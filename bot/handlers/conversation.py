"""Default message handler — the tutor pass-through.

Phase 1: any non-command text is sent to the LLM router with Karly's tutor
persona, using the last N messages as context. Corrections are produced inline
by the model (structured logging of corrections comes in Phase 2).
"""
from __future__ import annotations

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
from bot.middleware import require_auth
from db.repo import add_message, get_user_by_telegram_id, recent_history
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task, route

logger = logging.getLogger(__name__)

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏 (Gemini quota reached.)"
ERROR_MSG = "Entschuldigung, da ging etwas schief. Versuch es nochmal."


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

    add_message(user.id, "user", text)
    add_message(user.id, "assistant", reply)
    await message.reply_text(reply)
