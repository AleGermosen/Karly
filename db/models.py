"""SQLAlchemy models. All tables are created in Phase 0, even those used later."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    # JSON string: per-skill CEFR estimate.
    cefr_estimate: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Daily practice reminder time as "HH:MM" (local), or None if disabled.
    reminder_time: Mapped[str | None] = mapped_column(String, nullable=True)
    # Correction strictness: "strict" | "relaxed" | "off".
    # "relaxed" = only real errors; "strict" = everything; "off" = none.
    correction_level: Mapped[str] = mapped_column(String, default="relaxed")
    # Which language the user is learning: "german" (default) or "english".
    # German mode: native English speaker learning German.
    # English mode: native Spanish speaker learning English.
    learning_mode: Mapped[str] = mapped_column(String, default="german")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    @property
    def corrections_on(self) -> bool:
        """Backward-compat shim — true when any corrections are active."""
        return self.correction_level != "off"

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
