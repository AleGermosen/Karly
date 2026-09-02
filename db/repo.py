"""Small data-access helpers shared across handlers."""
from __future__ import annotations

import json

from db.models import Assessment, Message, User, VocabItem, VocabSource
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


# --- Vocab -----------------------------------------------------------------

def add_vocab_items(
    user_id: int,
    items: list[dict],
    source: VocabSource,
    document_id: int | None = None,
) -> int:
    """Insert vocab items. Each dict: {term, translation?, context_sentence?}.

    Skips exact-duplicate terms for this user+source. Returns count inserted.
    """
    inserted = 0
    with get_session() as session:
        existing = {
            t[0]
            for t in session.query(VocabItem.term)
            .filter(VocabItem.user_id == user_id)
            .all()
        }
        for it in items:
            term = (it.get("term") or "").strip()
            if not term or term in existing:
                continue
            session.add(
                VocabItem(
                    user_id=user_id,
                    term=term,
                    translation=(it.get("translation") or None),
                    context_sentence=(it.get("context_sentence") or None),
                    source=source,
                    document_id=document_id,
                )
            )
            existing.add(term)
            inserted += 1
    return inserted


def vocab_count(user_id: int) -> int:
    with get_session() as session:
        return (
            session.query(VocabItem)
            .filter(VocabItem.user_id == user_id)
            .count()
        )


# --- Assessments -----------------------------------------------------------

def save_assessment(
    user_id: int, verdict: dict, transcript: list
) -> None:
    """Store an assessment and update the user's cefr_estimate."""
    with get_session() as session:
        session.add(
            Assessment(
                user_id=user_id,
                verdict_json=json.dumps(verdict, ensure_ascii=False),
                transcript_json=json.dumps(transcript, ensure_ascii=False),
            )
        )
        user = session.get(User, user_id)
        if user is not None:
            cefr = {
                "overall": verdict.get("overall"),
                "skills": verdict.get("skills", {}),
            }
            user.cefr_estimate = json.dumps(cefr, ensure_ascii=False)


def latest_assessment(user_id: int) -> dict | None:
    with get_session() as session:
        row = (
            session.query(Assessment)
            .filter(Assessment.user_id == user_id)
            .order_by(Assessment.date.desc(), Assessment.id.desc())
            .first()
        )
        if row is None or not row.verdict_json:
            return None
        try:
            return json.loads(row.verdict_json)
        except ValueError:
            return None
