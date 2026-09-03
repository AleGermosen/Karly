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

from telegram import Update
from telegram.ext import ContextTypes

import config
from bot.middleware import require_auth
from db.models import VocabSource
from db.repo import (
    add_message,
    add_vocab_items,
    get_user_by_telegram_id,
    recent_document,
    recent_history,
    recent_user_messages,
    set_corrections,
)
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task, route
from llm.structured import generate_json

logger = logging.getLogger(__name__)

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏 (Gemini quota reached.)"
ERROR_MSG = "Entschuldigung, da ging etwas schief. Versuch es nochmal."

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
    """Run route() while keeping the typing indicator alive for the duration."""
    typing = asyncio.create_task(_keep_typing(context.bot, chat_id))
    try:
        return await route(task, prompt, **kw)
    finally:
        typing.cancel()


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
    corrections_on = user.corrections_on
    system = prompts.TUTOR_PERSONA.format(level=_user_level(user.cefr_estimate))
    system += prompts.CORRECTION_BLOCK if corrections_on else prompts.NO_CORRECTION_NOTE

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
        reply = await _route_with_typing(
            context, message.chat_id, Task.chat, text, system=system, history=history
        )
    except QuotaExceeded:
        await message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable as exc:
        logger.error("LLM unavailable: %s", exc)
        await message.reply_text(ERROR_MSG)
        return

    corrections = _parse_corrections(reply) if corrections_on else []
    add_message(user.id, "user", text)
    add_message(user.id, "assistant", reply, corrections=corrections or None)
    if corrections:
        add_vocab_items(user.id, corrections, source=VocabSource.conversation)

    await message.reply_text(reply)


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
        reply = await _route_with_typing(
            context,
            update.effective_message.chat_id,
            Task.chat,
            question,
            system=prompts.ENGLISH_META,
        )
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
        return
    await update.effective_message.reply_text(reply)


@require_auth
async def corrections(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/corrections on|off — toggle inline grammar corrections (persisted)."""
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    arg = (context.args[0].lower() if context.args else "").strip()

    if arg in ("on", "an", "ein"):
        set_corrections(user.id, True)
        await update.effective_message.reply_text(
            "Korrekturen AN — ich korrigiere jeden Fehler wieder. "
            "(Inline corrections on.)"
        )
        return
    if arg in ("off", "aus"):
        set_corrections(user.id, False)
        await update.effective_message.reply_text(
            "Korrekturen AUS — wir plaudern jetzt frei. Nutze /summary für eine "
            "Auswertung deiner Fehler. (Corrections off; use /summary later.)"
        )
        return

    state = "AN" if user.corrections_on else "AUS"
    await update.effective_message.reply_text(
        f"Korrekturen sind {state}. Nutze /corrections on oder /corrections off."
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
    except QuotaExceeded:
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
