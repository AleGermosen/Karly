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
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
from db.repo import (
    add_topup_credits,
    daily_credits_granted,
    daily_credits_used,
    get_public_limits_state,
    global_credits_used,
    practice_streak,
    record_llm_usage,
    reset_expired_windows,
    update_public_limits,
)

# ---------------------------------------------------------------------------
# Cost table
# ---------------------------------------------------------------------------

COSTS: dict[str, int] = {
    "chat": 1,         # one conversation message or roleplay turn
    "explain": 1,      # "📖 Why?" / "➕ Example" correction buttons
    "quiz": 2,         # full /quiz session (7 questions)
    "daily": 2,        # /daily challenge — fresh LLM generation
    "daily_cached": 1, # /daily — served from the shared daily cache (no LLM call)
    "pdf": 5,          # PDF upload + vocabulary extraction
    "learn": 3,        # /learn lesson from a document
    "summary": 1,      # /summary session analysis
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


def session_limit_text(en: bool, reset_in_min: int) -> str:
    if en:
        return (
            f"⏱ You've reached your session limit. "
            f"Your allowance resets in about *{reset_in_min} min*.\n\n"
            "Subscribe for more practice time, or buy a top-up pack:"
        )
    return (
        f"⏱ Dein Session-Limit ist erreicht. "
        f"Dein Kontingent wird in ca. *{reset_in_min} Min.* zurückgesetzt.\n\n"
        "Abonniere für mehr Übungszeit oder kauf ein Top-up-Paket:"
    )


def week_limit_text(en: bool) -> str:
    if en:
        return (
            "📅 You've used your weekly message allowance. "
            "Your limit resets next Monday.\n\n"
            "Subscribe to keep going, or buy a top-up pack:"
        )
    return (
        "📅 Du hast dein Wochenkontingent verbraucht. "
        "Es wird am Montag zurückgesetzt.\n\n"
        "Abonniere für mehr Übungszeit oder kauf ein Top-up-Paket:"
    )


def _limit_keyboard(en: bool) -> InlineKeyboardMarkup:
    if en:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ Subscribe (100 Stars/month)", callback_data="pay:subscribe")],
            [InlineKeyboardButton("➕ Buy message pack — /topup", callback_data="pay:topup")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Abonnieren (100 Stars/Monat)", callback_data="pay:subscribe")],
        [InlineKeyboardButton("➕ Nachrichten kaufen — /topup", callback_data="pay:topup")],
    ])


# ---------------------------------------------------------------------------
# Credit checks
# ---------------------------------------------------------------------------

def public_limit_check(user_id: int) -> tuple[str, bool]:
    """Check session/weekly public tier limits.

    Returns (status, use_topup) where status is one of:
      'ok'             — within session + week allowance
      'session_limit'  — session exhausted, no topup
      'week_limit'     — week exhausted, no topup
    and use_topup=True when topup credits cover an otherwise-blocked call.
    Teachers and superusers always get ('ok', False).
    """
    from datetime import datetime
    reset_expired_windows(user_id)
    state = get_public_limits_state(user_id)
    if not state:
        return "ok", False

    role = state.get("role", "student")
    if role in ("teacher", "superuser"):
        return "ok", False

    # Check subscription expiry.
    subscribed = state["subscribed"]
    if subscribed and state["subscription_expires_at"]:
        if state["subscription_expires_at"] < datetime.utcnow():
            subscribed = False  # expired — treat as free (cleared by nightly job)

    session_cap = config.SESSION_CAP_SUBSCRIBER if subscribed else config.SESSION_CAP_FREE
    week_cap = config.WEEK_CAP_SUBSCRIBER if subscribed else config.WEEK_CAP_FREE
    topup = state["topup_credits"]
    session_count = state["session_count"]
    week_count = state["week_count"]

    within_session = session_count < session_cap
    within_week = week_count < week_cap

    if within_session and within_week:
        return "ok", False
    if topup > 0:
        return "ok", True
    if not within_week:
        return "week_limit", False
    return "session_limit", False


def session_reset_minutes(user_id: int) -> int:
    """Minutes until the current session window resets."""
    from datetime import datetime
    state = get_public_limits_state(user_id)
    session_start = state.get("session_start")
    if not session_start:
        return 0
    window_end = session_start + __import__("datetime").timedelta(
        hours=config.SESSION_WINDOW_HOURS
    )
    remaining = (window_end - datetime.utcnow()).total_seconds()
    return max(0, int(remaining / 60))


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
    """Return 'ok', 'global_limit', 'user_limit', 'session_limit', or 'week_limit'.

    Checks in order:
    1. Classroom daily ceiling (global pool + per-student daily cap).
    2. Public subscription tier limits (session window + weekly cap).
    Topup credits transparently cover tier-limit hits — returns 'ok' in that case.
    """
    if cost <= 0:
        return "ok"
    if global_credits_used() + cost > _global_limit_for_now():
        return "global_limit"
    if daily_credits_used(user_id) + cost > _effective_user_limit(user_id):
        return "user_limit"
    status, _ = public_limit_check(user_id)
    return status


def check_credits(user_id: int, cost: int) -> bool:
    """Backward-compat wrapper — returns True iff the action is permitted."""
    return credits_check(user_id, cost) == "ok"


def credits_remaining(user_id: int) -> int:
    """Credits this student has left today (after grants and streak bonus)."""
    used = daily_credits_used(user_id)
    return max(0, _effective_user_limit(user_id) - used)


def credit_error_response(
    en: bool, status: str, user_id: int | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    """Return (text, keyboard) for a credits_check failure."""
    if status == "global_limit":
        return global_exhausted_text(), global_exhausted_keyboard()
    if status == "session_limit":
        mins = session_reset_minutes(user_id) if user_id else 60
        return session_limit_text(en, mins), _limit_keyboard(en)
    if status == "week_limit":
        return week_limit_text(en), _limit_keyboard(en)
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

def metered(task_name: str):
    """Decorator for handlers that spend credits.

    Wraps an async handler so it automatically checks credits before running
    and calls spend() after a successful LLM result. The decorated handler
    must receive `user` (a User ORM object) and `en` (bool) as its first two
    positional args after update/context, and must return the LLM result or
    None on failure.

    Usage::

        @require_auth
        @metered("chat")
        async def my_handler(update, context, user, en):
            ...
            return result  # LLM RouteResult, or None to skip spend
    """
    def decorator(handler):
        @wraps(handler)
        async def wrapper(update, context, *args, **kwargs):
            from db.repo import get_user_by_telegram_id as _get_user
            user = _get_user(update.effective_user.id) if not args else args[0]
            en = getattr(user, "learning_mode", "german") == "english" if user else False
            cost = COSTS.get(task_name, 1)
            status = credits_check(user.id, cost) if user else "ok"
            if status != "ok":
                text, kb = credit_error_response(en, status, user.id if user else None)
                await update.effective_message.reply_text(text, reply_markup=kb)
                return
            result = await handler(update, context, *args, **kwargs)
            if result is not None and user:
                model = getattr(getattr(result, "rung", None), "model_id", "unknown")
                spend(user.id, task=task_name, model=model)
            return result
        return wrapper
    return decorator


def spend(
    user_id: int,
    *,
    task: str,
    model: str = "unknown",
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> None:
    """Record one LLM usage row and update public tier counters."""
    cost = COSTS.get(task, 1)
    record_llm_usage(
        user_id,
        model=model,
        task=task,
        credits=cost,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    _, use_topup = public_limit_check(user_id)
    update_public_limits(user_id, use_topup=use_topup)
