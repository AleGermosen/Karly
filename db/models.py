"""SQLAlchemy models. All tables are created in Phase 0, even those used later."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.utcnow()


class VocabSource(str, enum.Enum):
    conversation = "conversation"
    assessment = "assessment"
    document = "document"
    personal = "personal"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    # JSON string: per-skill CEFR estimate.
    cefr_estimate: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Daily practice reminder time as "HH:MM" (local), or None if disabled.
    reminder_time: Mapped[str | None] = mapped_column(String, nullable=True)
    # Correction strictness on a 0-5 integer scale.
    # 0=Off, 1=Gentle (default), 2=Light, 3=Balanced, 4=Thorough, 5=Exam.
    correction_level: Mapped[int] = mapped_column(Integer, default=1)
    # Which language the user is learning: "german" (default) or "english".
    # German mode: native English speaker learning German.
    # English mode: native Spanish speaker learning English.
    learning_mode: Mapped[str] = mapped_column(String, default="german")
    # False until the user explicitly picks a language via /start or /language.
    # Unset users are redirected to the language picker before any handler runs.
    language_chosen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # Classroom fields.
    # role: "student" (default) | "teacher"
    # status: "active" (default) | "pending" (awaiting teacher approval) | "removed"
    # joined_at: set when a pending student is approved.
    # approved_by: telegram_id of the teacher who approved this student.
    # role: "student" | "teacher" | "superuser"
    role: Mapped[str] = mapped_column(String, default="student")
    class_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Which teacher (users.id) manages this student. Only superuser can change.
    teacher_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Which class (classes.id) this student is in. Teacher can change.
    class_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Subscription / public-tier limits (F-15, F-16, F-21).
    subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 3-hour session window counter.
    session_count: Mapped[int] = mapped_column(Integer, default=0)
    session_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Weekly counter (resets every Monday 00:00 UTC).
    week_count: Mapped[int] = mapped_column(Integer, default=0)
    week_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Purchased one-time credits (never expire).
    topup_credits: Mapped[int] = mapped_column(Integer, default=0)
    # F-19 — placement quiz status: "pending" | "completed" | "skipped" | None
    placement_status: Mapped[str | None] = mapped_column(String, nullable=True)

    @property
    def corrections_on(self) -> bool:
        """Backward-compat shim — true when any corrections are active."""
        return self.correction_level != 0

    assessments: Mapped[list["Assessment"]] = relationship(back_populates="user")
    vocab_items: Mapped[list["VocabItem"]] = relationship(back_populates="user")
    messages: Mapped[list["Message"]] = relationship(back_populates="user")
    documents: Mapped[list["Document"]] = relationship(back_populates="user")


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # JSON: CEFR levels + gap list.
    verdict_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="assessments")


class VocabItem(Base):
    __tablename__ = "vocab_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    term: Mapped[str] = mapped_column(String)
    translation: Mapped[str | None] = mapped_column(String, nullable=True)
    context_sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[VocabSource] = mapped_column(Enum(VocabSource))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True
    )

    # SM-2 spaced-repetition state.
    sm2_easiness: Mapped[float] = mapped_column(Float, default=2.5)
    sm2_interval: Mapped[int] = mapped_column(Integer, default=0)
    sm2_repetitions: Mapped[int] = mapped_column(Integer, default=0)
    next_review_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # HLR (Half-Life Regression) state — half-life in days. 0.0 = not yet used.
    hlr_half_life: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="vocab_items")
    document: Mapped["Document | None"] = relationship(back_populates="vocab_items")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String)  # "user" | "assistant"
    text: Mapped[str] = mapped_column(Text)
    corrections_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="messages")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String)
    upload_date: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    extracted_terms_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="documents")
    vocab_items: Mapped[list["VocabItem"]] = relationship(back_populates="document")


class PracticeLog(Base):
    """One row per practice session, used to compute the daily streak."""

    __tablename__ = "practice_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ReviewLog(Base):
    """One row per individual vocab review (card shown + outcome).

    Used by HLR and DKT. elapsed_days is the time since the item was last
    reviewed (0 on the first review), half_life is the HLR estimate at the
    time of review.
    """

    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    vocab_id: Mapped[int] = mapped_column(ForeignKey("vocab_items.id"), index=True)
    correct: Mapped[bool] = mapped_column(Boolean)
    elapsed_days: Mapped[float] = mapped_column(Float)
    half_life: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ConceptMastery(Base):
    """BKT mastery state per user, per skill (grammar, reading, …).

    state_json: JSON object {skill: p_mastered (float 0-1)}.
    """

    __tablename__ = "concept_mastery"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class CreditGrant(Base):
    """Extra credits given to a student by the teacher via /grant.

    These add to the student's effective daily allowance on top of the
    base DAILY_CREDIT_LIMIT and the streak bonus.
    """

    __tablename__ = "credit_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    granted_by: Mapped[int] = mapped_column(Integer)  # telegram_id of the teacher
    amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Class(Base):
    """A class managed by a teacher. Students belong to one class."""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    teacher_id: Mapped[int] = mapped_column(Integer, index=True)  # users.id of the teacher
    learning_mode: Mapped[str] = mapped_column(String, default="german")
    topic: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ClassSetting(Base):
    """Key-value store for class-wide teacher settings (e.g. assigned topic)."""

    __tablename__ = "class_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Broadcast(Base):
    """Log of teacher broadcast messages (F-18)."""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(Integer, index=True)  # users.id
    class_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_text: Mapped[str] = mapped_column(Text)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MediaTask(Base):
    """Teacher-posted media comprehension task (F-22)."""

    __tablename__ = "media_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(Integer, index=True)  # users.id
    class_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String)
    media_url: Mapped[str | None] = mapped_column(String, nullable=True)
    reference_summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MediaSubmission(Base):
    """Student summary submitted for a media task (F-22)."""

    __tablename__ = "media_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("media_tasks.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    submission_text: Mapped[str] = mapped_column(Text)
    score_comprehension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_accuracy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_language: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Payment(Base):
    """One row per Telegram Stars payment — subscriptions and top-up packs."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # "subscription" | "topup"
    stars_amount: Mapped[int] = mapped_column(Integer)
    credits_purchased: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_charge_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class LLMUsage(Base):
    """One row per metered LLM action — used for per-student daily credit gates.

    credits: cost in abstract credits (see bot/credits.py for the cost table).
    tokens_in / tokens_out: may be None for backends that don't report them.
    """

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    model: Mapped[str] = mapped_column(String)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task: Mapped[str] = mapped_column(String)   # "chat" | "quiz" | "daily" | …
    credits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class UnitProgress(Base):
    """One row per (user, unit) — tracks course progress (H3/H4).

    passed: True when the student reached the pass mark (≥ 80%) on any attempt.
    best_score: highest percentage achieved across all attempts (0.0–1.0).
    attempts: total number of times the student started the unit.
    """

    __tablename__ = "unit_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    unit_id: Mapped[str] = mapped_column(String, index=True)  # e.g. "en.a1.g01"
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    best_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0–1.0
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ItemAttempt(Base):
    """One row per question answered in a course unit (H3/H4).

    Correct answers with score < pass mark still feed H4's flashcard pipeline.
    item_id maps to the 'id' field in the JSONL bank (e.g. 'en.a1.g01.mcq.01').
    """

    __tablename__ = "item_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    unit_id: Mapped[str] = mapped_column(String, index=True)
    item_id: Mapped[str] = mapped_column(String)  # bank question id
    item_type: Mapped[str] = mapped_column(String)  # mcq | cloze | transform | produce
    correct: Mapped[bool] = mapped_column(Boolean)
    answer_given: Mapped[str | None] = mapped_column(Text, nullable=True)
    flashcard_created: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
