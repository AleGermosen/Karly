"""Default message handler.

Phase 0: a simple echo to prove Telegram plumbing works. This is replaced by
the tutor pass-through in Phase 1.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.middleware import require_auth


@require_auth
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.effective_message.text or ""
    await update.effective_message.reply_text(f"(echo) {text}")
