"""Database engine/session setup. DB and tables auto-created on first import."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

import config
from db.models import Base, Class, ClassSetting  # noqa: F401 — registers tables with metadata

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
        "teacher_id": "INTEGER",
        "class_id": "INTEGER",
        # F-15 / F-16 / F-21 — subscription and public tier limits.
        "subscribed": "BOOLEAN NOT NULL DEFAULT 0",
        "subscription_expires_at": "DATETIME",
        "session_count": "INTEGER NOT NULL DEFAULT 0",
        "session_start": "DATETIME",
        "week_count": "INTEGER NOT NULL DEFAULT 0",
        "week_start": "DATETIME",
        "topup_credits": "INTEGER NOT NULL DEFAULT 0",
        # F-19 — placement status.
        "placement_status": "TEXT",
        # Unlimited credits flag — bypasses per-user and session/weekly caps.
        "unlimited_credits": "BOOLEAN NOT NULL DEFAULT 0",
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
    """Set role='superuser' and status='active' for the configured superuser."""
    if not config.SUPERUSER_TELEGRAM_ID:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE users SET role='superuser', status='active' "
                "WHERE telegram_id=:tid"
            ),
            {"tid": config.SUPERUSER_TELEGRAM_ID},
        )


def _guard_bot_language() -> None:
    """Stamp this database with its bot language and refuse a mismatched boot.

    Belt-and-braces isolation on top of config.py's DATABASE_URL check: the first
    time a locked bot opens a database it records BOT_LANGUAGE in class_settings.
    If a later boot opens a database stamped with a *different* language (e.g. the
    wrong file was copied or restored), we exit rather than write one bot's data
    into the other bot's database.
    """
    import sys

    lang = config.BOT_LANGUAGE
    if lang not in ("german", "english"):
        return
    key = "bot_language"
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT value FROM class_settings WHERE key = :k"), {"k": key}
        ).fetchone()
        stamped = row[0] if row else None
        if stamped is None:
            conn.execute(
                text(
                    "INSERT INTO class_settings (key, value, updated_at) "
                    "VALUES (:k, :v, :ts)"
                ),
                {"k": key, "v": lang, "ts": _now_iso()},
            )
        elif stamped != lang:
            sys.stderr.write(
                f"\n[db] Database {config.DATABASE_URL} belongs to the {stamped!r} "
                f"bot, but BOT_LANGUAGE={lang!r}.\n"
                f"     Refusing to start to avoid mixing the two bots' data. "
                f"Point DATABASE_URL at this bot's own file.\n\n"
            )
            sys.exit(1)


def _now_iso() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat(sep=" ")


def init_db() -> None:
    """Create all tables if they don't exist, then backfill new columns."""
    Base.metadata.create_all(engine)
    _apply_migrations()
    _migrate_language_chosen()
    _migrate_teacher_role()
    _guard_bot_language()


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
