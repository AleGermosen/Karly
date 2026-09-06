"""/quiz — rapid-fire MCQ drill targeting weakest skills.

Works in German mode and English mode. In English mode all UI strings are in
Spanish; the quiz items themselves are in English.
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
from bot.utils import safe_edit, safe_reply
from db.repo import (
    get_bkt_state,
    get_student_topic,
    get_user_by_telegram_id,
    latest_assessment,
    record_practice,
    update_bkt_state,
)
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task
from llm.structured import generate_json
from srs import bkt as bkt_mod

logger = logging.getLogger(__name__)

IN_QUIZ = 1
QUIZ_SIZE = 7
WEAK_SKILLS = 3


def _weakest_skills(bkt_state: dict[str, dict]) -> list[tuple[str, str | None]]:
    ordered = sorted(
        ((s, e.get("p", bkt_mod.P_L0), e.get("level")) for s, e in bkt_state.items()),
        key=lambda x: x[1],
    )
    return [(s, lvl) for s, _, lvl in ordered[:WEAK_SKILLS]]


def _target_level(weak: list[tuple[str, str | None]], fallback: str) -> str:
    levels = [lvl for _, lvl in weak if lvl]
    if not levels:
        return fallback
    return max(set(levels), key=levels.count)


def _quiz_keyboard(q_no: int, n_opts: int) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(str(i + 1), callback_data=f"quiz:{q_no}:{i}")
        for i in range(n_opts)
    ]
    return InlineKeyboardMarkup([row])


def _item_text(item: dict) -> str:
    parts = [item.get("prompt", "")]
    opts = item.get("options") or []
    if opts:
        parts.append("")
        for i, o in enumerate(opts):
            parts.append(f"{i + 1}. {o}")
    return "\n".join(parts)


def _cefr_from_user(user) -> str:
    if user.cefr_estimate:
        try:
            data = json.loads(user.cefr_estimate)
            if isinstance(data, dict) and data.get("overall"):
                return str(data["overall"])
        except (ValueError, TypeError):
            pass
    return "A2"


def _en(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.user_data.get("quiz_mode") == "english"


@require_auth
async def quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return ConversationHandler.END

    mode = getattr(user, "learning_mode", "german") or "german"
    en = mode == "english"
    context.user_data["quiz_mode"] = mode

    _credit_status = credit_mod.credits_check(user.id, credit_mod.COSTS["quiz"])
    if _credit_status != "ok":
        _text, _kb = credit_mod.credit_error_response(en, _credit_status)
        await update.effective_message.reply_text(_text, reply_markup=_kb)
        return ConversationHandler.END

    bkt_state = get_bkt_state(user.id)
    weak = _weakest_skills(bkt_state)
    fallback_level = _cefr_from_user(user)
    target_level = _target_level(weak, fallback_level)
    skills_focus = ", ".join(s for s, _ in weak) if weak else "grammar, vocab"
    skill_labels = [s.capitalize() for s, _ in weak]

    # If a class topic is assigned, bias the quiz toward it.
    class_topic = get_student_topic(user.id)
    topic_note = f" Topic focus: {class_topic}." if class_topic else ""

    if en:
        topic_line = f" Topic: *{class_topic}*." if class_topic else ""
        intro = (
            f"⚡ Quiz — {QUIZ_SIZE} questions, focused on: {', '.join(skill_labels)}.{topic_line}\n"
            f"Tap a number to answer. /stop to cancel."
        )
    else:
        topic_line = f" Thema: *{class_topic}*." if class_topic else ""
        intro = (
            f"⚡ Quiz — {QUIZ_SIZE} Fragen, fokussiert auf: {', '.join(skill_labels)}.{topic_line}\n"
            f"Tippe auf eine Zahl zum Antworten. /stop zum Abbrechen."
        )
    await update.effective_message.reply_text(intro)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    system_prompt = (prompts.ENGLISH_QUIZ_ITEMS if en else prompts.QUIZ_ITEMS).format(
        level=target_level,
        skills_focus=skills_focus,
        n=QUIZ_SIZE,
    )
    try:
        parsed, _ = await generate_json(
            Task.generate,
            f"Focus skills: {skills_focus}. Level: {target_level}.{topic_note}",
            system=system_prompt,
        )
    except QuotaExceeded:
        await update.effective_message.reply_text(
            credit_mod.capacity_exhausted_text(en),
            reply_markup=credit_mod.capacity_exhausted_keyboard(en),
        )
        return ConversationHandler.END
    except LLMUnavailable:
        msg = "Couldn't create the quiz. Try again later." if en else "Quiz konnte nicht erstellt werden. Versuch es später."
        await update.effective_message.reply_text(msg)
        return ConversationHandler.END

    items = parsed.get("items") if isinstance(parsed, dict) else None
    items = [
        it for it in (items or [])
        if isinstance(it, dict)
        and it.get("prompt")
        and it.get("options")
        and isinstance(it.get("answer_index"), int)
    ]
    if not items:
        msg = "Couldn't create the quiz. Try again later." if en else "Quiz konnte nicht erstellt werden. Versuch es später."
        await update.effective_message.reply_text(msg)
        return ConversationHandler.END

    context.user_data["quiz_queue"] = items
    context.user_data["quiz_user_id"] = user.id
    context.user_data["quiz_correct"] = 0
    context.user_data["quiz_total"] = 0
    context.user_data["quiz_q_no"] = 0
    record_practice(user.id)
    credit_mod.spend(user.id, task="quiz")
    return await _ask(update, context)


async def _ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    queue: list[dict] = context.user_data.get("quiz_queue", [])
    if not queue:
        return await _finish(update, context)

    item = queue[0]
    q_no = context.user_data.get("quiz_q_no", 0) + 1
    context.user_data["quiz_q_no"] = q_no

    n = len(item.get("options") or [])
    text = _item_text(item)
    kb = _quiz_keyboard(q_no, n)
    await safe_reply(update.effective_message, text, reply_markup=kb)
    return IN_QUIZ


@require_auth
async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, raw_q, raw_idx = query.data.split(":")
    q_no, choice = int(raw_q), int(raw_idx)
    en = _en(context)

    if q_no != context.user_data.get("quiz_q_no"):
        return IN_QUIZ

    queue: list[dict] = context.user_data.get("quiz_queue", [])
    if not queue:
        return await _finish(update, context)

    item = queue[0]
    options = item.get("options") or []
    answer_index = item.get("answer_index")
    correct = choice == answer_index

    context.user_data["quiz_correct"] = context.user_data.get("quiz_correct", 0) + (1 if correct else 0)
    context.user_data["quiz_total"] = context.user_data.get("quiz_total", 0) + 1

    user_id = context.user_data.get("quiz_user_id")
    skill = item.get("skill")
    level = item.get("level")
    if user_id and skill:
        update_bkt_state(user_id, skill, correct, level=level)

    if en:
        mark = "✅ Correct!" if correct else f"❌ Correct answer: {options[answer_index]}"
    else:
        mark = "✅ Richtig!" if correct else f"❌ Richtig wäre: {options[answer_index]}"
    await safe_edit(query, _item_text(item) + f"\n\n{mark}")

    queue.pop(0)
    return await _ask(update, context)


async def _finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    correct = context.user_data.get("quiz_correct", 0)
    total = context.user_data.get("quiz_total", 0)
    en = _en(context)
    _clear(context)
    pct = round(correct / total * 100) if total else 0
    if en:
        await update.effective_message.reply_text(
            f"🎯 Quiz done! {correct}/{total} correct ({pct}%). "
            "BKT mastery updated — check /profile."
        )
    else:
        await update.effective_message.reply_text(
            f"🎯 Quiz fertig! {correct}/{total} richtig ({pct}%). "
            "BKT-Mastery aktualisiert — check /profile.\n"
            "(Quiz done — mastery updated.)"
        )
    return ConversationHandler.END


@require_auth
async def quiz_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    done = context.user_data.get("quiz_total", 0)
    en = _en(context)
    _clear(context)
    if en:
        await update.effective_message.reply_text(f"Quiz cancelled. {done} questions answered.")
    else:
        await update.effective_message.reply_text(f"Quiz abgebrochen. {done} Fragen beantwortet. (Stopped.)")
    return ConversationHandler.END


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("quiz_queue", "quiz_user_id", "quiz_correct", "quiz_total", "quiz_q_no", "quiz_mode"):
        context.user_data.pop(k, None)


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("quiz", quiz_start)],
        states={
            IN_QUIZ: [
                CommandHandler("stop", quiz_stop),
                CommandHandler("cancel", quiz_stop),
                CallbackQueryHandler(quiz_answer, pattern=r"^quiz:\d+:\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: IN_QUIZ),
            ]
        },
        fallbacks=[CommandHandler("stop", quiz_stop)],
        name="quiz",
        per_message=False,
    )
