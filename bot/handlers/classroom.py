"""Teacher-facing classroom commands and approval callbacks.

Commands (teacher only):
  /students          — roster of all students (active + pending)
  /student <name>    — one student's learning profile
  /class             — class-wide weekly summary
  /budget            — today's global credit usage + top consumers
  /grant <name> <n>  — give a student N extra credits today

Callback patterns (sent to teacher via DM, initiated from approval flow):
  approve_student:<user_db_id>:<mode>  — approve a pending student
  decline_student:<user_db_id>         — decline a pending student
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

import config
from bot.middleware import require_auth
from bot import credits as credit_mod
from db.repo import (
    approve_student,
    get_user_by_id,
    get_user_by_telegram_id,
    global_credits_used,
    grant_credits,
    latest_assessment,
    list_students,
    practice_streak,
    set_user_status,
    student_last_active,
    top_credit_consumers,
    vocab_count,
    weekly_practice_count,
)

logger = logging.getLogger(__name__)


def _is_teacher(user) -> bool:
    return (
        config.TEACHER_TELEGRAM_ID is not None
        and user is not None
        and user.telegram_id == config.TEACHER_TELEGRAM_ID
    )


def _time_ago(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    delta = datetime.utcnow() - dt
    if delta.days == 0:
        h = delta.seconds // 3600
        m = delta.seconds // 60
        if h >= 1:
            return f"{h}h ago"
        return f"{m}m ago" if m else "just now"
    return f"{delta.days}d ago"


def _status_icon(last_active: datetime | None, status: str) -> str:
    if status == "pending":
        return "⏳"
    if status == "removed":
        return "🚫"
    if last_active is None:
        return "🆕"
    delta = datetime.utcnow() - last_active
    if delta.days < 1:
        return "🟢"
    if delta.days < 7:
        return "🟡"
    return "🔴"


def _cefr_level(user) -> str:
    if user.cefr_estimate:
        try:
            data = json.loads(user.cefr_estimate)
            if isinstance(data, dict) and data.get("overall"):
                return str(data["overall"])
        except (ValueError, TypeError):
            pass
    return "—"


@require_auth
async def students(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = get_user_by_telegram_id(update.effective_user.id)
    if not _is_teacher(caller):
        await update.effective_message.reply_text(
            "🚫 This command is only available to teachers."
        )
        return

    roster = list_students(include_pending=True)
    if not roster:
        await update.effective_message.reply_text("No students yet.")
        return

    active = [s for s in roster if s.status == "active"]
    pending = [s for s in roster if s.status == "pending"]

    lines = [f"👥 *Students* — {len(active)} active, {len(pending)} pending\n"]
    for s in roster:
        last = student_last_active(s.id)
        icon = _status_icon(last, s.status)
        name = s.name or f"id={s.telegram_id}"
        level = _cefr_level(s)
        mode = "🇩🇪" if s.learning_mode == "german" else "🇺🇸"
        if s.status == "pending":
            lines.append(f"{icon} {name} {mode} — awaiting approval")
        else:
            streak = practice_streak(s.id)
            streak_txt = f" · 🔥{streak}d" if streak else ""
            lines.append(
                f"{icon} {name} {mode} — {level} · {_time_ago(last)}{streak_txt}"
            )

    lines.append("\n/student <name> for details.")
    await update.effective_message.reply_text("\n".join(lines))


@require_auth
async def student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = get_user_by_telegram_id(update.effective_user.id)
    if not _is_teacher(caller):
        await update.effective_message.reply_text(
            "🚫 This command is only available to teachers."
        )
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /student <name>\nExample: /student Ana"
        )
        return

    query_name = " ".join(context.args).lower()
    roster = list_students(include_pending=True)
    matches = [
        s for s in roster
        if s.name and query_name in s.name.lower()
    ]
    if not matches:
        await update.effective_message.reply_text(f"No student found matching '{query_name}'.")
        return
    if len(matches) > 1:
        names = ", ".join(s.name or "?" for s in matches)
        await update.effective_message.reply_text(
            f"Multiple matches: {names}\nBe more specific."
        )
        return

    s = matches[0]
    last = student_last_active(s.id)
    verdict = latest_assessment(s.id)
    streak = practice_streak(s.id)
    cards = vocab_count(s.id)
    sessions = weekly_practice_count(s.id)
    mode = "English" if s.learning_mode == "english" else "German"

    lines = [f"👤 *{s.name}*\n"]
    lines.append(f"Mode: {mode} · Status: {s.status}")
    lines.append(f"Level: {_cefr_level(s)}")
    if verdict and isinstance(verdict, dict):
        skills = verdict.get("skills") or {}
        if skills:
            lines.append("Skills: " + " · ".join(f"{k} {v}" for k, v in skills.items()))
        gaps = verdict.get("gaps") or []
        if gaps:
            lines.append("Gaps: " + ", ".join(gaps[:4]))
    lines.append(f"Last active: {_time_ago(last)}")
    lines.append(f"Streak: {streak} day(s) 🔥")
    lines.append(f"Saved cards: {cards}")
    lines.append(f"Practice sessions (7d): {sessions}")
    if s.joined_at:
        lines.append(f"Joined: {s.joined_at.strftime('%Y-%m-%d')}")

    await update.effective_message.reply_text("\n".join(lines))


@require_auth
async def class_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = get_user_by_telegram_id(update.effective_user.id)
    if not _is_teacher(caller):
        await update.effective_message.reply_text(
            "🚫 This command is only available to teachers."
        )
        return

    roster = list_students(include_pending=False)
    if not roster:
        await update.effective_message.reply_text("No active students yet.")
        return

    now = datetime.utcnow()
    active_week = []
    inactive = []
    for s in roster:
        last = student_last_active(s.id)
        if last and (now - last).days < 7:
            active_week.append(s.name or f"id={s.telegram_id}")
        else:
            inactive.append((s.name or f"id={s.telegram_id}", _time_ago(last)))

    lines = [f"📊 *Class — weekly snapshot*\n"]
    lines.append(f"Active this week: {len(active_week)}/{len(roster)}")
    if active_week:
        lines.append("  " + ", ".join(active_week))
    if inactive:
        lines.append("\n⚠️ Inactive:")
        for name, when in inactive:
            lines.append(f"  • {name} — {when}")

    pending = [s for s in list_students(include_pending=True) if s.status == "pending"]
    if pending:
        lines.append(f"\n⏳ Pending approval: {len(pending)}")
        for s in pending:
            lines.append(f"  • {s.name or str(s.telegram_id)}")

    await update.effective_message.reply_text("\n".join(lines))


@require_auth
async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """T.9 — /budget: today's global credit usage, top consumers, reserve status."""
    caller = get_user_by_telegram_id(update.effective_user.id)
    if not _is_teacher(caller):
        await update.effective_message.reply_text(
            "🚫 This command is only available to teachers."
        )
        return

    used = global_credits_used()
    full_limit = config.GLOBAL_DAILY_CREDIT_LIMIT
    effective_limit = credit_mod._global_limit_for_now()
    pct = round(used / full_limit * 100) if full_limit else 0
    alert = " ⚠️ HIGH" if pct >= 70 else ""
    reserve_note = (
        f" (75% reserve — full budget after {config.RESERVE_HOUR_UTC}:00 UTC)"
        if effective_limit < full_limit else ""
    )

    lines = ["📊 *Budget — today*\n"]
    lines.append(
        f"Global: *{used} / {effective_limit}* credits ({pct}%){alert}{reserve_note}"
    )

    now = datetime.utcnow()
    hour = now.hour
    if used > 0 and hour > 0:
        rate = used / hour
        remaining = effective_limit - used
        if rate > 0 and remaining > 0:
            hours_left = remaining / rate
            lines.append(f"Projected: ~{hours_left:.1f}h until limit at current rate")

    lines.append(f"Per-student limit: {config.DAILY_CREDIT_LIMIT} credits/day (+streak bonus up to +5)")

    consumers = top_credit_consumers(5)
    if consumers:
        lines.append("\n🔝 *Top consumers today:*")
        for c in consumers:
            lines.append(f"  • {c['name']}: {c['credits']} credits")
    else:
        lines.append("\nNo credits spent yet today.")

    lines.append("\n/grant <name> <credits> to give a student extra credits.")
    await update.effective_message.reply_text("\n".join(lines))


@require_auth
async def grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """T.10 — /grant <name> <credits>: teacher gives a student extra daily credits."""
    caller = get_user_by_telegram_id(update.effective_user.id)
    if not _is_teacher(caller):
        await update.effective_message.reply_text(
            "🚫 This command is only available to teachers."
        )
        return

    if not context.args or len(context.args) < 2:
        await update.effective_message.reply_text(
            "Usage: /grant <student name> <credits>\nExample: /grant Ana 10"
        )
        return

    amount_str = context.args[-1]
    try:
        amount = int(amount_str)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            "Credits must be a positive whole number."
        )
        return

    name_query = " ".join(context.args[:-1]).lower()
    roster = list_students(include_pending=False)
    matches = [s for s in roster if s.name and name_query in s.name.lower()]
    if not matches:
        await update.effective_message.reply_text(
            f"No active student found matching '{name_query}'."
        )
        return
    if len(matches) > 1:
        names = ", ".join(s.name or "?" for s in matches)
        await update.effective_message.reply_text(
            f"Multiple matches: {names}\nBe more specific."
        )
        return

    student = matches[0]
    grant_credits(student.id, granted_by=update.effective_user.id, amount=amount)

    # Notify the student so they know.
    try:
        await context.bot.send_message(
            chat_id=student.telegram_id,
            text=f"🎁 Your teacher gave you {amount} extra credits today. Keep going!",
        )
    except Exception:
        logger.exception("Could not notify student %s of grant", student.telegram_id)

    await update.effective_message.reply_text(
        f"✅ Granted *{amount}* extra credits to *{student.name}* today."
    )


async def on_approve_student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Teacher taps [✅ German mode] or [✅ English mode]."""
    query = update.callback_query
    await query.answer()
    _, raw_id, mode = query.data.split(":")
    user_db_id = int(raw_id)

    teacher = update.effective_user
    if not config.TEACHER_TELEGRAM_ID or teacher.id != config.TEACHER_TELEGRAM_ID:
        await query.answer("Not authorized.", show_alert=True)
        return

    student_user = get_user_by_id(user_db_id)
    if student_user is None:
        await query.edit_message_text("⚠️ Student not found.")
        return

    if student_user.status == "active":
        await query.edit_message_text(
            f"ℹ️ {student_user.name or 'Student'} is already active."
        )
        return

    approve_student(user_db_id, approved_by=teacher.id, mode=mode)

    lang_label = "German" if mode == "german" else "English"
    student_name = student_user.name or str(student_user.telegram_id)

    from bot.handlers.start import WELCOME_GERMAN, WELCOME_ENGLISH
    welcome = (WELCOME_GERMAN if mode == "german" else WELCOME_ENGLISH) + (
        "\n\n✅ Your teacher approved you — welcome! "
        "Start with /test to find your level."
    )
    try:
        await context.bot.send_message(chat_id=student_user.telegram_id, text=welcome)
    except Exception:
        logger.exception("Could not notify student %s of approval", student_user.telegram_id)

    await query.edit_message_text(
        f"✅ Approved: *{student_name}* ({lang_label} mode)"
    )


async def on_decline_student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Teacher taps [❌ Decline]."""
    query = update.callback_query
    await query.answer()
    _, raw_id = query.data.split(":")
    user_db_id = int(raw_id)

    teacher = update.effective_user
    if not config.TEACHER_TELEGRAM_ID or teacher.id != config.TEACHER_TELEGRAM_ID:
        await query.answer("Not authorized.", show_alert=True)
        return

    student_user = get_user_by_id(user_db_id)
    if student_user is None:
        await query.edit_message_text("⚠️ Student not found.")
        return

    set_user_status(user_db_id, "removed")
    student_name = student_user.name or str(student_user.telegram_id)
    await query.edit_message_text(f"❌ Declined: *{student_name}*")
