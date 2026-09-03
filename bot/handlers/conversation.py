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

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
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
)
from llm import prompts
from llm.errors import AllBackendsExhausted, LLMUnavailable, QuotaExceeded
from llm.router import Task, ladder_status, route, route_result
from llm.structured import generate_json

logger = logging.getLogger(__name__)

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏 (All LLM quotas reached.)"
ERROR_MSG = "Entschuldigung, da ging etwas schief. Versuch es nochmal."

# Backend-transition notices (bilingual, matching Karly's style).
_BACKEND_NOTICES: dict[str, str] = {
    "⚡ Groq": (
        "⚡ Läuft auf Groq — schnell. (Talking to Groq's fast model.)"
    ),
    "⚡ Groq Mini": (
        "⚡ Groqs Hauptmodell hat sein Limit erreicht — ich wechsle zum kleineren Modell. "
        "Immer noch schnell. Reset um Mitternacht (UTC). (Switched to Groq Mini.)"
    ),
    "🤖 Gemini": (
        "🐢 Groqs Gratis-Limit ist heute aufgebraucht — ich wechsle zu Gemini. "
        "Etwas langsamer (~20s). (Switched to Gemini; slower.)"
    ),
    "🐌 Ollama": (
        "🐌 Alle Cloud-Gratis-Limits sind heute erschöpft — ich laufe jetzt lokal (Ollama). "
        "Langsam (~1 Min/Antwort), aber es geht. (Running locally now; slow.)"
    ),
}

_RECOVERED_NOTICE = "⚡ Zurück auf Groqs schnellem Modell! (Back on Groq's fast model.)"

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


def _backend_notice(prev_label: str | None, new_label: str) -> str | None:
    """Return a transition notice to send the user, or None if nothing to say."""
    if prev_label == new_label:
        return None
    # Recovering back to the primary Groq 70B rung.
    if prev_label is not None and new_label == "⚡ Groq":
        return _RECOVERED_NOTICE
    return _BACKEND_NOTICES.get(new_label)


_CORR_CACHE_MAX = 30  # keep the last N corrected replies actionable


def _correction_keyboard(message_id: int) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton("📖 Warum?", callback_data=f"corr:why:{message_id}"),
        InlineKeyboardButton("➕ Beispiel", callback_data=f"corr:example:{message_id}"),
        InlineKeyboardButton("🎯 Üben", callback_data=f"corr:drill:{message_id}"),
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

    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:  # should not happen — middleware creates it
        return

    history = recent_history(user.id, limit=config.CONTEXT_WINDOW_MESSAGES)
    level = user.correction_level
    learning_mode = getattr(user, "learning_mode", "german") or "german"

    if learning_mode == "english":
        system = prompts.ENGLISH_TUTOR_PERSONA.format(level=_user_level(user.cefr_estimate))
        if level == "strict":
            system += prompts.ENGLISH_CORRECTION_STRICT + prompts.ENGLISH_SLANG_NOTE
        elif level == "relaxed":
            system += prompts.ENGLISH_CORRECTION_RELAXED + prompts.ENGLISH_SLANG_NOTE
        else:
            system += prompts.ENGLISH_NO_CORRECTION_NOTE + prompts.ENGLISH_SLANG_NOTE
    else:
        system = prompts.TUTOR_PERSONA.format(level=_user_level(user.cefr_estimate))
        if level == "strict":
            system += prompts.CORRECTION_STRICT + prompts.SLANG_NOTE
        elif level == "relaxed":
            system += prompts.CORRECTION_RELAXED + prompts.SLANG_NOTE
        else:
            system += prompts.NO_CORRECTION_NOTE + prompts.SLANG_NOTE

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

    try:
        result = await _route_with_typing(
            context, message.chat_id, Task.chat, text, system=system, history=history
        )
    except (QuotaExceeded, AllBackendsExhausted):
        await message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable as exc:
        logger.error("LLM unavailable: %s", exc)
        await message.reply_text(ERROR_MSG)
        return

    reply = result.text
    corrections = _parse_corrections(reply) if level != "off" else []
    add_message(user.id, "user", text)
    add_message(user.id, "assistant", reply, corrections=corrections or None)
    if corrections:
        add_vocab_items(user.id, corrections, source=VocabSource.conversation)

    # Backend-change notification (send before the reply so it reads naturally).
    prev_label = context.user_data.get("last_backend_label")
    new_label = result.rung.label
    notice = _backend_notice(prev_label, new_label)
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
            reply_markup=_correction_keyboard(sent.message_id)
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
        await query.message.reply_text(
            "Diese Korrektur ist zu alt. (That correction is no longer active.)"
        )
        return

    chat_id = query.message.chat_id
    block = "\n".join(c["context_sentence"] for c in corrections)

    if action == "drill":
        user = get_user_by_telegram_id(update.effective_user.id)
        terms = [c["term"] for c in corrections]
        n = mark_due_by_terms(user.id, terms) if user else 0
        await query.message.reply_text(
            f"🎯 {n} Wort/Wörter zur Übung markiert — /flashcards. "
            "(Marked for practice.)"
        )
        return

    system = (
        prompts.CORRECTION_EXPLAIN if action == "why" else prompts.CORRECTION_EXAMPLE
    )
    try:
        result = await _route_with_typing(
            context, chat_id, Task.chat, block, system=system
        )
    except (QuotaExceeded, AllBackendsExhausted):
        await query.message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable:
        await query.message.reply_text(ERROR_MSG)
        return
    await query.message.reply_text(result.text)


@require_auth
async def topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    arg = " ".join(context.args).strip() if context.args else ""
    if not arg:
        current = context.user_data.get("topic")
        if current:
            await update.effective_message.reply_text(
                f"Aktuelles Thema: {current}. /topic <x> zum Wechseln, "
                "/topic clear zum Zurücksetzen."
            )
        else:
            await update.effective_message.reply_text(
                "Kein Thema gesetzt. Nutze /topic <Thema> (z.B. /topic Elektrotechnik)."
            )
        return
    if arg.lower() in ("clear", "reset", "none"):
        context.user_data.pop("topic", None)
        await update.effective_message.reply_text("Thema zurückgesetzt. (Topic cleared.)")
        return
    context.user_data["topic"] = arg
    await update.effective_message.reply_text(
        f"Alles klar — wir sprechen jetzt über *{arg}*. Leg los!"
    )


@require_auth
async def english(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args).strip() if context.args else ""
    if not question:
        await update.effective_message.reply_text(
            "Ask a meta-question in English, e.g. /english when do I use dative?"
        )
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

    prev_label = context.user_data.get("last_backend_label")
    new_label = result.rung.label
    notice = _backend_notice(prev_label, new_label)
    if notice:
        await update.effective_message.reply_text(notice)
    context.user_data["last_backend_label"] = new_label

    await update.effective_message.reply_text(result.text)


@require_auth
async def spanish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/spanish <pregunta> — meta-question in Spanish (for English-mode users)."""
    question = " ".join(context.args).strip() if context.args else ""
    if not question:
        await update.effective_message.reply_text(
            "Haz una pregunta en español, por ejemplo: /spanish ¿cuándo uso 'the'?"
        )
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

    prev_label = context.user_data.get("last_backend_label")
    new_label = result.rung.label
    notice = _backend_notice(prev_label, new_label)
    if notice:
        await update.effective_message.reply_text(notice)
    context.user_data["last_backend_label"] = new_label
    await update.effective_message.reply_text(result.text)


@require_auth
async def corrections(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/corrections strict|relaxed|off — set correction strictness."""
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    arg = (context.args[0].lower() if context.args else "").strip()

    if arg in ("strict", "on", "an", "ein"):
        set_correction_level(user.id, "strict")
        await update.effective_message.reply_text(
            "Korrekturen: STRICT — ich korrigiere jeden Fehler, auch Wortstellung "
            "und Stil. (Strict corrections on — every mistake flagged.)"
        )
        return
    if arg in ("relaxed", "locker"):
        set_correction_level(user.id, "relaxed")
        await update.effective_message.reply_text(
            "Korrekturen: RELAXED — ich korrigiere nur echte Fehler, die einen "
            "Muttersprachler verwirren würden. Stilfragen ignoriere ich. "
            "(Relaxed — only real errors flagged.)"
        )
        return
    if arg in ("off", "aus"):
        set_correction_level(user.id, "off")
        await update.effective_message.reply_text(
            "Korrekturen AUS — wir plaudern frei. Nutze /summary für eine "
            "Auswertung. (Corrections off; use /summary later.)"
        )
        return

    level = user.correction_level
    level_label = {"strict": "STRICT", "relaxed": "RELAXED", "off": "AUS"}.get(level, level)
    await update.effective_message.reply_text(
        f"Korrekturen: {level_label}.\n"
        "/corrections strict — alles korrigieren\n"
        "/corrections relaxed — nur echte Fehler\n"
        "/corrections off — keine Korrekturen"
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

    messages = recent_user_messages(user.id, limit=config.CONTEXT_WINDOW_MESSAGES)
    if not messages:
        await update.effective_message.reply_text(
            "Noch nichts zum Auswerten — schreib mir erst ein paar Sätze. 🙂"
        )
        return

    batch = "\n".join(f"- {m}" for m in messages)
    try:
        result, _ = await _summary_analyze(context, update.effective_message.chat_id, batch)
    except (QuotaExceeded, AllBackendsExhausted):
        await update.effective_message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
        return

    if not isinstance(result, dict):
        await update.effective_message.reply_text(ERROR_MSG)
        return

    items = [
        it for it in (result.get("items") or [])
        if isinstance(it, dict) and (it.get("term") or "").strip()
    ]
    saved = 0
    if items:
        saved = add_vocab_items(user.id, items, source=VocabSource.conversation)

    lines = ["📝 *Auswertung*\n", (result.get("summary") or "").strip()]
    if items:
        lines.append("\nZu üben:")
        for it in items[:10]:
            ctx = it.get("context_sentence") or it.get("term")
            lines.append(f"  • {ctx}")
        lines.append(f"\n{saved} zur Übung gespeichert. /practice zum Üben. 💪")
    await update.effective_message.reply_text("\n".join(l for l in lines if l))


async def _summary_analyze(context, chat_id: int, batch: str):
    typing = asyncio.create_task(_keep_typing(context.bot, chat_id))
    try:
        return await generate_json(
            Task.analyze, batch, system=prompts.SESSION_SUMMARY
        )
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

    for r in rungs:
        if r["state"] == "ready":
            lines.append(f"  {r['label']}: ✅ frei")
        else:
            avail = r.get("available_at")
            reset_str = avail.strftime("%H:%M UTC") if avail else "?"
            lines.append(f"  {r['label']}: ⛔ Limit (Reset {reset_str})")

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
