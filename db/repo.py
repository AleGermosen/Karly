"""Small data-access helpers shared across handlers."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import func

from db.models import (
    Assessment,
    Assignment,
    Broadcast,
    Class,
    ClassSetting,
    ConceptMastery,
    CreditGrant,
    Document,
    ItemAttempt,
    LLMUsage,
    MediaSubmission,
    MediaTask,
    Message,
    Payment,
    PracticeLog,
    ReviewLog,
    UnitProgress,
    User,
    VocabItem,
    VocabSource,
)
from db.session import get_session
from srs import bkt as bkt_mod
from srs import hlr as hlr_mod
from srs import sm2


def get_user_by_telegram_id(telegram_id: int) -> User | None:
    with get_session() as session:
        return (
            session.query(User)
            .filter(User.telegram_id == telegram_id)
            .one_or_none()
        )


def get_or_create_user(
    telegram_id: int,
    name: str | None = None,
    default_status: str = "active",
) -> User:
    import config as _config
    with get_session() as session:
        user = (
            session.query(User)
            .filter(User.telegram_id == telegram_id)
            .one_or_none()
        )
        if user is None:
            is_superuser = bool(
                _config.SUPERUSER_TELEGRAM_ID
                and telegram_id == _config.SUPERUSER_TELEGRAM_ID
            )
            # Each bot owns its own database, so a new user is created directly
            # in this bot's locked language — no picker, no per-request rewrite.
            locked = _config.BOT_LANGUAGE if _config.BOT_LANGUAGE in ("german", "english") else None
            user = User(
                telegram_id=telegram_id,
                name=name,
                role="superuser" if is_superuser else "student",
                status="active" if is_superuser else default_status,
                learning_mode=locked or "german",
                language_chosen=bool(locked),
            )
            session.add(user)
            session.flush()
        elif name and (not user.name or user.name != name):
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


def set_correction_level(user_id: int, level: int) -> None:
    """Set correction_level to an integer 0-5 (0=Off … 5=Exam)."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            # Explicitly cast to Python int so SQLite stores numeric affinity.
            user.correction_level = int(max(0, min(5, int(level))))


def user_message_stats(user_id: int) -> tuple[int, datetime | None]:
    """Return (total_user_message_count, last_user_message_time) for warm-up rule."""
    with get_session() as session:
        rows = (
            session.query(Message.created_at)
            .filter(Message.user_id == user_id, Message.role == "user")
            .order_by(Message.created_at.desc())
            .all()
        )
    if not rows:
        return 0, None
    return len(rows), rows[0][0]


def set_learning_mode(user_id: int, mode: str) -> None:
    """Set learning_mode to 'german' or 'english'."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.learning_mode = mode


def set_language_chosen(user_id: int) -> None:
    """Mark that the user has explicitly chosen their language."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.language_chosen = True


def set_unlimited_credits(user_id: int, value: bool) -> None:
    """Grant or revoke the unlimited-credits flag for a user."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.unlimited_credits = value


# --- LLM usage / credit tracking -------------------------------------------

def record_llm_usage(
    user_id: int,
    *,
    model: str,
    task: str,
    credits: int,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> None:
    """Append one row to llm_usage for metering and billing."""
    with get_session() as session:
        session.add(LLMUsage(
            user_id=user_id,
            model=model,
            task=task,
            credits=credits,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        ))


def daily_credits_used(user_id: int) -> int:
    """Sum of credits charged to user_id since midnight UTC today."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with get_session() as session:
        result = (
            session.query(func.sum(LLMUsage.credits))
            .filter(
                LLMUsage.user_id == user_id,
                LLMUsage.created_at >= today_start,
            )
            .scalar()
        )
    return int(result or 0)


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


def due_vocab(
    user_id: int,
    limit: int = 10,
    now: datetime | None = None,
    source: str | None = None,
    document_id: int | None = None,
) -> list[dict]:
    """Return due vocab items, optionally filtered by source or document_id.

    source: one of "conversation", "assessment", "document" (VocabSource value).
    document_id: restrict to items from a specific uploaded document.
    """
    now = now or datetime.utcnow()
    with get_session() as session:
        q = session.query(VocabItem).filter(
            VocabItem.user_id == user_id,
            VocabItem.next_review_at <= now,
        )
        if source:
            q = q.filter(VocabItem.source == source)
        if document_id is not None:
            q = q.filter(VocabItem.document_id == document_id)
        rows = q.order_by(VocabItem.next_review_at.asc()).limit(limit).all()
        return [_vocab_to_dict(v) for v in rows]


def count_due(
    user_id: int,
    now: datetime | None = None,
    source: str | None = None,
) -> int:
    now = now or datetime.utcnow()
    with get_session() as session:
        q = session.query(VocabItem).filter(
            VocabItem.user_id == user_id,
            VocabItem.next_review_at <= now,
        )
        if source:
            q = q.filter(VocabItem.source == source)
        return q.count()


def count_due_by_source(user_id: int, now: datetime | None = None) -> dict[str, int]:
    """Return {source_name: due_count} for all three sources."""
    return {
        "conversation": count_due(user_id, now=now, source="conversation"),
        "assessment": count_due(user_id, now=now, source="assessment"),
        "document": count_due(user_id, now=now, source="document"),
    }


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


def apply_hlr_grade(
    vocab_id: int,
    user_id: int,
    quality: int,
    now: datetime | None = None,
) -> datetime | None:
    """Apply a grade using HLR scheduling, with review logging.

    quality is the SM-2 0-5 scale; quality < 3 = incorrect, >= 3 = correct.
    Also runs SM-2 to keep the easiness/interval fields in sync (used by
    /review stats). Returns the new next_review_at.
    """
    now = now or datetime.utcnow()
    correct = quality >= 3
    with get_session() as session:
        v = session.get(VocabItem, vocab_id)
        if v is None:
            return None

        # SM-2 update (keeps easiness/interval/repetitions consistent).
        sm2_state = sm2.update(
            v.sm2_easiness, v.sm2_interval, v.sm2_repetitions, quality, now=now
        )
        v.sm2_easiness = sm2_state.easiness
        v.sm2_interval = sm2_state.interval
        v.sm2_repetitions = sm2_state.repetitions

        # HLR update.
        prev_review = v.next_review_at - timedelta(days=max(v.sm2_interval, 1))
        elapsed = max(0.0, (now - prev_review).total_seconds() / 86400)
        old_h = v.hlr_half_life if v.hlr_half_life > 0 else hlr_mod.INIT_HALF_LIFE
        new_h = hlr_mod.update(old_h, elapsed, correct)
        v.hlr_half_life = new_h
        v.next_review_at = hlr_mod.next_review_at(new_h, now=now)

        # Log the review for DKT training.
        session.add(ReviewLog(
            user_id=user_id,
            vocab_id=vocab_id,
            correct=correct,
            elapsed_days=elapsed,
            half_life=old_h,
        ))

        return v.next_review_at


# --- BKT (Bayesian Knowledge Tracing) -------------------------------------

def get_bkt_state(user_id: int) -> dict[str, dict]:
    """Return the current per-skill BKT state for a user.

    Each value is a dict: {"p": float, "level": str | None}.
    Old flat {skill: float} rows are migrated on read.
    """
    with get_session() as session:
        row = (
            session.query(ConceptMastery)
            .filter(ConceptMastery.user_id == user_id)
            .one_or_none()
        )
        if row is None:
            return {s: {"p": bkt_mod.P_L0, "level": None} for s in bkt_mod.SKILLS}
        try:
            raw = json.loads(row.state_json)
        except (ValueError, TypeError):
            return {s: {"p": bkt_mod.P_L0, "level": None} for s in bkt_mod.SKILLS}
        # Migrate old flat format {skill: float} → {skill: {p, level}}.
        migrated = {}
        for s in bkt_mod.SKILLS:
            val = raw.get(s, bkt_mod.P_L0)
            if isinstance(val, dict):
                migrated[s] = val
            else:
                migrated[s] = {"p": float(val), "level": None}
        return migrated


def update_bkt_state(
    user_id: int, skill: str, correct: bool, level: str | None = None
) -> float:
    """Update BKT mastery for a skill after one observation.

    level is the CEFR level of the item that was answered (e.g. "A2").
    Returns the new mastery probability for that skill.
    """
    if skill not in bkt_mod.SKILLS:
        return 0.0
    with get_session() as session:
        row = (
            session.query(ConceptMastery)
            .filter(ConceptMastery.user_id == user_id)
            .one_or_none()
        )
        if row is None:
            state: dict = {
                s: {"p": bkt_mod.P_L0, "level": None} for s in bkt_mod.SKILLS
            }
            row = ConceptMastery(user_id=user_id, state_json=json.dumps(state))
            session.add(row)
        else:
            try:
                raw = json.loads(row.state_json)
            except (ValueError, TypeError):
                raw = {}
            # Migrate old flat format on write too.
            state = {}
            for s in bkt_mod.SKILLS:
                val = raw.get(s, bkt_mod.P_L0)
                state[s] = val if isinstance(val, dict) else {"p": float(val), "level": None}

        entry = state.get(skill, {"p": bkt_mod.P_L0, "level": None})
        new_p = bkt_mod.update(entry["p"], correct)
        # Update level if a more recent one is provided.
        new_level = level if level else entry.get("level")
        state[skill] = {"p": new_p, "level": new_level}
        row.state_json = json.dumps(state)
        row.updated_at = datetime.utcnow()
        return new_p


# --- DKT review history ----------------------------------------------------

def weekly_practice_count(user_id: int, now: datetime | None = None) -> int:
    """Number of practice sessions in the last 7 days."""
    now = now or datetime.utcnow()
    since = now - timedelta(days=7)
    with get_session() as session:
        return (
            session.query(PracticeLog)
            .filter(PracticeLog.user_id == user_id, PracticeLog.created_at >= since)
            .count()
        )


def weekly_review_stats(
    user_id: int, now: datetime | None = None
) -> dict[str, int]:
    """Review counts for the current week and the prior week from ReviewLog.

    Returns {"this_total", "this_correct", "prev_total", "prev_correct"}.
    """
    now = now or datetime.utcnow()
    this_start = now - timedelta(days=7)
    prev_start = now - timedelta(days=14)
    with get_session() as session:
        this_rows = (
            session.query(ReviewLog)
            .filter(
                ReviewLog.user_id == user_id,
                ReviewLog.created_at >= this_start,
            )
            .all()
        )
        prev_rows = (
            session.query(ReviewLog)
            .filter(
                ReviewLog.user_id == user_id,
                ReviewLog.created_at >= prev_start,
                ReviewLog.created_at < this_start,
            )
            .all()
        )
    return {
        "this_total": len(this_rows),
        "this_correct": sum(1 for r in this_rows if r.correct),
        "prev_total": len(prev_rows),
        "prev_correct": sum(1 for r in prev_rows if r.correct),
    }


def weekly_corrections(
    user_id: int, limit: int = 20, now: datetime | None = None
) -> list[str]:
    """Unique corrected forms (context_sentence strings) from the last 7 days.

    Pulls from Message.corrections_json on assistant turns that had corrections.
    """
    now = now or datetime.utcnow()
    since = now - timedelta(days=7)
    with get_session() as session:
        rows = (
            session.query(Message.corrections_json)
            .filter(
                Message.user_id == user_id,
                Message.role == "assistant",
                Message.corrections_json.isnot(None),
                Message.created_at >= since,
            )
            .order_by(Message.created_at.desc())
            .limit(50)
            .all()
        )
    seen: list[str] = []
    for (cj,) in rows:
        try:
            items = json.loads(cj)
        except (ValueError, TypeError):
            continue
        for it in items:
            line = it.get("context_sentence", "")
            if line and line not in seen:
                seen.append(line)
            if len(seen) >= limit:
                return seen
    return seen


def review_history_for_dkt(
    user_id: int,
) -> tuple[list[dict], dict[int, int], int]:
    """Load review history and build an item-index map for DKT.

    Returns:
        reviews      — list of {item_idx, correct} oldest-first
        item_idx_map — {vocab_id: item_idx}
        n_items      — number of distinct vocab items seen
    """
    with get_session() as session:
        rows = (
            session.query(ReviewLog)
            .filter(ReviewLog.user_id == user_id)
            .order_by(ReviewLog.created_at.asc(), ReviewLog.id.asc())
            .all()
        )

    vocab_ids: list[int] = []
    seen: dict[int, int] = {}
    for r in rows:
        if r.vocab_id not in seen:
            seen[r.vocab_id] = len(seen)
        vocab_ids.append(r.vocab_id)

    reviews = [
        {"item_idx": seen[r.vocab_id], "correct": r.correct}
        for r in rows
    ]
    return reviews, seen, len(seen)


# --- Classroom -----------------------------------------------------------------

def get_user_by_id(user_id: int) -> User | None:
    with get_session() as session:
        return session.query(User).filter(User.id == user_id).one_or_none()


def set_user_status(user_id: int, status: str) -> None:
    with get_session() as session:
        user = session.query(User).filter(User.id == user_id).one_or_none()
        if user:
            user.status = status


def approve_student(user_id: int, approved_by: int, mode: str) -> None:
    """Activate a pending student: set status, language, and timestamps."""
    with get_session() as session:
        user = session.query(User).filter(User.id == user_id).one_or_none()
        if user:
            user.status = "active"
            user.learning_mode = mode
            user.language_chosen = True
            user.joined_at = datetime.utcnow()
            user.approved_by = approved_by


def list_students(include_pending: bool = True) -> list[User]:
    """All student-role users, active and optionally pending."""
    statuses = ["active", "pending"] if include_pending else ["active"]
    with get_session() as session:
        return (
            session.query(User)
            .filter(User.role == "student", User.status.in_(statuses))
            .order_by(User.name)
            .all()
        )


def student_last_active(user_id: int) -> datetime | None:
    """Timestamp of the most recent message from this student (or None)."""
    with get_session() as session:
        return (
            session.query(func.max(Message.created_at))
            .filter(Message.user_id == user_id, Message.role == "user")
            .scalar()
        )


def global_credits_used() -> int:
    """Total credits spent by ALL users since midnight UTC today."""
    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with get_session() as session:
        result = (
            session.query(func.sum(LLMUsage.credits))
            .filter(LLMUsage.created_at >= since)
            .scalar()
        )
        return result or 0


def daily_credits_granted(user_id: int) -> int:
    """Extra credits granted to this user today via /grant."""
    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with get_session() as session:
        result = (
            session.query(func.sum(CreditGrant.amount))
            .filter(CreditGrant.user_id == user_id, CreditGrant.created_at >= since)
            .scalar()
        )
        return result or 0


def grant_credits(user_id: int, granted_by: int, amount: int) -> None:
    """Record a credit grant from a teacher to a student."""
    with get_session() as session:
        session.add(CreditGrant(user_id=user_id, granted_by=granted_by, amount=amount))


def top_credit_consumers(limit: int = 5) -> list[dict]:
    """Top N users by credits spent today, descending. Returns [{name, credits}]."""
    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with get_session() as session:
        rows = (
            session.query(
                User.name,
                User.telegram_id,
                func.sum(LLMUsage.credits).label("total"),
            )
            .join(LLMUsage, LLMUsage.user_id == User.id)
            .filter(LLMUsage.created_at >= since)
            .group_by(User.id)
            .order_by(func.sum(LLMUsage.credits).desc())
            .limit(limit)
            .all()
        )
        return [
            {"name": row.name or f"id={row.telegram_id}", "credits": row.total or 0}
            for row in rows
        ]


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


def random_terms(user_id: int, exclude_id: int, limit: int = 3) -> list[str]:
    """Random German terms from the user's vocab (for EN→DE MCQ distractors)."""
    with get_session() as session:
        rows = (
            session.query(VocabItem.term)
            .filter(VocabItem.user_id == user_id, VocabItem.id != exclude_id)
            .order_by(func.random())
            .limit(limit * 3)
            .all()
        )
    seen: list[str] = []
    for (t,) in rows:
        if t and t not in seen:
            seen.append(t)
        if len(seen) >= limit:
            break
    return seen


# ---------------------------------------------------------------------------
# Class settings (teacher-controlled key-value store)
# ---------------------------------------------------------------------------

def get_class_setting(key: str) -> str | None:
    with get_session() as session:
        row = session.query(ClassSetting).filter(ClassSetting.key == key).one_or_none()
        return row.value if row else None


def set_class_setting(key: str, value: str | None) -> None:
    with get_session() as session:
        row = session.query(ClassSetting).filter(ClassSetting.key == key).one_or_none()
        if row is None:
            row = ClassSetting(key=key, value=value)
            session.add(row)
        else:
            row.value = value
            row.updated_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Class-wide skill error rates (for teacher dashboard)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Teacher management (superuser only)
# ---------------------------------------------------------------------------

def list_teachers() -> list[User]:
    with get_session() as session:
        return (
            session.query(User)
            .filter(User.role.in_(["teacher", "superuser"]))
            .order_by(User.name)
            .all()
        )


def set_user_role(user_id: int, role: str) -> None:
    with get_session() as session:
        user = session.query(User).filter(User.id == user_id).one_or_none()
        if user:
            user.role = role


def assign_student_teacher(student_id: int, teacher_id: int | None) -> None:
    """Set which teacher manages a student. Superuser only."""
    with get_session() as session:
        student = session.query(User).filter(User.id == student_id).one_or_none()
        if student:
            student.teacher_id = teacher_id
            student.class_id = None  # reset class when teacher changes


# ---------------------------------------------------------------------------
# Class management
# ---------------------------------------------------------------------------

def create_class(name: str, teacher_id: int, learning_mode: str = "german") -> "Class":
    with get_session() as session:
        cls = Class(name=name, teacher_id=teacher_id, learning_mode=learning_mode)
        session.add(cls)
        session.flush()
        session.refresh(cls)
        return cls


def get_class_by_id(class_id: int) -> "Class | None":
    with get_session() as session:
        return session.query(Class).filter(Class.id == class_id).one_or_none()


def list_classes(teacher_id: int) -> list["Class"]:
    with get_session() as session:
        return (
            session.query(Class)
            .filter(Class.teacher_id == teacher_id)
            .order_by(Class.name)
            .all()
        )


def set_class_topic(class_id: int, topic: str | None) -> None:
    with get_session() as session:
        cls = session.query(Class).filter(Class.id == class_id).one_or_none()
        if cls:
            cls.topic = topic


def get_student_topic(user_id: int) -> str | None:
    """Return the topic for a student's class, or None if unset."""
    with get_session() as session:
        student = session.query(User).filter(User.id == user_id).one_or_none()
        if not student or not student.class_id:
            return None
        cls = session.query(Class).filter(Class.id == student.class_id).one_or_none()
        return cls.topic if cls else None


def assign_student_class(student_id: int, class_id: int | None) -> None:
    with get_session() as session:
        student = session.query(User).filter(User.id == student_id).one_or_none()
        if student:
            student.class_id = class_id


def list_students_in_class(class_id: int) -> list[User]:
    with get_session() as session:
        return (
            session.query(User)
            .filter(User.class_id == class_id, User.role == "student")
            .order_by(User.name)
            .all()
        )


def list_students_for_teacher(teacher_id: int, include_pending: bool = True) -> list[User]:
    """Students assigned to this teacher."""
    statuses = ["active", "pending"] if include_pending else ["active"]
    with get_session() as session:
        return (
            session.query(User)
            .filter(
                User.teacher_id == teacher_id,
                User.role == "student",
                User.status.in_(statuses),
            )
            .order_by(User.name)
            .all()
        )


def class_student_count(class_id: int) -> int:
    with get_session() as session:
        return (
            session.query(func.count(User.id))
            .filter(User.class_id == class_id)
            .scalar()
            or 0
        )


def class_skill_error_rates() -> dict[str, dict]:
    """Return per-skill stats across all active students.

    Returns {skill: {"mastery_avg": float, "struggling_pct": float, "n": int}}
    where struggling_pct is the % of students below 50% mastery on that skill.
    """
    from srs import bkt as _bkt
    students = list_students(include_pending=False)
    if not students:
        return {}

    skill_data: dict[str, list[float]] = {}
    for student in students:
        state = get_bkt_state(student.id)
        for skill, entry in state.items():
            p = entry.get("p", _bkt.P_L0)
            skill_data.setdefault(skill, []).append(p)

    result: dict[str, dict] = {}
    for skill, values in skill_data.items():
        n = len(values)
        avg = sum(values) / n
        struggling = sum(1 for p in values if p < 0.5)
        result[skill] = {
            "mastery_avg": round(avg * 100),
            "struggling_pct": round(struggling / n * 100),
            "n": n,
        }
    return result


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


# --- Subscription / top-ups / payments (F-15, F-16, F-21) ------------------

def get_user_by_id(user_id: int) -> User | None:
    with get_session() as session:
        return session.get(User, user_id)


def set_subscribed(user_id: int, days: int = 30) -> None:
    with get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.subscribed = True
            user.subscription_expires_at = datetime.utcnow() + timedelta(days=days)


def clear_expired_subscriptions() -> int:
    """Clear subscriptions past their expiry date. Returns number cleared."""
    now = datetime.utcnow()
    cleared = 0
    with get_session() as session:
        expired = (
            session.query(User)
            .filter(User.subscribed.is_(True), User.subscription_expires_at < now)
            .all()
        )
        for u in expired:
            u.subscribed = False
            cleared += 1
    return cleared


def add_topup_credits(user_id: int, amount: int) -> None:
    with get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.topup_credits = (user.topup_credits or 0) + amount


def record_payment(
    user_id: int,
    *,
    kind: str,
    stars_amount: int | None = None,
    credits_purchased: int | None = None,
    telegram_charge_id: str | None = None,
) -> None:
    with get_session() as session:
        session.add(Payment(
            user_id=user_id,
            kind=kind,
            stars_amount=stars_amount,
            credits_purchased=credits_purchased,
            telegram_charge_id=telegram_charge_id,
        ))


def get_public_limits_state(user_id: int) -> dict:
    """Return a snapshot of the user's session/week/topup state for limit checks."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            return {}
        return {
            "role": user.role,
            "subscribed": user.subscribed,
            "subscription_expires_at": user.subscription_expires_at,
            "session_count": user.session_count or 0,
            "session_start": user.session_start,
            "week_count": user.week_count or 0,
            "week_start": user.week_start,
            "topup_credits": user.topup_credits or 0,
        }


def update_public_limits(user_id: int, *, use_topup: bool) -> None:
    """Increment session/week counters, or decrement topup if use_topup is True."""
    now = datetime.utcnow()
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            return
        if use_topup:
            user.topup_credits = max(0, (user.topup_credits or 0) - 1)
        else:
            user.session_count = (user.session_count or 0) + 1
            user.week_count = (user.week_count or 0) + 1
            if user.session_start is None:
                user.session_start = now
            if user.week_start is None:
                user.week_start = now


def reset_expired_windows(user_id: int) -> None:
    """Reset session/week counters if their windows have expired.

    Call this before reading the counters so stale values don't block users.
    """
    now = datetime.utcnow()
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            return
        # Session window: 3 hours.
        import config as _cfg
        session_hours = _cfg.SESSION_WINDOW_HOURS
        if (
            user.session_start is None
            or (now - user.session_start).total_seconds() > session_hours * 3600
        ):
            user.session_count = 0
            user.session_start = now

        # Week window: resets each Monday at 00:00 UTC.
        monday = now - timedelta(days=now.weekday())
        monday_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        if user.week_start is None or user.week_start < monday_start:
            user.week_count = 0
            user.week_start = monday_start


# --- F-17: personal vocabulary -----------------------------------------------

def find_personal_word(user_id: int, term: str) -> bool:
    """Return True if the user already has this term in their personal deck."""
    with get_session() as session:
        row = (
            session.query(VocabItem)
            .filter(
                VocabItem.user_id == user_id,
                VocabItem.term == term,
                VocabItem.source == VocabSource.personal,
            )
            .first()
        )
        return row is not None


def add_personal_word(
    user_id: int,
    term: str,
    definition: str,
    example: str,
    part_of_speech: str,
) -> None:
    """Insert one personal flashcard into the user's HLR deck."""
    with get_session() as session:
        session.add(VocabItem(
            user_id=user_id,
            term=term,
            translation=f"({part_of_speech}) {definition}",
            context_sentence=example,
            source=VocabSource.personal,
        ))


# --- F-18: broadcasts --------------------------------------------------------

def log_broadcast(
    teacher_id: int,
    message_text: str,
    recipient_count: int,
    class_id: int | None = None,
) -> None:
    with get_session() as session:
        session.add(Broadcast(
            teacher_id=teacher_id,
            class_id=class_id,
            message_text=message_text,
            recipient_count=recipient_count,
        ))


def list_all_students() -> list[User]:
    """All active students across all classes."""
    with get_session() as session:
        return (
            session.query(User)
            .filter(User.role == "student", User.status == "active")
            .all()
        )


def list_students_by_teacher(teacher_id: int) -> list[User]:
    """All active students assigned to a given teacher."""
    with get_session() as session:
        return (
            session.query(User)
            .filter(
                User.role == "student",
                User.status == "active",
                User.teacher_id == teacher_id,
            )
            .all()
        )


# --- F-19: placement status --------------------------------------------------

def set_placement_status(user_id: int, status: str) -> None:
    """status: 'pending' | 'completed' | 'skipped'"""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is not None:
            user.placement_status = status


# --- F-22: media tasks -------------------------------------------------------

def create_media_task(
    teacher_id: int,
    title: str,
    reference_summary: str,
    media_url: str | None = None,
    class_id: int | None = None,
) -> int:
    with get_session() as session:
        t = MediaTask(
            teacher_id=teacher_id,
            class_id=class_id,
            title=title,
            reference_summary=reference_summary,
            media_url=media_url,
        )
        session.add(t)
        session.flush()
        return t.id


def get_active_media_task(class_id: int | None, teacher_id: int | None = None) -> "MediaTask | None":
    """Return the most recent open task for this class/teacher."""
    with get_session() as session:
        q = session.query(MediaTask).filter(MediaTask.closed_at.is_(None))
        if class_id is not None:
            q = q.filter(MediaTask.class_id == class_id)
        elif teacher_id is not None:
            q = q.filter(MediaTask.teacher_id == teacher_id)
        return q.order_by(MediaTask.created_at.desc()).first()


def close_media_task(task_id: int) -> None:
    with get_session() as session:
        t = session.get(MediaTask, task_id)
        if t is not None:
            t.closed_at = datetime.utcnow()


def upsert_media_submission(
    task_id: int,
    student_id: int,
    submission_text: str,
    score_comprehension: int,
    score_accuracy: int,
    score_language: int,
    feedback: str,
) -> None:
    with get_session() as session:
        existing = (
            session.query(MediaSubmission)
            .filter(
                MediaSubmission.task_id == task_id,
                MediaSubmission.student_id == student_id,
            )
            .first()
        )
        total = score_comprehension + score_accuracy + score_language
        if existing:
            existing.submission_text = submission_text
            existing.score_comprehension = score_comprehension
            existing.score_accuracy = score_accuracy
            existing.score_language = score_language
            existing.score_total = total
            existing.feedback = feedback
            existing.submitted_at = datetime.utcnow()
        else:
            session.add(MediaSubmission(
                task_id=task_id,
                student_id=student_id,
                submission_text=submission_text,
                score_comprehension=score_comprehension,
                score_accuracy=score_accuracy,
                score_language=score_language,
                score_total=total,
                feedback=feedback,
            ))


def get_media_submissions(task_id: int) -> list[dict]:
    with get_session() as session:
        rows = (
            session.query(MediaSubmission, User.name)
            .join(User, User.id == MediaSubmission.student_id)
            .filter(MediaSubmission.task_id == task_id)
            .order_by(MediaSubmission.score_total.desc())
            .all()
        )
        return [
            {
                "name": name or str(sub.student_id),
                "total": sub.score_total,
                "comprehension": sub.score_comprehension,
                "accuracy": sub.score_accuracy,
                "language": sub.score_language,
                "feedback": sub.feedback,
                "submitted_at": sub.submitted_at,
            }
            for sub, name in rows
        ]


# ---------------------------------------------------------------------------
# Course — unit progress (H3 / H4)
# ---------------------------------------------------------------------------

def get_unit_progress(user_id: int, unit_id: str) -> UnitProgress | None:
    with get_session() as session:
        return (
            session.query(UnitProgress)
            .filter(UnitProgress.user_id == user_id, UnitProgress.unit_id == unit_id)
            .one_or_none()
        )


def get_all_unit_progress(user_id: int) -> dict[str, UnitProgress]:
    """Return {unit_id: UnitProgress} for all units the user has touched."""
    with get_session() as session:
        rows = session.query(UnitProgress).filter(UnitProgress.user_id == user_id).all()
        return {r.unit_id: r for r in rows}


def record_unit_attempt(
    user_id: int,
    unit_id: str,
    score: float,  # 0.0–1.0
    pass_mark: float = 0.80,
) -> UnitProgress:
    """Upsert a unit attempt and return the updated progress row."""
    with get_session() as session:
        row = (
            session.query(UnitProgress)
            .filter(UnitProgress.user_id == user_id, UnitProgress.unit_id == unit_id)
            .one_or_none()
        )
        if row is None:
            row = UnitProgress(user_id=user_id, unit_id=unit_id)
            session.add(row)
        row.attempts += 1
        row.last_attempt_at = datetime.utcnow()
        if score > row.best_score:
            row.best_score = score
        if score >= pass_mark:
            row.passed = True
        return row


def record_item_attempt(
    user_id: int,
    unit_id: str,
    item_id: str,
    item_type: str,
    correct: bool,
    answer_given: str | None = None,
) -> ItemAttempt:
    with get_session() as session:
        row = ItemAttempt(
            user_id=user_id,
            unit_id=unit_id,
            item_id=item_id,
            item_type=item_type,
            correct=correct,
            answer_given=answer_given,
        )
        session.add(row)
        return row


def get_missed_items(user_id: int, unit_id: str) -> list[str]:
    """Return item_ids that the user got wrong at least once in this unit."""
    with get_session() as session:
        wrong = (
            session.query(ItemAttempt.item_id)
            .filter(
                ItemAttempt.user_id == user_id,
                ItemAttempt.unit_id == unit_id,
                ItemAttempt.correct == False,  # noqa: E712
            )
            .distinct()
            .all()
        )
        return [r.item_id for r in wrong]


def mark_flashcard_created(user_id: int, unit_id: str, item_id: str) -> None:
    with get_session() as session:
        session.query(ItemAttempt).filter(
            ItemAttempt.user_id == user_id,
            ItemAttempt.unit_id == unit_id,
            ItemAttempt.item_id == item_id,
            ItemAttempt.flashcard_created == False,  # noqa: E712
        ).update({"flashcard_created": True})


# --- F-14: assignments -------------------------------------------------------

def assign_unit(
    unit_id: str,
    assigned_by: int,  # users.id of the teacher
    *,
    student_id: int | None = None,
    class_id: int | None = None,
) -> None:
    """Create (or replace) an active assignment for a student or class."""
    with get_session() as session:
        # Clear any previous active assignment for the same target.
        q = session.query(Assignment).filter(
            Assignment.unit_id != "",  # always true — just to get a query
            Assignment.dismissed_at.is_(None),
        )
        if student_id is not None:
            q = q.filter(Assignment.student_id == student_id, Assignment.class_id.is_(None))
        else:
            q = q.filter(Assignment.class_id == class_id, Assignment.student_id.is_(None))
        q.update({"dismissed_at": datetime.utcnow()})

        a = Assignment(
            unit_id=unit_id,
            assigned_by=assigned_by,
            student_id=student_id,
            class_id=class_id,
        )
        session.add(a)


def clear_assignment(
    *,
    student_id: int | None = None,
    class_id: int | None = None,
) -> int:
    """Dismiss all active assignments for a student or class. Returns count cleared."""
    with get_session() as session:
        q = session.query(Assignment).filter(Assignment.dismissed_at.is_(None))
        if student_id is not None:
            q = q.filter(Assignment.student_id == student_id, Assignment.class_id.is_(None))
        else:
            q = q.filter(Assignment.class_id == class_id, Assignment.student_id.is_(None))
        count = q.count()
        q.update({"dismissed_at": datetime.utcnow()})
        return count


def get_active_assignment(user: "User") -> str | None:
    """Return the assigned unit_id for this student, or None.

    Checks student-level assignment first, then falls back to class-level.
    """
    with get_session() as session:
        # Student-specific assignment
        row = (
            session.query(Assignment)
            .filter(
                Assignment.student_id == user.id,
                Assignment.dismissed_at.is_(None),
            )
            .order_by(Assignment.assigned_at.desc())
            .first()
        )
        if row:
            return row.unit_id

        # Class-level assignment
        if user.class_id is not None:
            row = (
                session.query(Assignment)
                .filter(
                    Assignment.class_id == user.class_id,
                    Assignment.dismissed_at.is_(None),
                )
                .order_by(Assignment.assigned_at.desc())
                .first()
            )
            if row:
                return row.unit_id

        return None


def dismiss_assignment_for_student(user_id: int, unit_id: str) -> None:
    """Dismiss a class-level (or student-level) assignment when the student passes."""
    with get_session() as session:
        session.query(Assignment).filter(
            Assignment.student_id == user_id,
            Assignment.unit_id == unit_id,
            Assignment.dismissed_at.is_(None),
        ).update({"dismissed_at": datetime.utcnow()})


# --- Personalization memory --------------------------------------------------

def update_user_memory(
    user_id: int,
    *,
    profile_notes: str | None = None,
    last_session_summary: str | None = None,
) -> None:
    """Persist profile notes and/or the last-session summary for a user."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            return
        if profile_notes is not None:
            user.profile_notes = profile_notes
        if last_session_summary is not None:
            user.last_session_summary = last_session_summary
