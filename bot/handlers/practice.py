"""/practice — spaced-repetition session, and /review — stats.

A practice session pulls due VocabItems and drills each with one of several modes:
  • flashcard — recall the meaning, then self-grade (buttons)
  • cloze     — fill the blank in the stored context sentence (typed)
  • sentence  — use the term in your own sentence, LLM-checked (typed)
  • mcq       — tap one of 4 options (local scoring, no LLM)

New in this revision:
  • Deck picker at session start — filter by source (All / Chat / Docs / Test)
  • DE↔EN direction toggle — /flip inside a session reverses the drill direction

Grades feed HLR (+ SM-2 for stats) via repo.apply_hlr_grade.
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
    apply_hlr_grade,
    count_due,
    count_due_by_source,
    due_vocab,
    get_user_by_telegram_id,
    hardest_items,
    practice_streak,
    random_terms,
    random_translations,
    record_practice,
)
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task
from llm.structured import generate_json

logger = logging.getLogger(__name__)

PICKING    = 1   # choosing deck / direction before the session starts
IN_SESSION = 2

SESSION_LIMIT = 10

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏 (Gemini quota reached.)"

# Deck filter options: (callback_key, label, source_value_or_None)
_DECKS = [
    ("all",          "📚 Alle",        None),
    ("conversation", "💬 Gespräch",    "conversation"),
    ("document",     "📄 Dokumente",   "document"),
    ("assessment",   "📝 Test",        "assessment"),
]
_KEY_TO_SOURCE: dict[str, str | None] = {k: s for k, _, s in _DECKS}

# Self-grade buttons for flashcards → HLR quality.
_GRADE_BUTTONS = [
    ("Nochmal ❌", 1),
    ("Schwer 😕", 3),
    ("Gut 🙂",    4),
    ("Leicht 😎", 5),
]


def _grade_keyboard() -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(label, callback_data=f"grade:{q}")
        for label, q in _GRADE_BUTTONS
    ]
    return InlineKeyboardMarkup([row])


def _deck_keyboard(counts: dict[str, int], total_due: int) -> InlineKeyboardMarkup:
    """Picker shown at session start. Each button starts the session immediately."""
    rows = []
    for key, label, source in _DECKS:
        n = total_due if source is None else counts.get(source, 0)
        btn = InlineKeyboardButton(f"{label} ({n})", callback_data=f"deck:{key}:de_en")
        rows.append([btn])
    # Direction row below
    rows.append([
        InlineKeyboardButton("🇩🇪→🇬🇧 Normal (DE→EN)", callback_data="deck:all:de_en"),
        InlineKeyboardButton("🇬🇧→🇩🇪 Umkehren (EN→DE)", callback_data="deck:all:en_de"),
    ])
    return InlineKeyboardMarkup(rows)


def _direction_label(direction: str) -> str:
    return "DE→EN 🇩🇪" if direction == "de_en" else "EN→DE 🇬🇧"


def _pick_mode(item: dict, direction: str) -> str:
    if direction == "en_de":
        # EN→DE: flashcard and MCQ only (cloze context is in German, doesn't
        # make sense reversed; sentence mode always uses the German term anyway)
        modes = ["flashcard", "flashcard"]
        if item.get("translation"):
            modes.append("mcq")
        return random.choice(modes)

    # DE→EN (default)
    modes = ["flashcard"]
    if item.get("translation"):
        modes += ["flashcard", "mcq"]
    ctx = item.get("context_sentence") or ""
    if item["term"] and item["term"] in ctx:
        modes.append("cloze")
    modes.append("sentence")
    return random.choice(modes)


def _mcq_options_de_en(
    user_id: int, item: dict
) -> tuple[list[str], int] | None:
    """DE→EN: show German term, options are English translations."""
    correct = item.get("translation")
    if not correct:
        return None
    distractors = random_translations(user_id, item["id"], limit=3)
    distractors = [d for d in distractors if d != correct]
    if len(distractors) < 2:
        return None
    options = distractors[:3] + [correct]
    random.shuffle(options)
    return options, options.index(correct)


def _mcq_options_en_de(
    user_id: int, item: dict
) -> tuple[list[str], int] | None:
    """EN→DE: show English translation, options are German terms."""
    correct = item.get("term")
    if not correct:
        return None
    distractors = random_terms(user_id, item["id"], limit=3)
    distractors = [d for d in distractors if d != correct]
    if len(distractors) < 2:
        return None
    options = distractors[:3] + [correct]
    random.shuffle(options)
    return options, options.index(correct)


@require_auth
async def practice_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return ConversationHandler.END
    if getattr(user, "learning_mode", "german") == "english":
        await update.effective_message.reply_text(
            "Este comando es solo para el modo alemán. "
            "Usa /language para cambiar de idioma."
        )
        return ConversationHandler.END

    total_due = count_due(user.id)
    if total_due == 0:
        await update.effective_message.reply_text(
            "Nichts fällig zum Üben! 🎉 Schreib mir auf Deutsch oder mach /test, "
            "um neue Vokabeln zu sammeln. (Nothing due right now.)"
        )
        return ConversationHandler.END

    by_source = count_due_by_source(user.id)
    kb = _deck_keyboard(by_source, total_due)
    await update.effective_message.reply_text(
        "🃏 *Karteikarten* — wähle ein Deck und eine Richtung:\n"
        "(Choose a deck to drill. The bottom row lets you flip the direction "
        "for any deck — tap it first, then choose a deck from the list above "
        "using /flip. Or just tap a deck to start DE→EN.)",
        reply_markup=kb,
    )
    context.user_data["practice_picker_user_id"] = user.id
    return PICKING


@require_auth
async def on_deck_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle a deck / direction button tap from the picker."""
    query = update.callback_query
    await query.answer()
    _, key, direction = query.data.split(":")

    source = _KEY_TO_SOURCE.get(key)
    user_id = context.user_data.get("practice_picker_user_id")
    if user_id is None:
        user = get_user_by_telegram_id(update.effective_user.id)
        user_id = user.id if user else None
    if user_id is None:
        return ConversationHandler.END

    items = due_vocab(user_id, limit=SESSION_LIMIT, source=source)
    if not items:
        await query.edit_message_text("Kein Karten fällig in diesem Deck. (Nothing due here.)")
        return ConversationHandler.END

    deck_label = next(label for k, label, _ in _DECKS if k == key)
    dir_label = _direction_label(direction)
    await query.edit_message_text(
        f"🃏 {deck_label} · {dir_label} — {len(items)} Karten. /stop zum Beenden.\n"
        "(/flip wechselt die Richtung während der Übung.)"
    )

    context.user_data["practice_queue"] = items
    context.user_data["practice_user_id"] = user_id
    context.user_data["practice_done"] = 0
    context.user_data["practice_dir"] = direction
    record_practice(user_id)
    return await _next_card(update, context)


@require_auth
async def practice_flip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle DE↔EN direction mid-session and re-render the current card."""
    cur = context.user_data.get("practice_dir", "de_en")
    new = "en_de" if cur == "de_en" else "de_en"
    context.user_data["practice_dir"] = new
    await update.effective_message.reply_text(
        f"🔄 Richtung gewechselt: {_direction_label(new)}"
    )
    # Clear the current card's await state so _next_card re-picks a mode.
    context.user_data.pop("await", None)
    context.user_data.pop("current_item", None)
    return await _next_card(update, context)


async def _next_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    queue: list[dict] = context.user_data.get("practice_queue", [])
    if not queue:
        done = context.user_data.get("practice_done", 0)
        _clear(context)
        await _reply(update, f"Fertig! {done} Karten geübt. 💪 (Session done.)")
        return ConversationHandler.END

    item = queue[0]
    direction = context.user_data.get("practice_dir", "de_en")
    mode = _pick_mode(item, direction)
    context.user_data["current_item"] = item
    context.user_data["current_mode"] = mode

    user_id = context.user_data.get("practice_user_id")

    if mode == "mcq":
        if direction == "en_de":
            built = _mcq_options_en_de(user_id, item)
            question = f"🃏 Wie sagt man auf Deutsch: *{item.get('translation', '?')}*?\n"
        else:
            built = _mcq_options_de_en(user_id, item)
            question = f"🃏 Was bedeutet: *{item['term']}*?\n"

        if built is None:
            mode = "flashcard"
            context.user_data["current_mode"] = mode
        else:
            options, correct_idx = built
            context.user_data["await"] = "mcq"
            context.user_data["mcq_correct"] = correct_idx
            lines = [question]
            for i, opt in enumerate(options):
                lines.append(f"{i + 1}. {opt}")
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(str(i + 1), callback_data=f"mcqcard:{i}")
                for i in range(len(options))
            ]])
            await _reply(update, "\n".join(lines), keyboard=kb)
            return IN_SESSION

    if mode == "flashcard":
        context.user_data["await"] = "reveal"
        if direction == "en_de":
            prompt_text = (
                f"🃏 Wie sagt man auf Deutsch: *{item.get('translation', '?')}*?\n"
                "(Recall the German term, then reveal.)"
            )
        else:
            prompt_text = (
                f"🃏 Was bedeutet: *{item['term']}*?\n"
                "(Recall the meaning, then reveal.)"
            )
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Antwort zeigen 👀", callback_data="reveal")]]
        )
        await _reply(update, prompt_text, keyboard=kb)

    elif mode == "cloze":
        # Cloze is only available in DE→EN direction.
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
    direction = context.user_data.get("practice_dir", "de_en")
    if direction == "en_de":
        answer_label = f"*{item['term']}*"
        gloss = item.get("translation") or ""
        text = f"💡 {item.get('translation', '?')} → {answer_label}"
        if gloss:
            text += f"\n_{item.get('context_sentence', '')}_"
    else:
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
    user_id = context.user_data.get("practice_user_id")
    if item and user_id:
        apply_hlr_grade(item["id"], user_id, 4 if correct else 2)
    direction = context.user_data.get("practice_dir", "de_en")
    if direction == "en_de":
        answer = item.get("term") if item else None
    else:
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
    user_id = context.user_data.get("practice_user_id")
    if item and user_id:
        apply_hlr_grade(item["id"], user_id, quality)
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
        user_id = context.user_data.get("practice_user_id")
        if user_id:
            apply_hlr_grade(item["id"], user_id, quality)
        mark = "✅ Richtig!" if correct else f"❌ Es war: *{item['term']}*"
        await update.effective_message.reply_text(mark)
        return await _advance(update, context)

    # sentence mode → LLM check
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
        quality = 3
        msg = "(Konnte nicht prüfen — weiter geht's.)"
    user_id = context.user_data.get("practice_user_id")
    if user_id:
        apply_hlr_grade(item["id"], user_id, quality)
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
        "practice_picker_user_id",
        "practice_done",
        "practice_dir",
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
            PICKING: [
                CallbackQueryHandler(on_deck_pick, pattern=r"^deck:"),
                CommandHandler("stop", practice_stop),
            ],
            IN_SESSION: [
                CommandHandler("stop", practice_stop),
                CommandHandler("flip", practice_flip),
                CallbackQueryHandler(on_reveal, pattern=r"^reveal$"),
                CallbackQueryHandler(on_grade, pattern=r"^grade:\d$"),
                CallbackQueryHandler(on_mcq, pattern=r"^mcqcard:\d$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_typed),
            ],
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
