"""/practice — spaced-repetition session, and /review — stats.

A practice session pulls due VocabItems and drills each with one of several modes:
  • flashcard — recall the meaning, then self-grade (buttons)
  • cloze     — fill the blank in the stored context sentence (typed)
  • sentence  — use the term in your own sentence, LLM-checked (typed)
  • mcq       — tap one of 4 options (local scoring, no LLM)

German mode: term=German word, translation=English. Directions: DE→EN / EN→DE.
English mode: term=English word, translation=Spanish.  Directions: EN→ES / ES→EN.
              All UI strings are in Spanish for English mode.

Deck picker at session start — filter by source (All / Chat / Docs / Test).
/flip inside a session reverses the drill direction.
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

# ── Deck definitions ──────────────────────────────────────────────────────────

# (callback_key, label_de, label_es, source_value_or_None)
_DECKS = [
    ("all",          "📚 Alle",      "📚 Todas",      None),
    ("conversation", "💬 Gespräch",  "💬 Conversación", "conversation"),
    ("document",     "📄 Dokumente", "📄 Documentos", "document"),
    ("assessment",   "📝 Test",      "📝 Prueba",     "assessment"),
]
_KEY_TO_SOURCE: dict[str, str | None] = {k: s for k, _, _, s in _DECKS}

# Self-grade buttons
_GRADE_BUTTONS_DE = [
    ("Nochmal ❌", 1),
    ("Schwer 😕", 3),
    ("Gut 🙂",    4),
    ("Leicht 😎", 5),
]
_GRADE_BUTTONS_ES = [
    ("Otra vez ❌", 1),
    ("Difícil 😕",  3),
    ("Bien 🙂",     4),
    ("Fácil 😎",    5),
]


def _grade_keyboard(en: bool) -> InlineKeyboardMarkup:
    buttons = _GRADE_BUTTONS_ES if en else _GRADE_BUTTONS_DE
    row = [
        InlineKeyboardButton(label, callback_data=f"grade:{q}")
        for label, q in buttons
    ]
    return InlineKeyboardMarkup([row])


def _deck_keyboard(counts: dict[str, int], total_due: int, en: bool) -> InlineKeyboardMarkup:
    rows = []
    for key, label_de, label_es, source in _DECKS:
        label = label_es if en else label_de
        n = total_due if source is None else counts.get(source, 0)
        btn = InlineKeyboardButton(f"{label} ({n})", callback_data=f"deck:{key}:fwd")
        rows.append([btn])
    # Direction toggle row
    if en:
        rows.append([
            InlineKeyboardButton("🇺🇸→🇪🇸 Normal (EN→ES)", callback_data="deck:all:fwd"),
            InlineKeyboardButton("🇪🇸→🇺🇸 Invertir (ES→EN)", callback_data="deck:all:rev"),
        ])
    else:
        rows.append([
            InlineKeyboardButton("🇩🇪→🇬🇧 Normal (DE→EN)", callback_data="deck:all:fwd"),
            InlineKeyboardButton("🇬🇧→🇩🇪 Umkehren (EN→DE)", callback_data="deck:all:rev"),
        ])
    return InlineKeyboardMarkup(rows)


def _direction_label(direction: str, en: bool) -> str:
    if en:
        return "EN→ES 🇺🇸" if direction == "fwd" else "ES→EN 🇪🇸"
    return "DE→EN 🇩🇪" if direction == "fwd" else "EN→DE 🇬🇧"


def _pick_mode(item: dict, direction: str) -> str:
    if direction == "rev":
        modes = ["flashcard", "flashcard"]
        if item.get("translation"):
            modes.append("mcq")
        return random.choice(modes)

    modes = ["flashcard"]
    if item.get("translation"):
        modes += ["flashcard", "mcq"]
    ctx = item.get("context_sentence") or ""
    if item["term"] and item["term"] in ctx:
        modes.append("cloze")
    modes.append("sentence")
    return random.choice(modes)


def _mcq_options_fwd(user_id: int, item: dict) -> tuple[list[str], int] | None:
    """Forward: show term, options are translations."""
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


def _mcq_options_rev(user_id: int, item: dict) -> tuple[list[str], int] | None:
    """Reverse: show translation, options are terms."""
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


def _en(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.user_data.get("practice_mode") == "english"


@require_auth
async def practice_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return ConversationHandler.END

    mode = getattr(user, "learning_mode", "german") or "german"
    en = mode == "english"
    context.user_data["practice_mode"] = mode

    total_due = count_due(user.id)
    if total_due == 0:
        if en:
            await update.effective_message.reply_text(
                "¡Nada pendiente! 🎉 Habla conmigo en inglés o haz /test para acumular vocabulario."
            )
        else:
            await update.effective_message.reply_text(
                "Nichts fällig zum Üben! 🎉 Schreib mir auf Deutsch oder mach /test, "
                "um neue Vokabeln zu sammeln. (Nothing due right now.)"
            )
        return ConversationHandler.END

    by_source = count_due_by_source(user.id)
    kb = _deck_keyboard(by_source, total_due, en)
    if en:
        await update.effective_message.reply_text(
            "🃏 *Flashcards* — elige un mazo y dirección:\n"
            "(Toca un mazo para empezar EN→ES, o elige la dirección inversa abajo.)",
            reply_markup=kb,
        )
    else:
        await update.effective_message.reply_text(
            "🃏 *Karteikarten* — wähle ein Deck und eine Richtung:\n"
            "(Choose a deck to drill. Tap a deck to start DE→EN, "
            "or pick a direction from the bottom row.)",
            reply_markup=kb,
        )
    context.user_data["practice_picker_user_id"] = user.id
    return PICKING


@require_auth
async def on_deck_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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

    en = _en(context)
    items = due_vocab(user_id, limit=SESSION_LIMIT, source=source)
    if not items:
        msg = "Nada pendiente en este mazo." if en else "Kein Karten fällig in diesem Deck. (Nothing due here.)"
        await query.edit_message_text(msg)
        return ConversationHandler.END

    deck_label = next((label_es if en else label_de) for k, label_de, label_es, _ in _DECKS if k == key)
    dir_label = _direction_label(direction, en)
    if en:
        await query.edit_message_text(
            f"🃏 {deck_label} · {dir_label} — {len(items)} tarjetas. /stop para cancelar.\n"
            "(/flip invierte la dirección durante la sesión.)"
        )
    else:
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
    cur = context.user_data.get("practice_dir", "fwd")
    new = "rev" if cur == "fwd" else "fwd"
    context.user_data["practice_dir"] = new
    en = _en(context)
    if en:
        await update.effective_message.reply_text(f"🔄 Dirección cambiada: {_direction_label(new, en)}")
    else:
        await update.effective_message.reply_text(f"🔄 Richtung gewechselt: {_direction_label(new, en)}")
    context.user_data.pop("await", None)
    context.user_data.pop("current_item", None)
    return await _next_card(update, context)


async def _next_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    queue: list[dict] = context.user_data.get("practice_queue", [])
    if not queue:
        done = context.user_data.get("practice_done", 0)
        en = _en(context)
        _clear(context)
        msg = f"¡Listo! {done} tarjetas practicadas. 💪" if en else f"Fertig! {done} Karten geübt. 💪 (Session done.)"
        await _reply(update, msg)
        return ConversationHandler.END

    item = queue[0]
    direction = context.user_data.get("practice_dir", "fwd")
    mode = _pick_mode(item, direction)
    context.user_data["current_item"] = item
    context.user_data["current_mode"] = mode
    user_id = context.user_data.get("practice_user_id")
    en = _en(context)

    if mode == "mcq":
        if direction == "rev":
            built = _mcq_options_rev(user_id, item)
            if en:
                question = f"🃏 ¿Cómo se dice en inglés: *{item.get('translation', '?')}*?\n"
            else:
                question = f"🃏 Wie sagt man auf Deutsch: *{item.get('translation', '?')}*?\n"
        else:
            built = _mcq_options_fwd(user_id, item)
            if en:
                question = f"🃏 ¿Qué significa: *{item['term']}*?\n"
            else:
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
        if direction == "rev":
            if en:
                prompt_text = (
                    f"🃏 ¿Cómo se dice en inglés: *{item.get('translation', '?')}*?\n"
                    "(Recuerda la palabra en inglés, luego revela.)"
                )
            else:
                prompt_text = (
                    f"🃏 Wie sagt man auf Deutsch: *{item.get('translation', '?')}*?\n"
                    "(Recall the German term, then reveal.)"
                )
        else:
            if en:
                prompt_text = (
                    f"🃏 ¿Qué significa: *{item['term']}*?\n"
                    "(Recuerda el significado, luego revela.)"
                )
            else:
                prompt_text = (
                    f"🃏 Was bedeutet: *{item['term']}*?\n"
                    "(Recall the meaning, then reveal.)"
                )
        reveal_label = "Mostrar respuesta 👀" if en else "Antwort zeigen 👀"
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(reveal_label, callback_data="reveal")]]
        )
        await _reply(update, prompt_text, keyboard=kb)

    elif mode == "cloze":
        context.user_data["await"] = "cloze"
        blanked = re.sub(
            re.escape(item["term"]), "_____", item["context_sentence"], count=1
        )
        if en:
            await _reply(update, f"✏️ Completa el espacio:\n\n{blanked}\n\n(Escribe la palabra que falta.)")
        else:
            await _reply(update, f"✏️ Fülle die Lücke:\n\n{blanked}\n\n(Type the missing word.)")

    else:  # sentence
        context.user_data["await"] = "sentence"
        if en:
            await _reply(update, f"🛠️ Usa *{item['term']}* en una oración propia.\n(Escribe tu oración en inglés.)")
        else:
            await _reply(update, f"🛠️ Benutze *{item['term']}* in einem eigenen Satz.\n(Use the word in your own sentence.)")
    return IN_SESSION


@require_auth
async def on_reveal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    item = context.user_data.get("current_item")
    if not item:
        return IN_SESSION
    direction = context.user_data.get("practice_dir", "fwd")
    en = _en(context)

    if direction == "rev":
        answer_label = f"*{item['term']}*"
        text = f"💡 {item.get('translation', '?')} → {answer_label}"
        ctx = item.get("context_sentence", "")
        if ctx:
            text += f"\n_{ctx}_"
    else:
        answer = item.get("translation") or ("(sin traducción guardada)" if en else "(keine Übersetzung gespeichert)")
        ctx = item.get("context_sentence")
        text = f"💡 *{item['term']}* — {answer}"
        if ctx:
            text += f"\n_{ctx}_"

    how_well = "¿Qué tan bien lo sabías?" if en else "Wie gut wusstest du es?"
    text += f"\n\n{how_well}"
    context.user_data["await"] = "grade"
    await query.edit_message_text(text, reply_markup=_grade_keyboard(en))
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
    direction = context.user_data.get("practice_dir", "fwd")
    answer = item.get("term") if direction == "rev" else item.get("translation")
    en = _en(context)
    if en:
        mark = "✅ ¡Correcto!" if correct else f"❌ Era: {answer}"
    else:
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
    en = _en(context)

    if awaiting == "cloze":
        correct = item["term"].lower() in answer.lower() or answer.lower() in (
            item["term"].lower()
        )
        quality = 4 if correct else 2
        user_id = context.user_data.get("practice_user_id")
        if user_id:
            apply_hlr_grade(item["id"], user_id, quality)
        if en:
            mark = "✅ ¡Correcto!" if correct else f"❌ Era: *{item['term']}*"
        else:
            mark = "✅ Richtig!" if correct else f"❌ Es war: *{item['term']}*"
        await update.effective_message.reply_text(mark)
        return await _advance(update, context)

    # sentence mode → LLM check
    await context.bot.send_chat_action(
        chat_id=update.effective_message.chat_id, action="typing"
    )
    sentence_prompt = (
        prompts.ENGLISH_PRACTICE_SENTENCE_CHECK if en else prompts.PRACTICE_SENTENCE_CHECK
    ).format(term=item["term"])
    try:
        result, _ = await generate_json(
            Task.check,
            f'The user wrote: "{answer}"',
            system=sentence_prompt,
        )
    except QuotaExceeded:
        msg = "Límite alcanzado — inténtalo más tarde. 🙏" if en else "Tageslimit erreicht — versuch es später. 🙏 (Gemini quota reached.)"
        await update.effective_message.reply_text(msg)
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
        msg = "(No se pudo revisar — continuamos.)" if en else "(Konnte nicht prüfen — weiter geht's.)"
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
    en = _en(context)
    _clear(context)
    if en:
        await update.effective_message.reply_text(f"Sesión terminada. {done} tarjetas practicadas.")
    else:
        await update.effective_message.reply_text(f"Übung beendet. {done} Karten geübt. (Stopped.)")
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
        "practice_mode",
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
    en = getattr(user, "learning_mode", "german") == "english"
    due = count_due(user.id)
    streak = practice_streak(user.id)
    hardest = hardest_items(user.id, limit=5)

    if en:
        lines = ["📈 *Revisión*\n", f"Pendientes ahora: *{due}*", f"Racha: *{streak}* días 🔥"]
        if hardest:
            lines.append("\nPalabras más difíciles:")
            for h in hardest:
                lines.append(f"  • {h['term']} (EF {h['easiness']:.2f})")
        lines.append("\n/practice para practicar.")
    else:
        lines = ["📈 *Review*\n", f"Fällig jetzt: *{due}*", f"Streak: *{streak}* Tage 🔥"]
        if hardest:
            lines.append("\nSchwierigste Vokabeln:")
            for h in hardest:
                lines.append(f"  • {h['term']} (EF {h['easiness']:.2f})")
        lines.append("\n/practice zum Üben.")
    await update.effective_message.reply_text("\n".join(lines))
