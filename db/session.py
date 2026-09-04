"""Database engine/session setup. DB and tables auto-created on first import."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

import config
from db.models import Base

engine = create_engine(config.DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

# Additive columns to backfill on existing databases (create_all never ALTERs).
# {table: {column: "SQL column definition"}}.
_MIGRATIONS: dict[str, dict[str, str]] = {
    "users": {
        "corrections_on": "BOOLEAN NOT NULL DEFAULT 1",
        "correction_level": "TEXT NOT NULL DEFAULT 'relaxed'",
        "learning_mode": "TEXT NOT NULL DEFAULT 'german'",
        "language_chosen": "BOOLEAN NOT NULL DEFAULT 0",
        "role": "TEXT NOT NULL DEFAULT 'student'",
        "class_name": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "joined_at": "DATETIME",
        "approved_by": "INTEGER",
    },
    "vocab_items": {
        "hlr_half_life": "REAL NOT NULL DEFAULT 0.0",
    },
}


def _apply_migrations() -> None:
    """Add any missing columns to already-created tables (idempotent)."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _MIGRATIONS.items():
            if table not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table)}
            for column, ddl in columns.items():
                if column not in have:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                    )


def _migrate_correction_level() -> None:
    """One-time data migration: map corrections_on=0 → correction_level='off'."""
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE users SET correction_level = 'off' "
            "WHERE corrections_on = 0 AND correction_level = 'relaxed'"
        ))


def _migrate_correction_level_to_int() -> None:
    """Convert old string correction_level values to the 0-5 integer scale.

    Mapping: 'off' → 0, 'relaxed' → 1 (gentle, the new default), 'strict' → 4.
    Any row that is already an integer string ('0'..'5') is left alone.
    """
    mapping = {"off": "0", "relaxed": "1", "strict": "4"}
    with engine.begin() as conn:
        for old, new in mapping.items():
            conn.execute(
                text("UPDATE users SET correction_level = :new WHERE correction_level = :old"),
                {"new": new, "old": old},
            )


def _migrate_language_chosen() -> None:
    """Mark any user who already has messages as having chosen their language.

    New users (no messages yet) keep language_chosen=0 and will be sent to the
    picker before any handler runs.
    """
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE users SET language_chosen = 1 "
            "WHERE id IN (SELECT DISTINCT user_id FROM messages)"
        ))


def _migrate_teacher_role() -> None:
    """Set role='teacher' and status='active' for the configured teacher user."""
    if not config.TEACHER_TELEGRAM_ID:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE users SET role='teacher', status='active' "
                "WHERE telegram_id=:tid"
            ),
            {"tid": config.TEACHER_TELEGRAM_ID},
        )


def init_db() -> None:
    """Create all tables if they don't exist, then backfill new columns."""
    Base.metadata.create_all(engine)
    _apply_migrations()
    _migrate_correction_level()
    _migrate_correction_level_to_int()
    _migrate_language_chosen()
    _migrate_teacher_role()


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
