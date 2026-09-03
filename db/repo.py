"""Small data-access helpers shared across handlers."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import func

from db.models import (
    Assessment,
    Document,
    Message,
    PracticeLog,
    User,
    VocabItem,
    VocabSource,
)
from db.session import get_session
from srs import sm2


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


def recent_user_messages(user_id: int, limit: int = 30) -> list[str]:
    """Return the last `limit` user-authored message texts, oldest-first."""
    with get_session() as session:
        rows = (
            session.query(Message.text)
            .filter(Message.user_id == user_id, Message.role == "user")
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
            .all()
        )
    rows.reverse()
    return [r[0] for r in rows]


def set_correction_level(user_id: int, level: str) -> None:
    """Set correction_level to 'strict', 'relaxed', or 'off'."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.correction_level = level


def set_corrections(user_id: int, on: bool) -> None:
    set_correction_level(user_id, "strict" if on else "off")


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


# --- Practice / SRS --------------------------------------------------------

def _vocab_to_dict(v: VocabItem) -> dict:
    return {
        "id": v.id,
        "term": v.term,
        "translation": v.translation,
        "context_sentence": v.context_sentence,
        "easiness": v.sm2_easiness,
        "interval": v.sm2_interval,
        "repetitions": v.sm2_repetitions,
    }


def due_vocab(user_id: int, limit: int = 10, now: datetime | None = None) -> list[dict]:
    now = now or datetime.utcnow()
    with get_session() as session:
        rows = (
            session.query(VocabItem)
            .filter(
                VocabItem.user_id == user_id,
                VocabItem.next_review_at <= now,
            )
            .order_by(VocabItem.next_review_at.asc())
            .limit(limit)
            .all()
        )
        return [_vocab_to_dict(v) for v in rows]


def count_due(user_id: int, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    with get_session() as session:
        return (
            session.query(VocabItem)
            .filter(
                VocabItem.user_id == user_id,
                VocabItem.next_review_at <= now,
            )
            .count()
        )


def apply_grade(vocab_id: int, quality: int, now: datetime | None = None) -> datetime | None:
    """Apply an SM-2 grade to a vocab item. Returns the new next_review_at."""
    with get_session() as session:
        v = session.get(VocabItem, vocab_id)
        if v is None:
            return None
        state = sm2.update(
            v.sm2_easiness, v.sm2_interval, v.sm2_repetitions, quality, now=now
        )
        v.sm2_easiness = state.easiness
        v.sm2_interval = state.interval
        v.sm2_repetitions = state.repetitions
        v.next_review_at = state.next_review_at
        return state.next_review_at


def hardest_items(user_id: int, limit: int = 5) -> list[dict]:
    with get_session() as session:
        rows = (
            session.query(VocabItem)
            .filter(
                VocabItem.user_id == user_id,
                VocabItem.sm2_repetitions > 0,
            )
            .order_by(VocabItem.sm2_easiness.asc())
            .limit(limit)
            .all()
        )
        return [_vocab_to_dict(v) for v in rows]


def random_translations(user_id: int, exclude_id: int, limit: int = 3) -> list[str]:
    """Random distinct translations from the user's other vocab, for MCQ
    distractors. Excludes the item being tested and empty translations."""
    with get_session() as session:
        rows = (
            session.query(VocabItem.translation)
            .filter(
                VocabItem.user_id == user_id,
                VocabItem.id != exclude_id,
                VocabItem.translation.isnot(None),
                VocabItem.translation != "",
            )
            .order_by(func.random())
            .limit(limit * 3)  # over-fetch, then dedupe below
            .all()
        )
    seen: list[str] = []
    for (t,) in rows:
        if t not in seen:
            seen.append(t)
        if len(seen) >= limit:
            break
    return seen


def mark_due_by_terms(
    user_id: int, terms: list[str], now: datetime | None = None
) -> int:
    """Set next_review_at=now for the user's vocab items matching *terms*, so
    they surface immediately in the next practice session. Returns the count."""
    now = now or datetime.utcnow()
    terms = [t for t in terms if t]
    if not terms:
        return 0
    with get_session() as session:
        rows = (
            session.query(VocabItem)
            .filter(VocabItem.user_id == user_id, VocabItem.term.in_(terms))
            .all()
        )
        for v in rows:
            v.next_review_at = now
        return len(rows)


def record_practice(user_id: int) -> None:
    with get_session() as session:
        session.add(PracticeLog(user_id=user_id))


def practice_streak(user_id: int, now: datetime | None = None) -> int:
    """Consecutive days (up to today) with at least one practice session."""
    now = now or datetime.utcnow()
    with get_session() as session:
        rows = (
            session.query(PracticeLog.created_at)
            .filter(PracticeLog.user_id == user_id)
            .all()
        )
    days = {r[0].date() for r in rows}
    if not days:
        return 0
    today = now.date()
    # Allow the streak to count from today or yesterday (not yet practiced today).
    start = today if today in days else today - timedelta(days=1)
    if start not in days:
        return 0
    streak = 0
    cur = start
    while cur in days:
        streak += 1
        cur -= timedelta(days=1)
    return streak


# --- Reminders -------------------------------------------------------------

def set_reminder(user_id: int, hhmm: str | None) -> None:
    with get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.reminder_time = hhmm


# --- Documents -------------------------------------------------------------

def create_document(user_id: int, filename: str, summary: str | None) -> int:
    with get_session() as session:
        doc = Document(user_id=user_id, filename=filename, summary=summary)
        session.add(doc)
        session.flush()
        return doc.id


def set_document_term_count(document_id: int, count: int) -> None:
    with get_session() as session:
        doc = session.get(Document, document_id)
        if doc is not None:
            doc.extracted_terms_count = count


def list_documents(user_id: int) -> list[dict]:
    with get_session() as session:
        rows = (
            session.query(Document)
            .filter(Document.user_id == user_id)
            .order_by(Document.upload_date.desc(), Document.id.desc())
            .all()
        )
        return [
            {
                "id": d.id,
                "filename": d.filename,
                "summary": d.summary,
                "terms": d.extracted_terms_count,
            }
            for d in rows
        ]


def get_document(user_id: int, document_id: int) -> dict | None:
    with get_session() as session:
        d = session.get(Document, document_id)
        if d is None or d.user_id != user_id:
            return None
        terms = (
            session.query(VocabItem)
            .filter(VocabItem.document_id == document_id)
            .all()
        )
        return {
            "id": d.id,
            "filename": d.filename,
            "summary": d.summary,
            "terms": [
                {"term": t.term, "translation": t.translation}
                for t in terms
            ],
        }


def recent_document(user_id: int) -> dict | None:
    docs = list_documents(user_id)
    return docs[0] if docs else None


def users_with_reminders() -> list[tuple[int, int, str]]:
    """Return (user_id, telegram_id, hhmm) for users with a reminder set."""
    with get_session() as session:
        rows = (
            session.query(User.id, User.telegram_id, User.reminder_time)
            .filter(User.reminder_time.isnot(None))
            .all()
        )
        return [(r[0], r[1], r[2]) for r in rows]
