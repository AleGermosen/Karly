"""Single-user auth gate.

If ALLOWED_USER_ID is set, only that Telegram user may use the bot.
If unset, the first user to interact is adopted and persisted, and thereafter
only that user is allowed.
"""
from __future__ import annotations

import logging
from functools import wraps
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

import config
from db.repo import any_user_exists, get_or_create_user, get_user_by_telegram_id

logger = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def _is_authorized(telegram_id: int) -> bool:
    # Explicit allow-list via env wins.
    if config.ALLOWED_USER_ID is not None:
        return telegram_id == config.ALLOWED_USER_ID

    # Otherwise: adopt the first user, then restrict to them.
    known = get_user_by_telegram_id(telegram_id)
    if known is not None:
        return True
    if not any_user_exists():
        return True  # first-ever user is adopted
    return False


def require_auth(handler: Handler) -> Handler:
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None:
            return
        if not _is_authorized(user.id):
            logger.warning("Rejected unauthorized user id=%s", user.id)
            if update.effective_message:
                await update.effective_message.reply_text(
                    "Sorry, this is a private bot."
                )
            return
        # Ensure a User row exists for authorized users.
        get_or_create_user(user.id, name=user.full_name)
        await handler(update, context)

    return wrapper
