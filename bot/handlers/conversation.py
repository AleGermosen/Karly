"""Default message handler — the tutor pass-through (Phase 2).

Any non-command text is sent to the LLM router with Karly's tutor persona,
using the last N messages as context. Corrections the model emits in the
❌ wrong → ✅ right — reason format are parsed and logged as VocabItem rows
(source=conversation) so they feed /profile counts and, later, /practice.

Also handles /topic <x> (steer the conversation) and /english <q> (meta Q&A).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from bot import credits as credit_mod
from bot.middleware import require_auth
from db.models import VocabSource
from db.repo import (
    add_message,
    add_vocab_items,
    get_user_by_telegram_id,
    mark_due_by_terms,
    recent_document,
    recent_history,
    recent_user_messages,
    set_correction_level,
    user_message_stats,
)
from bot.handlers import media as media_mod
from llm import memory as memory_mod
from llm import prompts
from llm.errors import AllBackendsExhausted, LLMUnavailable, QuotaExceeded
from llm.router import Task, ladder_status, route, route_result
from llm.structured import generate_json

logger = logging.getLogger(__name__)

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏 (All LLM quotas reached.)"
QUOTA_MSG_EN = "Daily limit reached — try again later. 🙏"
ERROR_MSG = "Entschuldigung, da ging etwas schief. Versuch es nochmal."
ERROR_MSG_EN = "Sorry, something went wrong. Please try again."

# Backend-transition notices (bilingual, matching Karly's style).
_BACKEND_NOTICES_DE: dict[str, str] = {
    "⚡ Groq": "⚡ Läuft auf Groq — schnell.",
    "⚡ Groq Mini": (
        "⚡ Groqs Hauptmodell hat sein Limit erreicht — ich wechsle zum kleineren Modell. "
        "Immer noch schnell. Reset um Mitternacht (UTC)."
    ),
    "🤖 Gemini": (
        "🐢 Groqs Gratis-Limit ist heute aufgebraucht — ich wechsle zu Gemini. "
        "Etwas langsamer (~20s)."
    ),
    "🐌 Ollama": (
        "🐌 Alle Cloud-Gratis-Limits sind heute erschöpft — ich laufe jetzt lokal (Ollama). "
        "Langsam (~1 Min/Antwort), aber es geht."
    ),
}

_BACKEND_NOTICES_EN: dict[str, str] = {
    "⚡ Groq": "⚡ Usando Groq — rápido.",
    "⚡ Groq Mini": (
        "⚡ El modelo principal de Groq alcanzó su límite — cambiando al modelo más pequeño. "
        "Sigue siendo rápido. Se reinicia a medianoche (UTC)."
    ),
    "🤖 Gemini": (
        "🐢 La cuota gratuita de Groq se agotó — cambiando a Gemini. "
        "Un poco más lento (~20s)."
    ),
    "🐌 Ollama": (
        "🐌 Todas las cuotas en la nube están agotadas — ejecutando localmente (Ollama) ahora. "
        "Lento (~1 min/respuesta), pero funciona."
    ),
}

_RECOVERED_NOTICE_DE = "⚡ Zurück auf Groqs schnellem Modell!"
_RECOVERED_NOTICE_EN = "⚡ ¡De vuelta en el modelo rápido de Groq!"

# Matches:  ❌ wrong → ✅ right — reason
_CORRECTION_RE = re.compile(
    r"❌\s*(?P<wrong>.+?)\s*→\s*✅\s*(?P<right>.+?)\s*(?:—|--|-)\s*(?P<why>.+)"
)


def _user_level(cefr_estimate_json: str | None) -> str:
    if not cefr_estimate_json:
        return "A2-B1"
    try:
        data = json.loads(cefr_estimate_json)
        if isinstance(data, dict) and data.get("overall"):
            return str(data["overall"])
    except (ValueError, TypeError):
        pass
    return "A2-B1"


async def _keep_typing(bot, chat_id: int) -> None:
    """Re-send the 'typing' chat action every few seconds until cancelled.

    Telegram clears the indicator after ~5 s, but LLM replies can take 20 s+;
    without this the chat looks dead long before the answer lands.
    """
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def _route_with_typing(context, chat_id: int, task: Task, prompt: str, **kw):
    """Run route_result() while keeping the typing indicator alive."""
    typing = asyncio.create_task(_keep_typing(context.bot, chat_id))
    try:
        return await route_result(task, prompt, **kw)
    finally:
        typing.cancel()


def _backend_notice(prev_label: str | None, new_label: str, en: bool = False) -> str | None:
    """Return a transition notice to send the user, or None if nothing to say."""
    if prev_label == new_label:
        return None
    if prev_label is not None and new_label == "⚡ Groq":
        return _RECOVERED_NOTICE_EN if en else _RECOVERED_NOTICE_DE
    notices = _BACKEND_NOTICES_EN if en else _BACKEND_NOTICES_DE
    return notices.get(new_label)


_CORR_CACHE_MAX = 30  # keep the last N corrected replies actionable


def _correction_keyboard(message_id: int, en: bool = False) -> InlineKeyboardMarkup:
    if en:
        row = [
            InlineKeyboardButton("📖 ¿Por qué?", callback_data=f"corr:why:{message_id}"),
            InlineKeyboardButton("➕ Ejemplo", callback_data=f"corr:example:{message_id}"),
            InlineKeyboardButton("🎯 Practicar", callback_data=f"corr:drill:{message_id}"),
            InlineKeyboardButton("🔊", callback_data=f"corr:say:{message_id}"),
        ]
    else:
        row = [
            InlineKeyboardButton("📖 Warum?", callback_data=f"corr:why:{message_id}"),
            InlineKeyboardButton("➕ Beispiel", callback_data=f"corr:example:{message_id}"),
            InlineKeyboardButton("🎯 Üben", callback_data=f"corr:drill:{message_id}"),
            InlineKeyboardButton("🔊", callback_data=f"corr:say:{message_id}"),
        ]
    return InlineKeyboardMarkup([row])


def _cache_corrections(
    context: ContextTypes.DEFAULT_TYPE, message_id: int, corrections: list[dict]
) -> None:
    cache: dict[int, list[dict]] = context.user_data.setdefault("corr_cache", {})
    cache[message_id] = corrections
    if len(cache) > _CORR_CACHE_MAX:  # drop oldest by insertion order
        for old in list(cache)[:-_CORR_CACHE_MAX]:
            del cache[old]


def _parse_corrections(reply: str) -> list[dict]:
    """Extract corrections as vocab dicts from the tutor's reply."""
    items = []
    for m in _CORRECTION_RE.finditer(reply):
        right = m.group("right").strip()
        wrong = m.group("wrong").strip()
        why = m.group("why").strip()
        items.append(
            {
                "term": right,
                "translation": why,
                "context_sentence": f"❌ {wrong} → ✅ {right}",
            }
        )
    return items


@require_auth
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return

    # If a media task is pending for this user, hand off to that handler first.
    if context.user_data.get("_pending_media_task"):
        await media_mod.task_submission(update, context)
        return

    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:  # should not happen — middleware creates it
        return

    history = recent_history(user.id, limit=config.CONTEXT_WINDOW_MESSAGES)
    level: int = int(user.correction_level) if user.correction_level is not None else 3
    learning_mode = getattr(user, "learning_mode", "german") or "german"
    en = learning_mode == "english"

    # Warm-up rule: no corrections for the first 5 messages or after a 24h break,
    # at any level below 5 (exam mode is opted-in explicitly, never silenced).
    effective_level = level
    if level < 5:
        msg_count, last_at = user_message_stats(user.id)
        if msg_count < 5:
            effective_level = 0
        elif last_at is not None:
            last_naive = last_at.replace(tzinfo=None) if last_at.tzinfo else last_at
            if datetime.utcnow() - last_naive > timedelta(hours=24):
                effective_level = 0

    if en:
        system = prompts.ENGLISH_TUTOR_PERSONA.format(level=_user_level(user.cefr_estimate))
    else:
        system = prompts.TUTOR_PERSONA.format(level=_user_level(user.cefr_estimate))
    system += prompts.build_correction_block(effective_level, english=en)
    system += prompts.TONE_RULES

    # Inject personalization memory so the conversation feels continuous.
    system += prompts.build_memory_block(
        getattr(user, "profile_notes", None),
        getattr(user, "last_session_summary", None),
    )

    topic = context.user_data.get("topic")
    if topic:
        system += f"\n- Current focus topic: steer toward '{topic}'."

    if context.user_data.get("docfocus"):
        doc = recent_document(user.id)
        if doc and doc.get("summary"):
            system += (
                f"\n- AJ is studying the document '{doc['filename']}'. When it "
                f"fits, steer toward its topic. Summary: {doc['summary']}"
            )

    # Rate limit — throttle rapid-fire messages.
    if not credit_mod.check_rate_limit(context, credit_mod.COSTS["chat"]):
        await message.reply_text(credit_mod.rate_limited_text(en))
        return

    # Credit gates — per-student and class-wide.
    _credit_status = credit_mod.credits_check(user.id, credit_mod.COSTS["chat"])
    if _credit_status != "ok":
        _text, _kb = credit_mod.credit_error_response(en, _credit_status)
        await message.reply_text(_text, reply_markup=_kb)
        return

    try:
        result = await _route_with_typing(
            context, message.chat_id, Task.chat, text, system=system, history=history
        )
    except (QuotaExceeded, AllBackendsExhausted):
        await message.reply_text(
            credit_mod.capacity_exhausted_text(en),
            reply_markup=credit_mod.capacity_exhausted_keyboard(en),
        )
        return
    except LLMUnavailable as exc:
        logger.error("LLM unavailable: %s", exc)
        await message.reply_text(ERROR_MSG_EN if en else ERROR_MSG)
        return

    reply = result.text
    corrections = _parse_corrections(reply) if level > 0 else []
    add_message(user.id, "user", text)
    add_message(user.id, "assistant", reply, corrections=corrections or None)

    # Every 10 user messages, fire a background session summarizer (F-14 memory).
    msg_counter = context.user_data.get("_mem_counter", 0) + 1
    context.user_data["_mem_counter"] = msg_counter
    if msg_counter % 10 == 0:
        asyncio.create_task(
            memory_mod.run_session_summarizer(
                user.id, getattr(user, "profile_notes", None)
            )
        )
    if corrections:
        add_vocab_items(user.id, corrections, source=VocabSource.conversation)
        # One-time nudge: first correction this session — tell them about /corrections.
        if not context.user_data.get("_corrections_nudge_sent"):
            context.user_data["_corrections_nudge_sent"] = True
            if en:
                nudge = (
                    "_(💡 You can adjust how detailed my corrections are with "
                    "/corrections 0–5. Current level: {level}.)_"
                ).format(level=level)
            else:
                nudge = (
                    "_(💡 Du kannst den Korrektur-Level mit /corrections 0–5 anpassen. "
                    "Aktuell: {level}.)_"
                ).format(level=level)
            await message.reply_text(nudge)

    # Record usage after a successful call.
    credit_mod.spend(
        user.id,
        task="chat",
        model=result.model,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )

    # Low-balance nudge — shown once when the student is close to their limit.
    remaining = credit_mod.credits_remaining(user.id)
    if 1 <= remaining <= 5:
        nudge = (
            f"_(💡 {remaining} chat credit{'s' if remaining != 1 else ''} left today — "
            "flashcards and the game are always free.)_"
        )
        await message.reply_text(nudge)

    # Backend-change notification (send before the reply so it reads naturally).
    prev_label = context.user_data.get("last_backend_label")
    new_label = result.rung.label
    notice = _backend_notice(prev_label, new_label, en=en)
    if notice:
        await message.reply_text(notice)
    context.user_data["last_backend_label"] = new_label

    # Per-reply backend tag when /backend is on.
    if context.user_data.get("backend_tag_on"):
        reply = f"{reply}\n\n_{new_label}_"

    sent = await message.reply_text(reply)

    # Attach follow-up action buttons when the reply contained corrections.
    if corrections:
        _cache_corrections(context, sent.message_id, corrections)
        await sent.edit_reply_markup(
            reply_markup=_correction_keyboard(sent.message_id, en=en)
        )


@require_auth
async def on_correction_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the 📖/➕/🎯 buttons attached to a corrected reply."""
    query = update.callback_query
    await query.answer()
    _, action, raw_mid = query.data.split(":")
    corrections = (context.user_data.get("corr_cache") or {}).get(int(raw_mid))
    if not corrections:
        user = get_user_by_telegram_id(update.effective_user.id)
        en = getattr(user, "learning_mode", "german") == "english" if user else False
        msg = (
            "Esta corrección ya no está disponible. Intenta con un mensaje reciente."
            if en else
            "Diese Korrektur ist zu alt. Probiere es mit einer neueren Nachricht."
        )
        await query.message.reply_text(msg)
        return

    user = get_user_by_telegram_id(update.effective_user.id)
    en = getattr(user, "learning_mode", "german") == "english" if user else False
    chat_id = query.message.chat_id
    block = "\n".join(c["context_sentence"] for c in corrections)

    if action == "drill":
        terms = [c["term"] for c in corrections]
        n = mark_due_by_terms(user.id, terms) if user else 0
        if en:
            await query.message.reply_text(
                f"🎯 {n} word(s) marked for practice — /flashcards."
            )
        else:
            await query.message.reply_text(
                f"🎯 {n} Wort/Wörter zur Übung markiert — /flashcards. "
                "(Marked for practice.)"
            )
        return

    if action == "say":
        from bot.handlers.pronounce import pronounce_word, _LANG
        lang = _LANG["english" if en else "german"]
        # Pronounce the first corrected term.
        term = corrections[0].get("term", "") if corrections else ""
        if term:
            await pronounce_word(update, context, term, lang)
        return

    if en:
        system = (
            prompts.ENGLISH_CORRECTION_EXPLAIN if action == "why"
            else prompts.ENGLISH_CORRECTION_EXAMPLE
        )
    else:
        system = (
            prompts.CORRECTION_EXPLAIN if action == "why" else prompts.CORRECTION_EXAMPLE
        )
    _uid = user.id if user else 0
    _credit_status = credit_mod.credits_check(_uid, credit_mod.COSTS["explain"])
    if _credit_status != "ok":
        _text, _kb = credit_mod.credit_error_response(en, _credit_status)
        await query.message.reply_text(_text, reply_markup=_kb)
        return

    try:
        result = await _route_with_typing(
            context, chat_id, Task.chat, block, system=system
        )
    except (QuotaExceeded, AllBackendsExhausted):
        await query.message.reply_text(
            credit_mod.capacity_exhausted_text(en),
            reply_markup=credit_mod.capacity_exhausted_keyboard(en),
        )
        return
    except LLMUnavailable:
        await query.message.reply_text(ERROR_MSG_EN if en else ERROR_MSG)
        return

    if user:
        credit_mod.spend(user.id, task="explain", model=result.rung.model_id)
    await query.message.reply_text(result.text)


@require_auth
async def topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    en = getattr(user, "learning_mode", "german") == "english" if user else False
    arg = " ".join(context.args).strip() if context.args else ""
    if not arg:
        current = context.user_data.get("topic")
        if current:
            if en:
                await update.effective_message.reply_text(
                    f"Current topic: {current}. /topic <x> to change, /topic clear to reset."
                )
            else:
                await update.effective_message.reply_text(
                    f"Aktuelles Thema: {current}. /topic <x> zum Wechseln, "
                    "/topic clear zum Zurücksetzen."
                )
        else:
            if en:
                await update.effective_message.reply_text(
                    "No topic set. Use /topic <topic> (e.g. /topic job interviews)."
                )
            else:
                await update.effective_message.reply_text(
                    "Kein Thema gesetzt. Nutze /topic <Thema> (z.B. /topic Elektrotechnik)."
                )
        return
    if arg.lower() in ("clear", "reset", "none"):
        context.user_data.pop("topic", None)
        msg = "Topic cleared." if en else "Thema zurückgesetzt. (Topic cleared.)"
        await update.effective_message.reply_text(msg)
        return
    context.user_data["topic"] = arg
    if en:
        await update.effective_message.reply_text(
            f"Got it — let's talk about *{arg}*. Go ahead!"
        )
    else:
        await update.effective_message.reply_text(
            f"Alles klar — wir sprechen jetzt über *{arg}*. Leg los!"
        )


@require_auth
async def english(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user and getattr(user, "learning_mode", "german") == "english":
        # In English mode /english doesn't apply — redirect to /spanish.
        if context.args:
            context.args  # forward the args
            await update.effective_message.reply_text(
                "_(En modo inglés, tus preguntas van con /spanish — te reenvío ahora.)_"
            )
            await spanish(update, context)
        else:
            await update.effective_message.reply_text(
                "En modo inglés usa /spanish para hacer preguntas en español.\n"
                "Ejemplo: /spanish ¿cuándo uso 'the'?"
            )
        return

    question = " ".join(context.args).strip() if context.args else ""
    if not question:
        await update.effective_message.reply_text(
            "Ask a meta-question in English, e.g. /english when do I use dative?"
        )
        return
    en = False
    _uid = user.id if user else None
    if _uid:
        _credit_status = credit_mod.credits_check(_uid, credit_mod.COSTS["chat"])
        if _credit_status != "ok":
            _text, _kb = credit_mod.credit_error_response(en, _credit_status)
            await update.effective_message.reply_text(_text, reply_markup=_kb)
            return
    try:
        result = await _route_with_typing(
            context,
            update.effective_message.chat_id,
            Task.chat,
            question,
            system=prompts.ENGLISH_META,
        )
    except (QuotaExceeded, AllBackendsExhausted):
        await update.effective_message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
        return

    if _uid:
        credit_mod.spend(_uid, task="chat", model=result.rung.model_id)
    prev_label = context.user_data.get("last_backend_label")
    new_label = result.rung.label
    notice = _backend_notice(prev_label, new_label, en=en)
    if notice:
        await update.effective_message.reply_text(notice)
    context.user_data["last_backend_label"] = new_label

    await update.effective_message.reply_text(result.text)


@require_auth
async def spanish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/spanish <pregunta> — meta-question in Spanish (for English-mode users)."""
    user = get_user_by_telegram_id(update.effective_user.id)
    en = True
    question = " ".join(context.args).strip() if context.args else ""
    if not question:
        await update.effective_message.reply_text(
            "Haz una pregunta en español, por ejemplo: /spanish ¿cuándo uso 'the'?"
        )
        return
    _uid = user.id if user else None
    if _uid:
        _credit_status = credit_mod.credits_check(_uid, credit_mod.COSTS["chat"])
        if _credit_status != "ok":
            _text, _kb = credit_mod.credit_error_response(en, _credit_status)
            await update.effective_message.reply_text(_text, reply_markup=_kb)
            return
    try:
        result = await _route_with_typing(
            context,
            update.effective_message.chat_id,
            Task.chat,
            question,
            system=prompts.SPANISH_META,
        )
    except (QuotaExceeded, AllBackendsExhausted):
        await update.effective_message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
        return

    if _uid:
        credit_mod.spend(_uid, task="chat", model=result.rung.model_id)
    prev_label = context.user_data.get("last_backend_label")
    new_label = result.rung.label
    notice = _backend_notice(prev_label, new_label, en=True)
    if notice:
        await update.effective_message.reply_text(notice)
    context.user_data["last_backend_label"] = new_label
    await update.effective_message.reply_text(result.text)


_LEVEL_DESC_DE = {
    0: "Aus — nie ❌/✅ Zeilen",
    1: "Sanft — nur wenn Sinn bricht (Standard)",
    2: "Leicht — + Wiederholungsmuster",
    3: "Ausgewogen — klare Grammatikfehler, max. 2",
    4: "Gründlich — + Stil & Wortwahl, max. 4",
    5: "Prüfung — alles, inkl. Tippfehler",
}

_LEVEL_DESC_EN = {
    0: "Off — never ❌/✅ lines",
    1: "Gentle — only meaning-breaking (default)",
    2: "Light — + repeated patterns",
    3: "Balanced — clear grammar errors, max 2",
    4: "Thorough — + word choice/style, max 4",
    5: "Exam — everything, incl. typos",
}

# Old string aliases still accepted for muscle memory.
_STRING_ALIASES = {"off": 0, "aus": 0, "relaxed": 1, "locker": 1, "strict": 4, "on": 4, "an": 4}


def _corrections_keyboard(current: int, en: bool) -> InlineKeyboardMarkup:
    descs = _LEVEL_DESC_EN if en else _LEVEL_DESC_DE
    rows = []
    for lvl in range(6):
        mark = " ✓" if lvl == current else ""
        rows.append([InlineKeyboardButton(
            f"{lvl}: {descs[lvl]}{mark}",
            callback_data=f"setcorr:{lvl}",
        )])
    return InlineKeyboardMarkup(rows)


@require_auth
async def corrections(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/corrections [0-5|off|relaxed|strict] — set or view correction strictness."""
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    en = getattr(user, "learning_mode", "german") == "english"
    current: int = int(user.correction_level) if user.correction_level is not None else 3
    arg = (context.args[0].lower() if context.args else "").strip()

    # Accept numeric or legacy-string argument.
    new_level: int | None = None
    if arg.isdigit() and 0 <= int(arg) <= 5:
        new_level = int(arg)
    elif arg in _STRING_ALIASES:
        new_level = _STRING_ALIASES[arg]

    if new_level is not None:
        set_correction_level(user.id, new_level)
        name = prompts.LEVEL_NAMES[new_level]
        if en:
            desc = _LEVEL_DESC_EN[new_level]
            await update.effective_message.reply_text(
                f"Corrections set to **{new_level} — {name}**.\n_{desc}_"
            )
        else:
            desc = _LEVEL_DESC_DE[new_level]
            await update.effective_message.reply_text(
                f"Korrekturen auf **{new_level} — {name}** gesetzt.\n_{desc}_"
            )
        return

    # No arg — show the picker.
    if en:
        header = f"Correction level: **{current} — {prompts.LEVEL_NAMES[current]}**\nChoose a level:"
    else:
        header = f"Korrektur-Level: **{current} — {prompts.LEVEL_NAMES[current]}**\nLevel wählen:"
    await update.effective_message.reply_text(
        header, reply_markup=_corrections_keyboard(current, en)
    )


@require_auth
async def on_corrections_pick(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the /corrections inline-keyboard level buttons."""
    query = update.callback_query
    await query.answer()
    new_level = int(query.data.split(":")[1])
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    en = getattr(user, "learning_mode", "german") == "english"
    set_correction_level(user.id, new_level)
    name = prompts.LEVEL_NAMES[new_level]
    if en:
        desc = _LEVEL_DESC_EN[new_level]
        await query.edit_message_text(f"Corrections set to **{new_level} — {name}**.\n_{desc}_")
    else:
        desc = _LEVEL_DESC_DE[new_level]
        await query.edit_message_text(
            f"Korrekturen auf **{new_level} — {name}** gesetzt.\n_{desc}_"
        )


@require_auth
async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/summary — analyse recent messages and list what to work on.

    Sends the session's user messages in one batch to the LLM, so mistakes are
    surfaced even when inline corrections were off. Corrections found feed the
    same spaced-repetition vocab pipeline as inline ones.
    """
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return

    en = getattr(user, "learning_mode", "german") == "english"
    _credit_status = credit_mod.credits_check(user.id, credit_mod.COSTS["summary"])
    if _credit_status != "ok":
        _text, _kb = credit_mod.credit_error_response(en, _credit_status)
        await update.effective_message.reply_text(_text, reply_markup=_kb)
        return
    messages = recent_user_messages(user.id, limit=config.CONTEXT_WINDOW_MESSAGES)
    if not messages:
        if en:
            await update.effective_message.reply_text(
                "Todavía no hay nada que analizar — escríbeme un poco primero. 🙂"
            )
        else:
            await update.effective_message.reply_text(
                "Noch nichts zum Auswerten — schreib mir erst ein paar Sätze. 🙂"
            )
        return

    batch = "\n".join(f"- {m}" for m in messages)
    try:
        result, _ = await _summary_analyze(context, update.effective_message.chat_id, batch, en=en)
        credit_mod.spend(user.id, task="summary", model="analyze")
    except (QuotaExceeded, AllBackendsExhausted):
        await update.effective_message.reply_text(QUOTA_MSG_EN if en else QUOTA_MSG)
        return
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG_EN if en else ERROR_MSG)
        return

    if not isinstance(result, dict):
        await update.effective_message.reply_text(ERROR_MSG_EN if en else ERROR_MSG)
        return

    items = [
        it for it in (result.get("items") or [])
        if isinstance(it, dict) and (it.get("term") or "").strip()
    ]
    saved = 0
    if items:
        saved = add_vocab_items(user.id, items, source=VocabSource.conversation)

    if en:
        lines = ["📝 *Análisis*\n", (result.get("summary") or "").strip()]
        if items:
            lines.append("\nPara practicar:")
            for it in items[:10]:
                ctx = it.get("context_sentence") or it.get("term")
                lines.append(f"  • {ctx}")
            lines.append(f"\n{saved} guardadas para practicar. /practice para repasar. 💪")
    else:
        lines = ["📝 *Auswertung*\n", (result.get("summary") or "").strip()]
        if items:
            lines.append("\nZu üben:")
            for it in items[:10]:
                ctx = it.get("context_sentence") or it.get("term")
                lines.append(f"  • {ctx}")
            lines.append(f"\n{saved} zur Übung gespeichert. /practice zum Üben. 💪")
    await update.effective_message.reply_text("\n".join(l for l in lines if l))


async def _summary_analyze(context, chat_id: int, batch: str, en: bool = False):
    typing = asyncio.create_task(_keep_typing(context.bot, chat_id))
    system = prompts.ENGLISH_SESSION_SUMMARY if en else prompts.SESSION_SUMMARY
    try:
        return await generate_json(Task.analyze, batch, system=system)
    finally:
        typing.cancel()


@require_auth
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — backend ladder state + Groq request quota snapshot."""
    from llm.groq_client import quota_snapshot

    rungs = ladder_status(Task.chat)
    current = context.user_data.get(
        "last_backend_label", rungs[0]["label"] if rungs else "?"
    )

    lines = [f"⚙️ *Backend-Status* — aktiv: {current}\n"]

    poisoned = []
    for r in rungs:
        if r["state"] == "ready":
            lines.append(f"  {r['label']}: ✅ frei")
        else:
            avail = r.get("available_at")
            reset_str = avail.strftime("%H:%M UTC") if avail else "?"
            reason = r.get("reason") or "limit"
            lines.append(f"  {r['label']}: ⛔ {reason} (Reset {reset_str})")
            poisoned.append(r["label"])

    if poisoned:
        lines.append(f"\n⚠️ *Poisoned rungs:* {', '.join(poisoned)}")

    quota = quota_snapshot()
    if quota:
        lines.append("\n📊 *Groq Quota* (letzte Antwort):")
        import config as _config
        model_labels = {
            _config.GROQ_MODEL_PRIMARY: "120b (primary)",
            _config.GROQ_MODEL_FALLBACK: "20b (fallback)",
        }
        for model_id, q in quota.items():
            label = model_labels.get(model_id, model_id)
            rem = q.get("remaining_req")
            lim = q.get("limit_req")
            rem_tok = q.get("remaining_tok")
            lim_tok = q.get("limit_tok")
            reset_at = q.get("reset_at")
            req_str = f"{rem}/{lim} req" if rem is not None and lim else "? req"
            tok_str = f"{rem_tok}/{lim_tok} tok" if rem_tok is not None and lim_tok else ""
            reset_str = f" — reset {reset_at.strftime('%H:%M UTC')}" if reset_at else ""
            detail = f"{req_str}" + (f", {tok_str}" if tok_str else "") + reset_str
            lines.append(f"  {label}: {detail}")
        lines.append("  _(Quota is per-minute on free tier. Check console.groq.com for monthly totals.)_")
    else:
        lines.append("\n_(Groq quota: no calls made yet this session.)_")

    await update.effective_message.reply_text("\n".join(lines))


@require_auth
async def backend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/backend on|off — toggle per-reply backend tag footer."""
    arg = (context.args[0].lower() if context.args else "").strip()
    if arg in ("on", "an", "ein"):
        context.user_data["backend_tag_on"] = True
        await update.effective_message.reply_text(
            "Backend-Tag AN — jede Antwort zeigt das aktive Modell. "
            "(Backend tag on — every reply shows the active model.)"
        )
        return
    if arg in ("off", "aus"):
        context.user_data["backend_tag_on"] = False
        await update.effective_message.reply_text(
            "Backend-Tag AUS. (Backend tag off.)"
        )
        return
    state = "AN" if context.user_data.get("backend_tag_on") else "AUS"
    await update.effective_message.reply_text(
        f"Backend-Tag ist {state}. Nutze /backend on oder /backend off."
    )


async def on_free_feature_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer the 'free:practice' / 'free:impostor' buttons on credit-exhausted messages."""
    query = update.callback_query
    await query.answer()
    feature = query.data.split(":", 1)[1]
    if feature == "practice":
        await query.message.reply_text("Type /practice to open flashcards. It's always free! 🃏")
    else:
        await query.message.reply_text("Type /impostor new to start a game. Always free! 🎮")
