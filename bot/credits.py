"""Per-student and class-wide daily credit system.

Credits are an abstract unit (1 credit ≈ 1 LLM call).

Limits:
  DAILY_CREDIT_LIMIT       — per student per day (default 20)
  GLOBAL_DAILY_CREDIT_LIMIT — whole class per day (default 1000)
  RESERVE_HOUR_UTC          — before this hour only 75% of global budget is
                               available, so night owls can't drain everything
                               before the afternoon lesson (default 14)

Rate limit:
  RATE_LIMIT_SECONDS — minimum gap between metered actions per student.
  Checked via context.user_data so it resets on bot restart (intentional —
  a restart clears any stuck state).

Free features (flashcards, game, profile, course exercises from the bank)
cost 0 and are never gated.
"""
from __future__ import annotations

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
from db.repo import (
    daily_credits_granted,
    daily_credits_used,
    global_credits_used,
    practice_streak,
    record_llm_usage,
)

# ---------------------------------------------------------------------------
# Cost table
# ---------------------------------------------------------------------------

COSTS: dict[str, int] = {
    "chat": 1,      # one conversation message or roleplay turn
    "explain": 1,   # "📖 Why?" / "➕ Example" correction buttons
    "quiz": 2,      # full /quiz session (7 questions)
    "daily": 2,     # /daily challenge (3 items)
    "pdf": 5,       # PDF upload + vocabulary extraction
    "learn": 3,     # /learn lesson from a document
    "summary": 1,   # /summary session analysis
    # /test is free — it comes out of a joining allowance so new students
    # are not penalised on day one.
}

# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _free_features_keyboard(en: bool) -> InlineKeyboardMarkup:
    if en:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🃏 Flashcards — /practice", callback_data="free:practice")],
            [InlineKeyboardButton("🎮 Play The Impostor — /impostor new", callback_data="free:impostor")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🃏 Karteikarten — /practice", callback_data="free:practice")],
        [InlineKeyboardButton("🎮 The Impostor spielen — /impostor new", callback_data="free:impostor")],
    ])


def capacity_exhausted_text(en: bool) -> str:
    if en:
        return (
            "🔴 I'm out of LLM capacity for today — the free providers have hit "
            "their daily limit. Try again tomorrow!\n\n"
            "These features are always free and available right now:"
        )
    return (
        "🔴 Alle LLM-Kontingente für heute sind aufgebraucht. Morgen geht's weiter!\n\n"
        "Diese Features sind immer kostenlos und jetzt verfügbar:"
    )


def capacity_exhausted_keyboard(en: bool) -> InlineKeyboardMarkup:
    return _free_features_keyboard(en)


def credits_exhausted_text(en: bool) -> str:
    if en:
        return (
            f"⚡ That's your {config.DAILY_CREDIT_LIMIT} credits for today — "
            "you've had a solid session! Come back tomorrow for more.\n\n"
            "These features are still completely free right now:"
        )
    return (
        f"⚡ Das war's für heute — {config.DAILY_CREDIT_LIMIT} Credits verbraucht, "
        "gute Session! Morgen wieder.\n\n"
        "Diese Features sind jetzt noch kostenlos:"
    )


def credits_exhausted_keyboard(en: bool) -> InlineKeyboardMarkup:
    return _free_features_keyboard(en)


def global_exhausted_text() -> str:
    return (
        "📊 The whole class has used up today's AI quota. "
        "Flashcards, games, and your course are still open — no limit on those. "
        "Quota resets at midnight UTC. 🔄"
    )


def global_exhausted_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🃏 Flashcards — /practice", callback_data="free:practice")],
        [InlineKeyboardButton("🎮 The Impostor — /impostor new", callback_data="free:impostor")],
    ])


def rate_limited_text(en: bool) -> str:
    if en:
        return "⏳ Slow down a little — wait a moment before your next message."
    return "⏳ Langsamer bitte — kurz warten vor der nächsten Nachricht. (Too fast!)"


# ---------------------------------------------------------------------------
# Credit checks
# ---------------------------------------------------------------------------

def _global_limit_for_now() -> int:
    """Return the effective global ceiling, accounting for the reserve pool."""
    full = config.GLOBAL_DAILY_CREDIT_LIMIT
    if datetime.utcnow().hour < config.RESERVE_HOUR_UTC:
        return int(full * 0.75)
    return full


def _effective_user_limit(user_id: int) -> int:
    """Base limit + teacher grants today + streak bonus (capped at 5)."""
    granted = daily_credits_granted(user_id)
    streak = practice_streak(user_id)
    bonus = min(streak, 5)
    return config.DAILY_CREDIT_LIMIT + granted + bonus


def credits_check(user_id: int, cost: int) -> str:
    """Return 'ok', 'global_limit', or 'user_limit'.

    Accounts for:
    • Per-class daily ceiling (with reserve pool before RESERVE_HOUR_UTC)
    • Per-student base limit + teacher grants + streak bonus (up to +5)
    """
    if cost <= 0:
        return "ok"
    if global_credits_used() + cost > _global_limit_for_now():
        return "global_limit"
    if daily_credits_used(user_id) + cost > _effective_user_limit(user_id):
        return "user_limit"
    return "ok"


def check_credits(user_id: int, cost: int) -> bool:
    """Backward-compat wrapper — returns True iff the action is permitted."""
    return credits_check(user_id, cost) == "ok"


def credits_remaining(user_id: int) -> int:
    """Credits this student has left today (after grants and streak bonus)."""
    used = daily_credits_used(user_id)
    return max(0, _effective_user_limit(user_id) - used)


def credit_error_response(
    en: bool, status: str
) -> tuple[str, InlineKeyboardMarkup]:
    """Return (text, keyboard) for a credits_check failure."""
    if status == "global_limit":
        return global_exhausted_text(), global_exhausted_keyboard()
    return credits_exhausted_text(en), credits_exhausted_keyboard(en)


# ---------------------------------------------------------------------------
# Rate limit (per-user, in-memory via context.user_data)
# ---------------------------------------------------------------------------

def check_rate_limit(context, cost: int = 1) -> bool:
    """Return False if the user is sending metered actions too fast.

    Uses context.user_data so state is per-user across handlers without a DB
    round-trip. Resets on bot restart (intentional).
    """
    if cost <= 0:
        return True
    now = datetime.utcnow()
    last = context.user_data.get("_last_llm_call")
    if last and (now - last).total_seconds() < config.RATE_LIMIT_SECONDS:
        return False
    context.user_data["_last_llm_call"] = now
    return True


# ---------------------------------------------------------------------------
# Spend
# ---------------------------------------------------------------------------

def spend(
    user_id: int,
    *,
    task: str,
    model: str = "unknown",
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> None:
    """Record one LLM usage row. Call after a successful LLM call."""
    cost = COSTS.get(task, 1)
    record_llm_usage(
        user_id,
        model=model,
        task=task,
        credits=cost,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
