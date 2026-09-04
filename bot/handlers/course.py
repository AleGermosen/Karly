"""H3 — /course command: lesson card, exercise runner, pass/fail.

H4 — missed questions become flashcards automatically after each unit.

Flow:
  /course                 → show progress overview + "Continue" button
  /course <unit_id>       → start that specific unit
  callback course:start:X → show lesson card for unit X
  callback course:go:X    → begin the exercise run for unit X
  callback course:ans:X:N → register answer N for current MCQ question
  Freetext while running  → answer cloze / transform / produce question

State stored in context.user_data under key "_course".
"""
from __future__ import annotations

import random
import re
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from bot.middleware import require_auth
from curriculum import loader
from curriculum.loader import Unit
from db import repo

_PASS_MARK = 0.80
_PRODUCE_COST = "explain"  # borrow the "explain" credit slot (1 credit)

# ConversationHandler states
_ST_IDLE = 0
_ST_RUNNING = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _progress_bar(passed: int, total: int, width: int = 10) -> str:
    filled = round(width * passed / max(total, 1))
    return "█" * filled + "░" * (width - filled)


def _unit_status_line(unit: Unit, progress: dict) -> str:
    p = progress.get(unit.id)
    if p and p.passed:
        icon = "✅"
    elif p and p.attempts > 0:
        pct = round(p.best_score * 100)
        icon = f"🔄 {pct}%"
    else:
        icon = "⬜"
    return f"{icon} {unit.order}. {unit.title_target} — _{unit.title_l1}_"


def _course_state(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return context.user_data.setdefault("_course", {})


def _session_items(unit: Unit, n_per_type: dict[str, int] | None = None) -> list[dict]:
    """Pick a balanced set of questions for one unit run."""
    if n_per_type is None:
        # Derive from spine exercises spec
        n_per_type = {ex["type"]: ex["n"] for ex in unit.exercises}

    selected: list[dict] = []
    for qtype, n in n_per_type.items():
        pool = unit.questions_of_type(qtype)
        if pool:
            selected.extend(random.sample(pool, min(n, len(pool))))
    return selected


def _level_from_user(user) -> tuple[str, str]:
    """Return (lang, level) for the student's current learning mode and CEFR."""
    lang = "en" if getattr(user, "learning_mode", "english") == "english" else "de"
    # Use the student's CEFR estimate to pick the right level; default A1.
    import json as _json
    cefr_json = getattr(user, "cefr_estimate", None) or "{}"
    try:
        cefr = _json.loads(cefr_json)
    except Exception:
        cefr = {}
    level = cefr.get("overall", cefr.get("grammar", "A1")).upper()
    # Clamp to a level we actually have content for.
    available = loader.available_levels(lang)
    if level not in available:
        level = available[0] if available else "A1"
    return lang, level


# ---------------------------------------------------------------------------
# /course — overview
# ---------------------------------------------------------------------------

@require_auth
async def course_overview(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    args = context.args or []
    if args:
        unit_id = args[0].lower()
        return await _start_unit(update, context, user, en, unit_id)

    lang, level = _level_from_user(user)
    units = loader.list_units(lang, level)

    if not units:
        await update.message.reply_text(
            "No course content is available yet for your level. "
            "Keep chatting — it's coming soon! 🚧"
        )
        return _ST_IDLE

    progress = repo.get_all_unit_progress(user.id)
    passed_ids = {uid for uid, p in progress.items() if p.passed}
    passed_count = len(passed_ids)

    bar = _progress_bar(passed_count, len(units))
    lines = [
        f"📚 *English {level} — Your course*",
        f"`{bar}` {passed_count}/{len(units)} units passed\n",
    ]
    for unit in units:
        lines.append(_unit_status_line(unit, progress))

    # "Continue" button → first unpassed unit
    next_unit = loader.first_unpassed_unit(lang, level, passed_ids)
    keyboard_rows = []
    if next_unit:
        keyboard_rows.append([
            InlineKeyboardButton(
                f"▶️ Continue — {next_unit.title_target}",
                callback_data=f"course:start:{next_unit.id}",
            )
        ])
    if passed_count == len(units) and units:
        lines.append("\n🎉 You've passed all units at this level!")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None,
    )
    return _ST_IDLE


# ---------------------------------------------------------------------------
# Lesson card
# ---------------------------------------------------------------------------

async def _show_lesson_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
    unit_id: str,
) -> int:
    unit = loader.get_unit(unit_id)
    if not unit:
        msg = update.effective_message
        await msg.reply_text("Unit not found. Use /course to see available units.")
        return _ST_IDLE

    progress = repo.get_unit_progress(user.id, unit_id)
    status = ""
    if progress and progress.passed:
        status = f"\n✅ Passed (best: {round(progress.best_score * 100)}%)"
    elif progress and progress.attempts:
        status = f"\n🔄 Attempted {progress.attempts}× — best {round(progress.best_score * 100)}%"

    explain_text = "\n".join(f"• {b}" for b in unit.explain)
    examples_text = "\n".join(
        f"_{ex['target']}_ — {ex['gloss']}" for ex in unit.examples
    )
    pitfalls_text = "\n".join(f"⚠️ {p}" for p in unit.pitfalls)

    card = (
        f"📖 *{unit.title_target}*\n"
        f"_{unit.title_l1}_{status}\n\n"
        f"*Can-do:* {unit.can_do}\n\n"
        f"{explain_text}\n\n"
        f"*Examples:*\n{examples_text}\n\n"
        f"*Watch out for:*\n{pitfalls_text}"
    )

    n_questions = sum(ex["n"] for ex in unit.exercises)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"✏️ Start {n_questions} exercises",
            callback_data=f"course:go:{unit_id}",
        ),
        InlineKeyboardButton("🔙 Overview", callback_data="course:overview"),
    ]])

    msg = update.effective_message
    await msg.reply_text(card, parse_mode="Markdown", reply_markup=keyboard)
    return _ST_IDLE


async def on_lesson_card_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    query = update.callback_query
    await query.answer()
    unit_id = query.data.split(":", 2)[2]
    return await _show_lesson_card(update, context, user, en, unit_id)


# ---------------------------------------------------------------------------
# Exercise runner
# ---------------------------------------------------------------------------

async def _start_unit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
    unit_id: str,
) -> int:
    unit = loader.get_unit(unit_id)
    if not unit:
        await update.effective_message.reply_text(
            "Unit not found. Use /course to see available units."
        )
        return _ST_IDLE

    items = _session_items(unit)
    if not items:
        # No bank questions yet — show lesson card and note the gap.
        await update.effective_message.reply_text(
            f"📖 The exercises for *{unit.title_target}* aren't ready yet.\n"
            "Here's the lesson card while you wait:",
            parse_mode="Markdown",
        )
        return await _show_lesson_card(update, context, user, en, unit_id)

    state = _course_state(context)
    state.update({
        "unit_id": unit_id,
        "items": items,
        "idx": 0,
        "correct": 0,
        "total": len(items),
        "answers": [],
    })

    await update.effective_message.reply_text(
        f"✏️ *{unit.title_target}* — {len(items)} questions\n\n"
        "Answer each question. Type /stopcourse to exit at any time.",
        parse_mode="Markdown",
    )
    return await _send_next_question(update, context, user, en)


async def on_start_exercises_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    query = update.callback_query
    await query.answer()
    unit_id = query.data.split(":", 2)[2]
    return await _start_unit(update, context, user, en, unit_id)


async def _send_next_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    state = _course_state(context)
    idx = state["idx"]
    items = state["items"]

    if idx >= len(items):
        return await _finish_unit(update, context, user, en)

    item = items[idx]
    qtype = item.get("type")
    prompt = item.get("prompt", "")
    q_num = f"*Q{idx + 1}/{len(items)}* ({qtype})\n\n"

    if qtype == "mcq":
        opts = item.get("options", [])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"{i + 1}. {opt}", callback_data=f"course:ans:{i}")
            for i in range(len(opts))
        ]])
        await update.effective_message.reply_text(
            q_num + prompt,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return _ST_RUNNING

    # cloze / transform / produce — text answer
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


async def on_mcq_answer(
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
    why = item.get("why", "")
    opts = item.get("options", [])

    if correct:
        feedback = f"✅ *Correct!* {opts[correct_idx]}\n_{why}_"
    else:
        feedback = (
            f"❌ *Not quite.* You chose: {opts[choice]}\n"
            f"✔️ Answer: *{opts[correct_idx]}*\n_{why}_"
        )

    await query.edit_message_reply_markup(None)
    await update.effective_message.reply_text(feedback, parse_mode="Markdown")

    _record_and_advance(context, user.id, item, correct, str(choice))
    return await _send_next_question(update, context, user, en)


async def on_text_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    state = _course_state(context)
    if "unit_id" not in state:
        return _ST_IDLE

    idx = state["idx"]
    item = state["items"][idx]
    qtype = item.get("type")
    user_answer = (update.message.text or "").strip()

    if qtype == "produce":
        return await _grade_produce(update, context, user, en, item, user_answer)

    # cloze / transform — local string comparison
    correct, feedback = _grade_locally(item, user_answer)
    await update.message.reply_text(feedback, parse_mode="Markdown")

    _record_and_advance(context, user.id, item, correct, user_answer)
    return await _send_next_question(update, context, user, en)


def _grade_locally(item: dict, user_answer: str) -> tuple[bool, str]:
    """Check cloze/transform against the accepted list. Returns (correct, feedback)."""
    accepted: list[str] = item.get("accept", [item.get("answer", "")])
    normalised = user_answer.lower().strip().rstrip(".")
    correct = any(normalised == a.lower().strip().rstrip(".") for a in accepted)
    why = item.get("why", "")
    canonical = item.get("answer", accepted[0] if accepted else "—")
    if correct:
        return True, f"✅ *Correct!*\n_{why}_"
    return False, (
        f"❌ *Not quite.* You wrote: _{user_answer}_\n"
        f"✔️ Answer: *{canonical}*\n_{why}_"
    )


async def _grade_produce(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
    item: dict,
    user_answer: str,
) -> int:
    """Grade a produce question with one LLM call."""
    from bot.credits import COSTS, credits_check, credit_error_response, spend
    from llm.structured import generate_json

    cost = COSTS.get(_PRODUCE_COST, 1)
    status = credits_check(user.id, cost)
    if status != "ok":
        text, kb = credit_error_response(en, status, user.id)
        await update.message.reply_text(text, reply_markup=kb)
        # Count as attempted but not graded — skip forward
        state = _course_state(context)
        state["idx"] += 1
        return await _send_next_question(update, context, user, en)

    rubric_lines = "\n".join(f"- {r}" for r in item.get("rubric", []))
    model_answer = item.get("model_answer", "")
    prompt_text = (
        f"You are grading a short English writing exercise.\n\n"
        f"Task: {item['prompt']}\n\n"
        f"Rubric (each criterion is pass/fail):\n{rubric_lines}\n\n"
        f"Model answer (for reference only): {model_answer}\n\n"
        f"Student answer: {user_answer}\n\n"
        "Return a JSON object with:\n"
        '  "passed": true/false (true if ALL rubric criteria are met),\n'
        '  "score": int 0 to 3 (number of criteria met),\n'
        '  "feedback": string (1-2 sentences in English, encouraging and specific).'
    )

    result, _ = await generate_json(prompt_text, schema=None)
    spend(user.id, task=_PRODUCE_COST, model="llm")

    passed = result.get("passed", False)
    feedback_text = result.get("feedback", "Good try!")
    score = result.get("score", 0)
    total_criteria = len(item.get("rubric", []))

    if passed:
        fb = f"✅ *Well done!* ({score}/{total_criteria} criteria)\n_{feedback_text}_"
    else:
        fb = (
            f"🔄 *Almost!* ({score}/{total_criteria} criteria)\n"
            f"_{feedback_text}_\n\n"
            f"Model answer: _{model_answer}_"
        )

    await update.message.reply_text(fb, parse_mode="Markdown")
    state = _course_state(context)
    _record_and_advance(context, user.id, item, passed, user_answer)
    return await _send_next_question(update, context, user, en)


def _record_and_advance(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    item: dict,
    correct: bool,
    answer_given: str,
) -> None:
    state = _course_state(context)
    state["idx"] += 1
    if correct:
        state["correct"] += 1
    state["answers"].append({"item_id": item["id"], "correct": correct})

    repo.record_item_attempt(
        user_id=user_id,
        unit_id=state["unit_id"],
        item_id=item["id"],
        item_type=item.get("type", ""),
        correct=correct,
        answer_given=answer_given,
    )


# ---------------------------------------------------------------------------
# Finish — score, flashcard pipeline (H4)
# ---------------------------------------------------------------------------

async def _finish_unit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    state = _course_state(context)
    unit_id = state.get("unit_id", "")
    correct = state.get("correct", 0)
    total = state.get("total", 1)
    score = correct / max(total, 1)
    passed = score >= _PASS_MARK

    progress = repo.record_unit_attempt(user.id, unit_id, score)

    bar = _progress_bar(correct, total, width=10)
    summary_lines = [
        f"{'🎉 Passed!' if passed else '🔄 Not passed yet — try again any time!'}",
        f"`{bar}` {correct}/{total} correct ({round(score * 100)}%)",
    ]
    if passed:
        unit = loader.get_unit(unit_id)
        lang, level = _level_from_user(user)
        next_u = loader.next_unit(lang, level, unit.order if unit else 0)
        if next_u:
            summary_lines.append(f"\n➡️ Next up: *{next_u.title_target}*")
            next_btn = [[InlineKeyboardButton(
                f"▶️ Start next unit",
                callback_data=f"course:start:{next_u.id}",
            )]]
        else:
            summary_lines.append("\n🏆 You've completed all available units at this level!")
            next_btn = []
    else:
        next_btn = [[InlineKeyboardButton(
            "🔁 Try again", callback_data=f"course:go:{unit_id}"
        )]]

    # H4 — turn missed questions into flashcards
    flashcard_count = await _create_flashcards_from_missed(user, unit_id)
    if flashcard_count:
        summary_lines.append(
            f"\n🃏 {flashcard_count} missed question(s) added to your flashcard deck."
        )

    keyboard = InlineKeyboardMarkup(next_btn + [[
        InlineKeyboardButton("📚 Back to overview", callback_data="course:overview")
    ]]) if (next_btn or True) else None

    await update.effective_message.reply_text(
        "\n".join(summary_lines),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    # Clear course state
    context.user_data.pop("_course", None)
    return _ST_IDLE


async def _create_flashcards_from_missed(user, unit_id: str) -> int:
    """Add missed items to the flashcard deck. Returns count created."""
    missed_ids = repo.get_missed_items(user.id, unit_id)
    if not missed_ids:
        return 0

    unit = loader.get_unit(unit_id)
    if not unit:
        return 0

    count = 0
    for item in unit.questions:
        if item["id"] not in missed_ids:
            continue
        # Build a flashcard term from the question prompt
        prompt_text = item.get("prompt", "")
        answer_text = item.get("answer") or (
            item["options"][item["answer"]] if item.get("type") == "mcq" else ""
        )
        if not prompt_text:
            continue

        # Check if a vocab item with this term already exists
        term = f"[{unit.id}] {prompt_text[:80]}"
        existing = repo.find_personal_word(user.id, term)
        if not existing:
            repo.add_personal_word(
                user_id=user.id,
                term=term,
                translation=answer_text[:200] if answer_text else "(see unit)",
                context_sentence=item.get("why", "")[:300],
            )
            repo.mark_flashcard_created(user.id, unit_id, item["id"])
            count += 1

    return count


# ---------------------------------------------------------------------------
# Stop mid-unit
# ---------------------------------------------------------------------------

@require_auth
async def stop_course(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    context.user_data.pop("_course", None)
    await update.message.reply_text(
        "Course paused. Use /course to pick up where you left off."
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Overview callback (back button)
# ---------------------------------------------------------------------------

async def on_overview_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    en: bool,
) -> int:
    query = update.callback_query
    await query.answer()
    # Re-use the /course command logic
    context.args = []
    return await course_overview(update, context, user, en)


# ---------------------------------------------------------------------------
# Build handlers
# ---------------------------------------------------------------------------

def build_handlers() -> list:
    """Return the list of handlers to register in main.py."""

    # Wrap every handler with require_auth
    def _auth(fn):
        return require_auth(fn)

    lesson_card_handler = CallbackQueryHandler(
        require_auth(on_lesson_card_button), pattern=r"^course:start:"
    )
    overview_btn_handler = CallbackQueryHandler(
        require_auth(on_overview_button), pattern=r"^course:overview$"
    )

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("course", require_auth(course_overview)),
            CallbackQueryHandler(
                require_auth(on_start_exercises_button), pattern=r"^course:go:"
            ),
        ],
        states={
            _ST_IDLE: [
                lesson_card_handler,
                overview_btn_handler,
                CallbackQueryHandler(
                    require_auth(on_start_exercises_button), pattern=r"^course:go:"
                ),
            ],
            _ST_RUNNING: [
                CallbackQueryHandler(
                    require_auth(on_mcq_answer), pattern=r"^course:ans:\d+"
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    require_auth(on_text_answer),
                ),
                CommandHandler("stopcourse", require_auth(stop_course)),
            ],
        },
        fallbacks=[CommandHandler("stopcourse", require_auth(stop_course))],
        per_user=True,
        per_chat=True,
    )

    return [conv, lesson_card_handler, overview_btn_handler]
