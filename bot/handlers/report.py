"""/weekly — weekly German learning progress report.

Pulls practice sessions, card-review accuracy, and inline corrections from the
past 7 days, compares accuracy to the prior week, and asks an LLM to synthesise
a short personalised summary with one actionable tip.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.middleware import require_auth
from db.repo import (
    get_bkt_state,
    get_user_by_telegram_id,
    practice_streak,
    weekly_corrections,
    weekly_practice_count,
    weekly_review_stats,
)
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task, route
from srs import bkt as bkt_mod

logger = logging.getLogger(__name__)


def _accuracy_str(correct: int, total: int) -> str:
    if total == 0:
        return "—"
    return f"{round(correct / total * 100)}% ({correct}/{total})"


def _delta_str(this_c: int, this_t: int, prev_c: int, prev_t: int) -> str:
    if this_t == 0 or prev_t == 0:
        return ""
    this_pct = this_c / this_t
    prev_pct = prev_c / prev_t
    diff = round((this_pct - prev_pct) * 100)
    if diff > 0:
        return f" (+{diff}pp vs last week ⬆️)"
    if diff < 0:
        return f" ({diff}pp vs last week ⬇️)"
    return " (same as last week)"


def _bkt_block(bkt_state: dict) -> str:
    lines = []
    for skill, entry in bkt_state.items():
        p = entry.get("p", 0.0)
        lvl = entry.get("level")
        label = f"{skill.capitalize()} ({lvl})" if lvl else skill.capitalize()
        lines.append(f"  {label}: {round(p * 100)}%")
    return "\n".join(lines) if lines else "(no mastery data yet)"


@require_auth
async def weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    sessions = weekly_practice_count(user.id)
    streak = practice_streak(user.id)
    stats = weekly_review_stats(user.id)
    corrections = weekly_corrections(user.id, limit=15)
    bkt_state = get_bkt_state(user.id)

    this_t, this_c = stats["this_total"], stats["this_correct"]
    prev_t, prev_c = stats["prev_total"], stats["prev_correct"]

    accuracy_line = _accuracy_str(this_c, this_t) + _delta_str(this_c, this_t, prev_c, prev_t)

    # Build the raw stats block shown to the user and sent to the LLM.
    stats_block = (
        f"Practice sessions this week: {sessions}\n"
        f"Cards reviewed: {this_t} (accuracy: {accuracy_line})\n"
        f"Current streak: {streak} days"
    )
    corrections_block = (
        "\n".join(corrections) if corrections else "(none logged this week)"
    )
    bkt_block = _bkt_block(bkt_state)

    # Always show the hard stats first so the user sees them immediately.
    stats_msg = (
        "📊 *Wochenbericht*\n\n"
        f"Übungssessions: *{sessions}*\n"
        f"Karten geübt: *{this_t}* — Genauigkeit: *{accuracy_line}*\n"
        f"Streak: *{streak}* Tage 🔥\n\n"
        "🧠 *Skill mastery:*\n"
        + "\n".join(
            f"  {s.capitalize()}" + (f" ({e.get('level')})" if e.get("level") else "")
            + f": {bkt_mod.mastery_bar(e.get('p', 0))}"
            for s, e in bkt_state.items()
            if e.get("p", 0) > bkt_mod.P_L0 + 0.001
        )
    )
    await update.effective_message.reply_text(stats_msg)

    # LLM synthesis — best-effort; skip gracefully on quota.
    if not corrections and this_t == 0:
        await update.effective_message.reply_text(
            "Noch keine Daten diese Woche. Üb ein bisschen und schau morgen nochmal! "
            "(No data yet this week — practice a bit and check back.)"
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        summary = await route(
            Task.generate,
            "Synthesise the weekly report.",
            system=prompts.WEEKLY_REPORT_SYNTHESIS.format(
                stats_block=stats_block,
                corrections_block=corrections_block,
                bkt_block=bkt_block,
            ),
        )
        await update.effective_message.reply_text(f"💬 {summary.strip()}")
    except (QuotaExceeded, LLMUnavailable):
        pass  # stats already sent; synthesis is a nice-to-have
