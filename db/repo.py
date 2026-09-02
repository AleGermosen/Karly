"""Small data-access helpers shared across handlers."""
from __future__ import annotations

from db.models import User
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
