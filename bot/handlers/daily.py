"""/daily — short mixed challenge (cloze + translate + reply).

Works in German mode and English mode. In English mode all UI strings are in
Spanish; the exercises themselves are in English.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot import credits as credit_mod
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


def _level(user) -> str:
    if user.cefr_estimate:
        try:
            data = json.loads(user.cefr_estimate)
            if isinstance(data, dict) and data.get("overall"):
                return str(data["overall"])
        except (ValueError, TypeError):
            pass
    return "A2-B1"


def _en(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.user_data.get("daily_mode") == "english"


@require_auth
async def daily_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return ConversationHandler.END

    mode = getattr(user, "learning_mode", "german") or "german"
    en = mode == "english"
    context.user_data["daily_mode"] = mode

    _credit_status = credit_mod.credits_check(user.id, credit_mod.COSTS["daily"])
    if _credit_status != "ok":
        _text, _kb = credit_mod.credit_error_response(en, _credit_status)
        await update.effective_message.reply_text(_text, reply_markup=_kb)
        return ConversationHandler.END

    gaps = []
    verdict = latest_assessment(user.id)
    if isinstance(verdict, dict):
        gaps = verdict.get("gaps") or []

    if en:
        await update.effective_message.reply_text(
            "🗓️ Reto diario — 3 ejercicios cortos. /stop para cancelar."
        )
    else:
        await update.effective_message.reply_text(
            "🗓️ Tägliche Challenge — 3 kurze Aufgaben. /stop zum Abbrechen.\n"
            "(Your daily challenge — 3 quick tasks.)"
        )

    level = _level(user)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache_key = f"daily:{mode}:{level}:{today}"

    # T.8 — one LLM call per level per day, shared across all students.
    cached_items = context.bot_data.get(cache_key)
    if cached_items:
        items = list(cached_items)  # copy so each student gets an independent queue
    else:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )
        prompt = "Gaps to target: " + (", ".join(gaps) if gaps else "(none provided)")
        system_prompt = (
            prompts.ENGLISH_DAILY_CHALLENGE if en else prompts.DAILY_CHALLENGE
        ).format(level=level)

        try:
            parsed, _ = await generate_json(Task.generate, prompt, system=system_prompt)
        except QuotaExceeded:
            await update.effective_message.reply_text(
                credit_mod.capacity_exhausted_text(en),
                reply_markup=credit_mod.capacity_exhausted_keyboard(en),
            )
            return ConversationHandler.END
        except LLMUnavailable:
            msg = (
                "No se pudo crear el reto. Inténtalo más tarde."
                if en else
                "Die tägliche Challenge ließ sich nicht erstellen. Versuch es später."
            )
            await update.effective_message.reply_text(msg)
            return ConversationHandler.END

        items = (parsed or {}).get("items") if isinstance(parsed, dict) else None
        items = [it for it in (items or []) if isinstance(it, dict) and it.get("prompt")]
        if not items:
            msg = (
                "No se pudo crear el reto. Inténtalo más tarde."
                if en else
                "Die tägliche Challenge ließ sich nicht erstellen. Versuch es später."
            )
            await update.effective_message.reply_text(msg)
            return ConversationHandler.END
        context.bot_data[cache_key] = items

    context.user_data["daily_queue"] = items
    context.user_data["daily_correct"] = 0
    context.user_data["daily_user_id"] = user.id
    record_practice(user.id)
    credit_mod.spend(user.id, task="daily")
    return await _ask(update, context)


async def _ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    queue: list[dict] = context.user_data.get("daily_queue", [])
    if not queue:
        return await _finish(update, context)

    item = queue[0]
    kind = item.get("type")
    en = _en(context)

    if en:
        if kind == "cloze":
            text = f"1️⃣ Fill in the blank:\n\n{item['prompt']}\n\n(Escribe la palabra que falta.)"
        elif kind == "translate":
            text = f"2️⃣ Traduce al inglés:\n\n{item['prompt']}"
        else:
            text = f"3️⃣ Responde en inglés:\n\n{item['prompt']}"
    else:
        if kind == "cloze":
            text = f"1️⃣ Lückentext:\n\n{item['prompt']}\n\n(Type the missing word.)"
        elif kind == "translate":
            text = f"2️⃣ Übersetze ins Deutsche:\n\n{item['prompt']}"
        else:
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
    en = _en(context)

    if kind == "cloze":
        correct = solution and solution.lower() in answer.lower()
        if correct:
            context.user_data["daily_correct"] += 1
        if en:
            mark = "✅ ¡Correcto!" if correct else f"❌ Respuesta: {solution}"
        else:
            mark = "✅ Richtig!" if correct else f"❌ Lösung: {solution}"
        await update.effective_message.reply_text(mark)
    elif kind == "translate":
        if en:
            await update.effective_message.reply_text(
                f"Tu respuesta: {answer}\nReferencia: {solution}"
            )
        else:
            await update.effective_message.reply_text(
                f"Deine Antwort: {answer}\nReferenz: {solution}"
            )
    else:
        if en:
            await update.effective_message.reply_text(f"Respuesta modelo: {solution}")
        else:
            await update.effective_message.reply_text(f"Beispielantwort: {solution}")

    queue.pop(0)
    return await _ask(update, context)


async def _finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    correct = context.user_data.get("daily_correct", 0)
    user_id = context.user_data.get("daily_user_id")
    streak = practice_streak(user_id) if user_id else 0
    en = _en(context)
    _clear(context)
    if en:
        await update.effective_message.reply_text(
            f"🎉 ¡Reto completado! Rellena-huecos: {correct} correctas. "
            f"Racha: {streak} días 🔥"
        )
    else:
        await update.effective_message.reply_text(
            f"🎉 Challenge fertig! Lückentext: {correct} richtig. "
            f"Streak: {streak} Tage 🔥\n(Daily done — see you tomorrow!)"
        )
    return ConversationHandler.END


@require_auth
async def daily_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    en = _en(context)
    _clear(context)
    msg = "Reto cancelado." if en else "Challenge abgebrochen. (Daily cancelled.)"
    await update.effective_message.reply_text(msg)
    return ConversationHandler.END


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("daily_queue", "daily_correct", "daily_user_id", "daily_mode"):
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
