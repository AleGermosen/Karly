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


def init_db() -> None:
    """Create all tables if they don't exist, then backfill new columns."""
    Base.metadata.create_all(engine)
    _apply_migrations()
    _migrate_correction_level()


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
