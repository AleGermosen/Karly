"""Auth gate and language-picker gate.

require_auth:
  1. Checks ALLOWED_USER_ID (private deployments).
  2. Creates a User row if the user is new.
  3. If the user has never chosen a language (language_chosen=False),
     intercepts all commands except /start and /language and sends the
     language picker — so new students always land in the right mode.
"""
from __future__ import annotations

import logging
from functools import wraps
from typing import Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from db.repo import get_or_create_user, get_user_by_telegram_id

logger = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

# Inline keyboard shown to users who haven't chosen a language yet.
# Mirrors start.py's _PICKER_KB — defined here to avoid a circular import.
_PICKER_KB = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("🇩🇪 Deutsch lernen", callback_data="lang:german"),
        InlineKeyboardButton("🇺🇸 Learn English", callback_data="lang:english"),
    ]
])

# Commands that are allowed through even before a language is chosen.
_LANGUAGE_FREE_COMMANDS = {"start", "language", "help"}


def _is_authorized(telegram_id: int) -> bool:
    if config.ALLOWED_USER_ID is not None:
        return telegram_id == config.ALLOWED_USER_ID
    return True


def _command_name(update: Update) -> str | None:
    """Extract the bare command name from the update, or None."""
    msg = update.effective_message
    if msg and msg.text and msg.text.startswith("/"):
        cmd = msg.text.split()[0].lstrip("/").split("@")[0].lower()
        return cmd
    return None


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

        default_status = "active"
        if (
            config.ACCESS_MODE == "approval"
            and config.TEACHER_TELEGRAM_ID
            and user.id != config.TEACHER_TELEGRAM_ID
        ):
            default_status = "pending"

        db_user = get_or_create_user(user.id, name=user.full_name, default_status=default_status)

        async def _dismiss_button() -> None:
            """Silently dismiss the spinner on an intercepted callback tap."""
            if update.callback_query:
                try:
                    await update.callback_query.answer()
                except Exception:
                    pass

        # Access gate — hard block for removed/declined users.
        if db_user.status == "removed":
            await _dismiss_button()
            if update.effective_message:
                await update.effective_message.reply_text(
                    "Sorry, you don't have access to this bot."
                )
            return

        # Approval gate — pending users may only use /start and /language.
        if db_user.status == "pending":
            cmd = _command_name(update)
            if cmd not in _LANGUAGE_FREE_COMMANDS:
                await _dismiss_button()
                if update.effective_message:
                    await update.effective_message.reply_text(
                        "⏳ You're on the waiting list. "
                        "Your teacher hasn't approved you yet — check back soon!"
                    )
                return

        # Language gate — redirect to picker until the user has chosen.
        if not db_user.language_chosen:
            cmd = _command_name(update)
            if cmd not in _LANGUAGE_FREE_COMMANDS:
                await _dismiss_button()
                msg = update.effective_message
                if msg:
                    await msg.reply_text(
                        "¡Hola! / Hello! 👋\n\n"
                        "First, choose the language you want to learn:\n"
                        "Primero, elige el idioma que quieres aprender:",
                        reply_markup=_PICKER_KB,
                    )
                return

        return await handler(update, context)

    return wrapper
