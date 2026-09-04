"""/drill — focused grammar topic drill (10 exercises, batch-generated).

Exercises are generated upfront for the assigned class topic (or the student's
weakest skill if no topic is set). Mix of MCQ (inline buttons) and fill-in-the-
blank (typed answer, auto-graded). Free — no credits charged.
"""
from __future__ import annotations

import json
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot import credits as credit_mod
from bot.middleware import require_auth
from db.repo import get_bkt_state, get_student_topic, get_user_by_telegram_id, record_practice
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task
from llm.structured import generate_json
from srs import bkt as bkt_mod

logger = logging.getLogger(__name__)

IN_DRILL = 1
DRILL_SIZE = 10


def _cefr(user) -> str:
    if user.cefr_estimate:
        try:
            data = json.loads(user.cefr_estimate)
            if isinstance(data, dict) and data.get("overall"):
                return str(data["overall"])
        except (ValueError, TypeError):
            pass
    return "A2"


def _weakest_skill(user) -> str:
    state = get_bkt_state(user.id)
    if not state:
        return "grammar"
    return min(state.items(), key=lambda kv: kv[1].get("p", bkt_mod.P_L0))[0]


def _en(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.user_data.get("drill_mode") == "english"


def _drill_keyboard(q_no: int, n_opts: int) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(str(i + 1), callback_data=f"drill:{q_no}:{i}")
        for i in range(n_opts)
    ]
    return InlineKeyboardMarkup([row])


def _item_text(item: dict, q_no: int, total: int) -> str:
    prefix = f"*{q_no}/{total}* — "
    parts = [prefix + item.get("prompt", "")]
    if item.get("type") == "mcq":
        parts.append("")
        for i, opt in enumerate(item.get("options") or []):
            parts.append(f"{i + 1}. {opt}")
    return "\n".join(parts)


@require_auth
async def drill_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return ConversationHandler.END

    mode = getattr(user, "learning_mode", "german") or "german"
    en = mode == "english"
    context.user_data["drill_mode"] = mode

    # Determine topic: class assignment > weakest skill fallback.
    if context.args:
        topic = " ".join(context.args)
    else:
        topic = get_student_topic(user.id) or _weakest_skill(user)

    level = _cefr(user)
    context.user_data["drill_topic"] = topic

    if en:
        await update.effective_message.reply_text(
            f"🎯 *Drill: {topic}* — {DRILL_SIZE} ejercicios. /stop para cancelar."
        )
    else:
        await update.effective_message.reply_text(
            f"🎯 *Drill: {topic}* — {DRILL_SIZE} Übungen. /stop zum Abbrechen."
        )

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    prompt_template = prompts.ENGLISH_DRILL_ITEMS if en else prompts.DRILL_ITEMS
    system = prompt_template.format(topic=topic, level=level, n=DRILL_SIZE)

    try:
        parsed, _ = await generate_json(Task.generate, f"Topic: {topic}. Level: {level}.", system=system)
    except QuotaExceeded:
        await update.effective_message.reply_text(
            credit_mod.capacity_exhausted_text(en),
            reply_markup=credit_mod.capacity_exhausted_keyboard(en),
        )
        return ConversationHandler.END
    except LLMUnavailable:
        msg = "No se pudo crear el drill. Inténtalo más tarde." if en else "Drill konnte nicht erstellt werden. Versuch es später."
        await update.effective_message.reply_text(msg)
        return ConversationHandler.END

    raw_items = parsed.get("items") if isinstance(parsed, dict) else None
    items = [
        it for it in (raw_items or [])
        if isinstance(it, dict) and it.get("prompt") and it.get("type") in ("mcq", "fill")
    ]
    if not items:
        msg = "No se pudo crear el drill. Inténtalo más tarde." if en else "Drill konnte nicht erstellt werden. Versuch es später."
        await update.effective_message.reply_text(msg)
        return ConversationHandler.END

    context.user_data["drill_queue"] = items
    context.user_data["drill_total"] = len(items)
    context.user_data["drill_q_no"] = 0
    context.user_data["drill_correct"] = 0
    context.user_data["drill_user_id"] = user.id
    record_practice(user.id)
    return await _ask(update, context)


async def _ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    queue: list[dict] = context.user_data.get("drill_queue", [])
    total: int = context.user_data.get("drill_total", DRILL_SIZE)
    if not queue:
        return await _finish(update, context)

    item = queue[0]
    q_no = context.user_data.get("drill_q_no", 0) + 1
    context.user_data["drill_q_no"] = q_no
    context.user_data["drill_current"] = item

    text = _item_text(item, q_no, total)
    en = _en(context)

    if item.get("type") == "mcq":
        kb = _drill_keyboard(q_no, len(item.get("options") or []))
        await update.effective_message.reply_text(text, reply_markup=kb)
    else:
        label = "✏️" if en else "✏️"
        await update.effective_message.reply_text(f"{label} {text}")

    return IN_DRILL


@require_auth
async def drill_mcq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, raw_q, raw_idx = query.data.split(":")
    q_no, choice = int(raw_q), int(raw_idx)
    en = _en(context)

    if q_no != context.user_data.get("drill_q_no"):
        return IN_DRILL

    item = context.user_data.get("drill_current", {})
    options = item.get("options") or []
    answer_index = item.get("answer_index")
    correct = (choice == answer_index)
    if correct:
        context.user_data["drill_correct"] = context.user_data.get("drill_correct", 0) + 1

    explanation = item.get("explanation", "")
    chosen_text = options[choice] if 0 <= choice < len(options) else "?"
    correct_text = options[answer_index] if isinstance(answer_index, int) and 0 <= answer_index < len(options) else "?"

    total = context.user_data.get("drill_total", DRILL_SIZE)
    base = _item_text(item, q_no, total)
    if correct:
        feedback = f"\n\n✅ {'¡Correcto!' if en else 'Richtig!'}"
    else:
        feedback = f"\n\n❌ {correct_text}\n_{explanation}_"

    await query.edit_message_text(base + feedback)
    context.user_data["drill_queue"].pop(0)
    return await _ask(update, context)


@require_auth
async def drill_fill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = (update.effective_message.text or "").strip()
    item = context.user_data.get("drill_current", {})
    en = _en(context)

    if item.get("type") != "fill":
        return IN_DRILL

    expected = (item.get("answer") or "").strip()
    correct = bool(expected) and expected.lower() in answer.lower()
    if correct:
        context.user_data["drill_correct"] = context.user_data.get("drill_correct", 0) + 1

    explanation = item.get("explanation", "")
    if correct:
        mark = f"✅ {'¡Correcto!' if en else 'Richtig!'}"
    else:
        mark = f"❌ *{expected}*\n_{explanation}_"

    await update.effective_message.reply_text(mark)
    context.user_data["drill_queue"].pop(0)
    return await _ask(update, context)


async def _finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    correct = context.user_data.get("drill_correct", 0)
    total = context.user_data.get("drill_total", DRILL_SIZE)
    topic = context.user_data.get("drill_topic", "")
    en = _en(context)
    pct = round(correct / total * 100) if total else 0
    _clear(context)

    if en:
        await update.effective_message.reply_text(
            f"🎯 *Drill completo — {topic}*\n\n"
            f"{correct}/{total} correctas ({pct}%)\n\n"
            + ("¡Excelente dominio!" if pct >= 80 else "Sigue practicando — /drill para repetir.")
        )
    else:
        await update.effective_message.reply_text(
            f"🎯 *Drill fertig — {topic}*\n\n"
            f"{correct}/{total} richtig ({pct}%)\n\n"
            + ("Sehr gut! 💪" if pct >= 80 else "Weiter üben — /drill zum Wiederholen.")
        )
    return ConversationHandler.END


@require_auth
async def drill_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    done = context.user_data.get("drill_q_no", 0)
    en = _en(context)
    _clear(context)
    msg = f"Drill cancelado. {done} preguntas respondidas." if en else f"Drill abgebrochen. {done} Fragen beantwortet."
    await update.effective_message.reply_text(msg)
    return ConversationHandler.END


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("drill_queue", "drill_total", "drill_q_no", "drill_correct",
              "drill_topic", "drill_user_id", "drill_mode", "drill_current"):
        context.user_data.pop(k, None)


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("drill", drill_start)],
        states={
            IN_DRILL: [
                CommandHandler("stop", drill_stop),
                CommandHandler("cancel", drill_stop),
                CallbackQueryHandler(drill_mcq, pattern=r"^drill:\d+:\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, drill_fill),
            ]
        },
        fallbacks=[CommandHandler("stop", drill_stop)],
        name="drill",
        per_message=False,
    )
