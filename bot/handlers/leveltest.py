"""H5 — /leveltest and /browse.

/leveltest  — 15 questions sampled across all units of the student's current
              level. Pass ≥ 80% → CEFR level marked cleared, student offered
              the next level. Retakeable any time.

/browse     — inline unit picker: shows all units at or below the student's
              level; tapping one opens the lesson card via course:start:.
"""
from __future__ import annotations

import json
import random

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
from bot.handlers.course import (
    _PASS_MARK,
    _course_state,
    _grade_locally,
    _grade_produce,
    _level_from_user,
    _progress_bar,
    _record_and_advance,
    _ST_IDLE,
    _ST_RUNNING,
)
from curriculum import loader
from curriculum.loader import Unit
from db import repo

_LEVELTEST_N = 15   # questions per level test
_CEFR_ORDER = ["A1", "A2", "B1", "B1+", "B2", "C1"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_cefr(level: str) -> str | None:
    try:
        idx = _CEFR_ORDER.index(level.upper())
        return _CEFR_ORDER[idx + 1] if idx + 1 < len(_CEFR_ORDER) else None
    except ValueError:
        return None


def _sample_leveltest_items(units: list[Unit], n: int = _LEVELTEST_N) -> list[dict]:
    """Pick n questions distributed evenly across units."""
    all_questions: list[dict] = []
    for unit in units:
        all_questions.extend(unit.questions)
    if not all_questions:
        return []
    return random.sample(all_questions, min(n, len(all_questions)))


def _update_cefr(user, level: str) -> None:
    """Mark the given CEFR level as cleared in the user's cefr_estimate."""
    try:
        cefr = json.loads(user.cefr_estimate or "{}")
    except Exception:
        cefr = {}
    cefr["overall"] = level
    cefr["grammar"] = level
    from db.session import get_session
    from db.models import User as UserModel
    with get_session() as session:
        row = session.query(UserModel).filter(UserModel.id == user.id).one_or_none()
        if row:
            row.cefr_estimate = json.dumps(cefr, ensure_ascii=False)


# ---------------------------------------------------------------------------
# /leveltest
# ---------------------------------------------------------------------------

@require_auth
async def leveltest_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    lang, level = _level_from_user(user)
    units = loader.list_units(lang, level)

    if not units:
        await update.message.reply_text(
            "No course content is available for your level yet. "
            "Try /course to see what's ready."
        )
        return _ST_IDLE

    items = _sample_leveltest_items(units)
    if not items:
        await update.message.reply_text(
            "The question bank for this level isn't complete yet. "
            "Come back after doing /course first!"
        )
        return _ST_IDLE

    state = _course_state(context)
    state.update({
        "unit_id": f"_leveltest_{level}",
        "mode": "leveltest",
        "level": level,
        "lang": lang,
        "items": items,
        "idx": 0,
        "correct": 0,
        "total": len(items),
        "answers": [],
    })

    await update.message.reply_text(
        f"📋 *Level test — English {level}*\n\n"
        f"{len(items)} questions across all {level} units.\n"
        f"Pass mark: {round(_PASS_MARK * 100)}%\n\n"
        "Type /stopcourse to exit at any time.",
        parse_mode="Markdown",
    )
    return await _send_lt_question(update, context, user, en)


async def _send_lt_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    state = _course_state(context)
    idx = state["idx"]
    items = state["items"]

    if idx >= len(items):
        return await _finish_leveltest(update, context, user, en)

    item = items[idx]
    qtype = item.get("type")
    prompt = item.get("prompt", "")
    unit = loader.get_unit(item.get("unit", ""))
    unit_label = f"_{unit.title_target}_" if unit else ""
    q_num = f"*Q{idx + 1}/{len(items)}*  {unit_label}\n\n"

    if qtype == "mcq":
        opts = item.get("options", [])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"{i + 1}. {opt}", callback_data=f"lt:ans:{i}")
            for i in range(len(opts))
        ]])
        await update.effective_message.reply_text(
            q_num + prompt,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return _ST_RUNNING

    hint = {
        "cloze": "_Fill in the blank(s)._",
        "transform": "_Rewrite the sentence._",
        "produce": "_Write your own sentence(s)._",
    }.get(qtype, "")
    await update.effective_message.reply_text(
        q_num + prompt + (f"\n\n{hint}" if hint else ""),
        parse_mode="Markdown",
    )
    return _ST_RUNNING


async def on_lt_mcq_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    query = update.callback_query
    await query.answer()
    choice = int(query.data.split(":")[2])
    state = _course_state(context)
    idx = state["idx"]
    item = state["items"][idx]

    correct_idx = item.get("answer", 0)
    correct = choice == correct_idx
    opts = item.get("options", [])
    why = item.get("why", "")

    if correct:
        feedback = f"✅ *Correct!* {opts[correct_idx]}\n_{why}_"
    else:
        feedback = (
            f"❌ You chose: {opts[choice]}\n"
            f"✔️ *{opts[correct_idx]}*\n_{why}_"
        )

    await query.edit_message_reply_markup(None)
    await update.effective_message.reply_text(feedback, parse_mode="Markdown")
    _record_and_advance(context, user.id, item, correct, str(choice))
    return await _send_lt_question(update, context, user, en)


async def on_lt_text_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    state = _course_state(context)
    if state.get("mode") != "leveltest":
        return _ST_IDLE

    idx = state["idx"]
    item = state["items"][idx]
    qtype = item.get("type")
    user_answer = (update.message.text or "").strip()

    if qtype == "produce":
        return await _grade_produce(update, context, user, en, item, user_answer)

    correct, feedback = _grade_locally(item, user_answer)
    await update.message.reply_text(feedback, parse_mode="Markdown")
    _record_and_advance(context, user.id, item, correct, user_answer)
    return await _send_lt_question(update, context, user, en)


async def _finish_leveltest(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    state = _course_state(context)
    correct = state.get("correct", 0)
    total = state.get("total", 1)
    level = state.get("level", "A1")
    lang = state.get("lang", "en")
    score = correct / max(total, 1)
    passed = score >= _PASS_MARK

    bar = _progress_bar(correct, total)
    lines = [
        f"{'🎉 Level cleared!' if passed else '🔄 Not passed — keep practising!'}",
        f"`{bar}` {correct}/{total} ({round(score * 100)}%)",
    ]

    keyboard_rows = []
    if passed:
        _update_cefr(user, level)
        next_level = _next_cefr(level)
        if next_level and loader.list_units(lang, next_level):
            lines.append(f"\n✅ English {level} complete. Next level: *{next_level}*")
            keyboard_rows.append([InlineKeyboardButton(
                f"▶️ Start {next_level} course",
                callback_data=f"course:overview:{lang}:{next_level}",
            )])
        else:
            lines.append(f"\n🏆 You've cleared English {level}!")
    else:
        lines.append(f"\nPass mark is {round(_PASS_MARK * 100)}%. Work through /course units then try again.")
        keyboard_rows.append([InlineKeyboardButton(
            "📚 Back to course", callback_data="course:overview"
        )])

    context.user_data.pop("_course", None)
    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None,
    )
    return _ST_IDLE


# ---------------------------------------------------------------------------
# /browse
# ---------------------------------------------------------------------------

@require_auth
async def browse_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> None:
    lang, level = _level_from_user(user)
    progress = repo.get_all_unit_progress(user.id)

    lines = [f"📖 *Browse units — English {level}*\n"]
    keyboard_rows: list[list[InlineKeyboardButton]] = []

    units = loader.list_units(lang, level)
    if not units:
        await update.message.reply_text(
            "No course content yet for your level. Check back soon!"
        )
        return

    for unit in units:
        p = progress.get(unit.id)
        if p and p.passed:
            icon = "✅"
        elif p and p.attempts:
            icon = "🔄"
        else:
            icon = "⬜"
        lines.append(f"{icon} {unit.order}. {unit.title_target}")
        keyboard_rows.append([InlineKeyboardButton(
            f"{icon} {unit.order}. {unit.title_target}",
            callback_data=f"course:start:{unit.id}",
        )])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard_rows),
    )


# ---------------------------------------------------------------------------
# Build handlers
# ---------------------------------------------------------------------------

def build_handlers() -> list:
    lt_conv = ConversationHandler(
        entry_points=[CommandHandler("leveltest", leveltest_cmd)],
        states={
            _ST_IDLE: [
                CallbackQueryHandler(
                    require_auth(on_lt_mcq_answer), pattern=r"^lt:ans:\d+"
                ),
            ],
            _ST_RUNNING: [
                CallbackQueryHandler(
                    require_auth(on_lt_mcq_answer), pattern=r"^lt:ans:\d+"
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    require_auth(on_lt_text_answer),
                ),
                CommandHandler("stopcourse", require_auth(_stop_leveltest)),
            ],
        },
        fallbacks=[CommandHandler("stopcourse", require_auth(_stop_leveltest))],
        per_user=True,
        per_chat=True,
    )
    browse_handler = CommandHandler("browse", browse_cmd)
    return [lt_conv, browse_handler]


@require_auth
async def _stop_leveltest(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    context.user_data.pop("_course", None)
    await update.message.reply_text("Level test stopped. Use /leveltest to restart.")
    return ConversationHandler.END
