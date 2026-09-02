"""Small data-access helpers shared across handlers."""
from __future__ import annotations

import json

from db.models import Message, User
from db.session import get_session


def get_user_by_telegram_id(telegram_id: int) -> User | None:
    with get_session() as session:
        return (
            session.query(User)
            .filter(User.telegram_id == telegram_id)
            .one_or_none()
        )


def get_or_create_user(telegram_id: int, name: str | None = None) -> User:
    with get_session() as session:
        user = (
            session.query(User)
            .filter(User.telegram_id == telegram_id)
            .one_or_none()
        )
        if user is None:
            user = User(telegram_id=telegram_id, name=name)
            session.add(user)
            session.flush()
        elif name and not user.name:
            user.name = name
        session.refresh(user)
        return user


def any_user_exists() -> bool:
    with get_session() as session:
        return session.query(User).first() is not None


def add_message(
    user_id: int,
    role: str,
    text: str,
    corrections: list | None = None,
) -> None:
    with get_session() as session:
        session.add(
            Message(
                user_id=user_id,
                role=role,
                text=text,
                corrections_json=json.dumps(corrections) if corrections else None,
            )
        )


def recent_history(user_id: int, limit: int = 20) -> list[dict]:
    """Return the last `limit` messages oldest-first as {role, text} dicts."""
    with get_session() as session:
        rows = (
            session.query(Message)
            .filter(Message.user_id == user_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
            .all()
        )
    rows.reverse()
    return [{"role": r.role, "text": r.text} for r in rows]
