"""/practice — spaced-repetition session, and /review — stats.

A practice session pulls due VocabItems and drills each with one of three modes:
  • flashcard — recall the meaning, then self-grade (buttons)
  • cloze     — fill the blank in the stored context sentence (typed)
  • sentence  — use the term in your own sentence, LLM-checked (typed)

Grades feed SM-2 via repo.apply_grade. Also exposes /remind for the optional
daily reminder.
"""
from __future__ import annotations

import logging
import random
import re

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
    apply_grade,
    count_due,
    due_vocab,
    get_user_by_telegram_id,
    hardest_items,
    practice_streak,
    random_translations,
    record_practice,
)
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task
from llm.structured import generate_json

logger = logging.getLogger(__name__)

IN_SESSION = 1
SESSION_LIMIT = 10

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏 (Gemini quota reached.)"

# Self-grade buttons for flashcards -> SM-2 quality.
_GRADE_BUTTONS = [
    ("Nochmal ❌", 1),
    ("Schwer 😕", 3),
    ("Gut 🙂", 4),
    ("Leicht 😎", 5),
]


def _grade_keyboard() -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(label, callback_data=f"grade:{q}")
        for label, q in _GRADE_BUTTONS
    ]
    return InlineKeyboardMarkup([row])


def _pick_mode(item: dict) -> str:
    modes = ["flashcard"]
    if item.get("translation"):
        modes.append("flashcard")
        modes.append("mcq")  # tap-only recall; needs distractors at render time
    ctx = item.get("context_sentence") or ""
    if item["term"] and item["term"] in ctx:
        modes.append("cloze")
    modes.append("sentence")
    return random.choice(modes)


def _mcq_options(user_id: int, item: dict) -> tuple[list[str], int] | None:
    """Build shuffled MCQ options (correct translation + distractors) and the
    index of the correct one. Returns None if not enough distractors exist."""
    correct = item.get("translation")
    if not correct:
        return None
    distractors = random_translations(user_id, item["id"], limit=3)
    distractors = [d for d in distractors if d != correct]
    if len(distractors) < 2:  # need at least a 3-way choice to be worthwhile
        return None
    options = distractors[:3] + [correct]
    random.shuffle(options)
    return options, options.index(correct)


@require_auth
async def practice_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return ConversationHandler.END

    items = due_vocab(user.id, limit=SESSION_LIMIT)
    if not items:
        await update.effective_message.reply_text(
            "Nichts fällig zum Üben! 🎉 Schreib mir auf Deutsch oder mach /test, "
            "um neue Vokabeln zu sammeln. (Nothing due right now.)"
        )
        return ConversationHandler.END

    context.user_data["practice_queue"] = items
    context.user_data["practice_user_id"] = user.id
    context.user_data["practice_done"] = 0
    record_practice(user.id)

    await update.effective_message.reply_text(
        f"Übung! {len(items)} fällige Vokabeln. /stop zum Beenden.\n"
        "(Practice time — /stop to end.)"
    )
    return await _next_card(update, context)


async def _next_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    queue: list[dict] = context.user_data.get("practice_queue", [])
    if not queue:
        done = context.user_data.get("practice_done", 0)
        _clear(context)
        await _reply(update, f"Fertig! {done} Karten geübt. 💪 (Session done.)")
        return ConversationHandler.END

    item = queue[0]
    mode = _pick_mode(item)
    context.user_data["current_item"] = item
    context.user_data["current_mode"] = mode

    if mode == "mcq":
        user_id = context.user_data.get("practice_user_id")
        built = _mcq_options(user_id, item)
        if built is None:
            mode = "flashcard"  # fall back if not enough distractors
            context.user_data["current_mode"] = mode
        else:
            options, correct_idx = built
            context.user_data["await"] = "mcq"
            context.user_data["mcq_correct"] = correct_idx
            lines = [f"🃏 Was bedeutet: *{item['term']}*?\n"]
            for i, opt in enumerate(options):
                lines.append(f"{i + 1}. {opt}")
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(str(i + 1), callback_data=f"mcqcard:{i}")
                        for i in range(len(options))
                    ]
                ]
            )
            await _reply(update, "\n".join(lines), keyboard=kb)
            return IN_SESSION

    if mode == "flashcard":
        context.user_data["await"] = "reveal"
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Antwort zeigen 👀", callback_data="reveal")]]
        )
        await _reply(
            update,
            f"🃏 Was bedeutet: *{item['term']}*?\n(Recall the meaning, then reveal.)",
            keyboard=kb,
        )
    elif mode == "cloze":
        context.user_data["await"] = "cloze"
        blanked = re.sub(
            re.escape(item["term"]), "_____", item["context_sentence"], count=1
        )
        await _reply(
            update,
            f"✏️ Fülle die Lücke:\n\n{blanked}\n\n(Type the missing word.)",
        )
    else:  # sentence
        context.user_data["await"] = "sentence"
        await _reply(
            update,
            f"🛠️ Benutze *{item['term']}* in einem eigenen Satz.\n"
            "(Use the word in your own sentence.)",
        )
    return IN_SESSION


@require_auth
async def on_reveal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    item = context.user_data.get("current_item")
    if not item:
        return IN_SESSION
    answer = item.get("translation") or "(keine Übersetzung gespeichert)"
    ctx = item.get("context_sentence")
    text = f"💡 *{item['term']}* — {answer}"
    if ctx:
        text += f"\n_{ctx}_"
    text += "\n\nWie gut wusstest du es?"
    context.user_data["await"] = "grade"
    await query.edit_message_text(text, reply_markup=_grade_keyboard())
    return IN_SESSION


@require_auth
async def on_mcq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if context.user_data.get("await") != "mcq":
        return IN_SESSION
    choice = int(query.data.split(":", 1)[1])
    item = context.user_data.get("current_item")
    correct_idx = context.user_data.get("mcq_correct")
    correct = choice == correct_idx
    if item:
        apply_grade(item["id"], 4 if correct else 2)
    answer = item.get("translation") if item else None
    mark = "✅ Richtig!" if correct else f"❌ Es war: {answer}"
    await query.edit_message_text(query.message.text + f"\n\n{mark}")
    return await _advance(update, context)


@require_auth
async def on_grade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    quality = int(query.data.split(":", 1)[1])
    item = context.user_data.get("current_item")
    if item:
        apply_grade(item["id"], quality)
    await query.edit_message_text(query.message.text)
    return await _advance(update, context)


@require_auth
async def on_typed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    awaiting = context.user_data.get("await")
    item = context.user_data.get("current_item")
    if not item or awaiting not in ("cloze", "sentence"):
        return IN_SESSION

    answer = (update.effective_message.text or "").strip()

    if awaiting == "cloze":
        correct = item["term"].lower() in answer.lower() or answer.lower() in (
            item["term"].lower()
        )
        quality = 4 if correct else 2
        apply_grade(item["id"], quality)
        mark = "✅ Richtig!" if correct else f"❌ Es war: *{item['term']}*"
        await update.effective_message.reply_text(mark)
        return await _advance(update, context)

    # sentence mode -> LLM check
    await context.bot.send_chat_action(
        chat_id=update.effective_message.chat_id, action="typing"
    )
    try:
        result, _ = await generate_json(
            Task.check,
            f'AJ wrote: "{answer}"',
            system=prompts.PRACTICE_SENTENCE_CHECK.format(term=item["term"]),
        )
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        _clear(context)
        return ConversationHandler.END
    except LLMUnavailable:
        result = None

    if isinstance(result, dict):
        correct = bool(result.get("correct"))
        quality = 4 if correct else 2
        fb = result.get("feedback", "")
        corrected = result.get("corrected", "")
        mark = "✅" if correct else "❌"
        msg = f"{mark} {fb}"
        if corrected and corrected.strip().lower() != answer.strip().lower():
            msg += f"\n✅ {corrected}"
    else:
        quality = 3  # neutral if we couldn't check
        msg = "(Konnte nicht prüfen — weiter geht's.)"
    apply_grade(item["id"], quality)
    await update.effective_message.reply_text(msg)
    return await _advance(update, context)


async def _advance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    queue: list[dict] = context.user_data.get("practice_queue", [])
    if queue:
        queue.pop(0)
    context.user_data["practice_done"] = context.user_data.get("practice_done", 0) + 1
    return await _next_card(update, context)


@require_auth
async def practice_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    done = context.user_data.get("practice_done", 0)
    _clear(context)
    await update.effective_message.reply_text(
        f"Übung beendet. {done} Karten geübt. (Stopped.)"
    )
    return ConversationHandler.END


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in (
        "practice_queue",
        "practice_user_id",
        "practice_done",
        "current_item",
        "current_mode",
        "await",
        "mcq_correct",
    ):
        context.user_data.pop(k, None)


async def _reply(update: Update, text: str, keyboard=None) -> None:
    msg = update.effective_message or (
        update.callback_query.message if update.callback_query else None
    )
    if msg:
        await msg.reply_text(text, reply_markup=keyboard)


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler(["practice", "flashcards"], practice_start)],
        states={
            IN_SESSION: [
                CommandHandler("stop", practice_stop),
                CallbackQueryHandler(on_reveal, pattern=r"^reveal$"),
                CallbackQueryHandler(on_grade, pattern=r"^grade:\d$"),
                CallbackQueryHandler(on_mcq, pattern=r"^mcqcard:\d$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_typed),
            ]
        },
        fallbacks=[CommandHandler("stop", practice_stop)],
        name="practice",
        per_message=False,
    )


# --- /review stats ---------------------------------------------------------

@require_auth
async def review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    due = count_due(user.id)
    streak = practice_streak(user.id)
    hardest = hardest_items(user.id, limit=5)

    lines = ["📈 *Review*\n", f"Fällig jetzt: *{due}*", f"Streak: *{streak}* Tage 🔥"]
    if hardest:
        lines.append("\nSchwierigste Vokabeln:")
        for h in hardest:
            lines.append(f"  • {h['term']} (EF {h['easiness']:.2f})")
    lines.append("\n/practice zum Üben.")
    await update.effective_message.reply_text("\n".join(lines))
