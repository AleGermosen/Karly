"""/daily — a short mixed daily challenge (cloze + translate + reply).

One LLM call generates three bite-sized items tailored to the user's level and
gaps; the user works through them; cloze is auto-checked locally and the open
items reveal a model answer for self-comparison. Completing it records a
practice session so it feeds the existing streak.
"""
from __future__ import annotations

import json
import logging

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.middleware import require_auth
from db.repo import (
    get_user_by_telegram_id,
    latest_assessment,
    practice_streak,
    record_practice,
)
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task
from llm.structured import generate_json

logger = logging.getLogger(__name__)

IN_DAILY = 1

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏 (All LLM quotas reached.)"
ERROR_MSG = "Die tägliche Challenge ließ sich nicht erstellen. Versuch es später."


def _level(user) -> str:
    if user.cefr_estimate:
        try:
            data = json.loads(user.cefr_estimate)
            if isinstance(data, dict) and data.get("overall"):
                return str(data["overall"])
        except (ValueError, TypeError):
            pass
    return "A2-B1"


@require_auth
async def daily_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return ConversationHandler.END
    if getattr(user, "learning_mode", "german") == "english":
        await update.effective_message.reply_text(
            "Este comando es solo para el modo alemán. "
            "Usa /language para cambiar de idioma."
        )
        return ConversationHandler.END

    gaps = []
    verdict = latest_assessment(user.id)
    if isinstance(verdict, dict):
        gaps = verdict.get("gaps") or []

    await update.effective_message.reply_text(
        "🗓️ Tägliche Challenge — 3 kurze Aufgaben. /stop zum Abbrechen.\n"
        "(Your daily challenge — 3 quick tasks.)"
    )
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )
    prompt = "Gaps to target: " + (", ".join(gaps) if gaps else "(none provided)")
    try:
        parsed, _ = await generate_json(
            Task.generate,
            prompt,
            system=prompts.DAILY_CHALLENGE.format(level=_level(user)),
        )
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        return ConversationHandler.END
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
        return ConversationHandler.END

    items = parsed.get("items") if isinstance(parsed, dict) else None
    items = [it for it in (items or []) if isinstance(it, dict) and it.get("prompt")]
    if not items:
        await update.effective_message.reply_text(ERROR_MSG)
        return ConversationHandler.END

    context.user_data["daily_queue"] = items
    context.user_data["daily_correct"] = 0
    context.user_data["daily_user_id"] = user.id
    record_practice(user.id)  # counts toward the streak
    return await _ask(update, context)


async def _ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    queue: list[dict] = context.user_data.get("daily_queue", [])
    if not queue:
        return await _finish(update, context)

    item = queue[0]
    kind = item.get("type")
    if kind == "cloze":
        text = f"1️⃣ Lückentext:\n\n{item['prompt']}\n\n(Type the missing word.)"
    elif kind == "translate":
        text = f"2️⃣ Übersetze ins Deutsche:\n\n{item['prompt']}"
    else:  # reply / anything else
        text = f"3️⃣ Antworte auf Deutsch:\n\n{item['prompt']}"
    await update.effective_message.reply_text(text)
    return IN_DAILY


@require_auth
async def daily_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    queue: list[dict] = context.user_data.get("daily_queue", [])
    if not queue:
        return await _finish(update, context)

    item = queue[0]
    answer = (update.effective_message.text or "").strip()
    kind = item.get("type")
    solution = (item.get("answer") or "").strip()

    if kind == "cloze":
        correct = solution and solution.lower() in answer.lower()
        if correct:
            context.user_data["daily_correct"] += 1
        mark = "✅ Richtig!" if correct else f"❌ Lösung: {solution}"
        await update.effective_message.reply_text(mark)
    elif kind == "translate":
        await update.effective_message.reply_text(
            f"Deine Antwort: {answer}\nReferenz: {solution}"
        )
    else:  # reply — reveal a model answer for self-comparison
        await update.effective_message.reply_text(f"Beispielantwort: {solution}")

    queue.pop(0)
    return await _ask(update, context)


async def _finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    correct = context.user_data.get("daily_correct", 0)
    user_id = context.user_data.get("daily_user_id")
    streak = practice_streak(user_id) if user_id else 0
    _clear(context)
    await update.effective_message.reply_text(
        f"🎉 Challenge fertig! Lückentext: {correct} richtig. "
        f"Streak: {streak} Tage 🔥\n(Daily done — see you tomorrow!)"
    )
    return ConversationHandler.END


@require_auth
async def daily_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear(context)
    await update.effective_message.reply_text(
        "Challenge abgebrochen. (Daily cancelled.)"
    )
    return ConversationHandler.END


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("daily_queue", "daily_correct", "daily_user_id"):
        context.user_data.pop(k, None)


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("daily", daily_start)],
        states={
            IN_DAILY: [
                CommandHandler("stop", daily_stop),
                CommandHandler("cancel", daily_stop),
                MessageHandler(filters.TEXT & ~filters.COMMAND, daily_answer),
            ]
        },
        fallbacks=[CommandHandler("stop", daily_stop)],
        name="daily",
        per_message=False,
    )
