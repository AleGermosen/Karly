"""Default message handler — the tutor pass-through (Phase 2).

Any non-command text is sent to the LLM router with Karly's tutor persona,
using the last N messages as context. Corrections the model emits in the
❌ wrong → ✅ right — reason format are parsed and logged as VocabItem rows
(source=conversation) so they feed /profile counts and, later, /practice.

Also handles /topic <x> (steer the conversation) and /english <q> (meta Q&A).
"""
from __future__ import annotations

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
)
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task, route

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
    system = prompts.TUTOR_PERSONA.format(level=_user_level(user.cefr_estimate))

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

    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")

    try:
        reply = await route(Task.chat, text, system=system, history=history)
    except QuotaExceeded:
        await message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable as exc:
        logger.error("LLM unavailable: %s", exc)
        await message.reply_text(ERROR_MSG)
        return

    corrections = _parse_corrections(reply)
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
    await context.bot.send_chat_action(
        chat_id=update.effective_message.chat_id, action="typing"
    )
    try:
        reply = await route(Task.chat, question, system=prompts.ENGLISH_META)
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        return
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
        return
    await update.effective_message.reply_text(reply)
