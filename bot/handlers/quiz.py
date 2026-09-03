"""/quiz — rapid-fire MCQ drill targeting your weakest skills.

One LLM call generates N MCQ items focused on the skills where BKT mastery is
lowest. The user taps answer buttons for instant feedback; no typing required.
Each answer updates BKT so the profile improves in real time.
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

from bot.middleware import require_auth
from db.repo import (
    get_bkt_state,
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
QUIZ_SIZE = 7        # number of MCQ items per session
WEAK_SKILLS = 3      # how many lowest-mastery skills to target

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏 (All LLM quotas reached.)"
ERROR_MSG = "Quiz konnte nicht erstellt werden. Versuch es später. (Could not build quiz.)"


def _weakest_skills(bkt_state: dict[str, dict]) -> list[tuple[str, str | None]]:
    """Return up to WEAK_SKILLS skills ordered by mastery probability ascending.

    Returns list of (skill, level_or_None) so the prompt can target the right
    CEFR level per skill.
    """
    ordered = sorted(
        ((s, e.get("p", bkt_mod.P_L0), e.get("level")) for s, e in bkt_state.items()),
        key=lambda x: x[1],
    )
    return [(s, lvl) for s, _, lvl in ordered[:WEAK_SKILLS]]


def _target_level(weak: list[tuple[str, str | None]], fallback: str) -> str:
    """Pick the most common level among weak skills, or fall back to assessment."""
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


@require_auth
async def quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return ConversationHandler.END

    bkt_state = get_bkt_state(user.id)
    weak = _weakest_skills(bkt_state)
    fallback_level = _cefr_from_user(user)
    target_level = _target_level(weak, fallback_level)
    skills_focus = ", ".join(s for s, _ in weak) if weak else "grammar, vocab"

    # Show which skills we're drilling
    skill_labels = [s.capitalize() for s, _ in weak]
    intro = (
        f"⚡ Quiz — {QUIZ_SIZE} Fragen, fokussiert auf: {', '.join(skill_labels)}.\n"
        f"Tippe auf eine Zahl zum Antworten. /stop zum Abbrechen."
    )
    await update.effective_message.reply_text(intro)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        parsed, _ = await generate_json(
            Task.generate,
            f"Focus skills: {skills_focus}. Level: {target_level}.",
            system=prompts.QUIZ_ITEMS.format(
                level=target_level,
                skills_focus=skills_focus,
                n=QUIZ_SIZE,
            ),
        )
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        return ConversationHandler.END
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
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
        await update.effective_message.reply_text(ERROR_MSG)
        return ConversationHandler.END

    context.user_data["quiz_queue"] = items
    context.user_data["quiz_user_id"] = user.id
    context.user_data["quiz_correct"] = 0
    context.user_data["quiz_total"] = 0
    context.user_data["quiz_q_no"] = 0
    record_practice(user.id)
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
    await update.effective_message.reply_text(text, reply_markup=kb)
    return IN_QUIZ


@require_auth
async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, raw_q, raw_idx = query.data.split(":")
    q_no, choice = int(raw_q), int(raw_idx)

    if q_no != context.user_data.get("quiz_q_no"):
        return IN_QUIZ  # stale tap

    queue: list[dict] = context.user_data.get("quiz_queue", [])
    if not queue:
        return await _finish(update, context)

    item = queue[0]
    options = item.get("options") or []
    answer_index = item.get("answer_index")
    correct = choice == answer_index
    chosen = options[choice] if 0 <= choice < len(options) else "?"

    context.user_data["quiz_correct"] = context.user_data.get("quiz_correct", 0) + (1 if correct else 0)
    context.user_data["quiz_total"] = context.user_data.get("quiz_total", 0) + 1

    # Update BKT with the level from the item.
    user_id = context.user_data.get("quiz_user_id")
    skill = item.get("skill")
    level = item.get("level")
    if user_id and skill:
        update_bkt_state(user_id, skill, correct, level=level)

    mark = "✅ Richtig!" if correct else f"❌ Richtig wäre: {options[answer_index]}"
    await query.edit_message_text(_item_text(item) + f"\n\n{mark}")

    queue.pop(0)
    return await _ask(update, context)


async def _finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    correct = context.user_data.get("quiz_correct", 0)
    total = context.user_data.get("quiz_total", 0)
    _clear(context)
    pct = round(correct / total * 100) if total else 0
    await update.effective_message.reply_text(
        f"🎯 Quiz fertig! {correct}/{total} richtig ({pct}%). "
        "BKT-Mastery aktualisiert — check /profile.\n"
        "(Quiz done — mastery updated.)"
    )
    return ConversationHandler.END


@require_auth
async def quiz_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    done = context.user_data.get("quiz_total", 0)
    _clear(context)
    await update.effective_message.reply_text(
        f"Quiz abgebrochen. {done} Fragen beantwortet. (Stopped.)"
    )
    return ConversationHandler.END


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("quiz_queue", "quiz_user_id", "quiz_correct", "quiz_total", "quiz_q_no"):
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
