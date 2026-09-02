"""/start, /help, /profile command handlers."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.middleware import require_auth

WELCOME = (
    "Hallo! Ich bin Karly, dein Deutsch-Tutor. 🇩🇪\n\n"
    "Right now I'm still being built (Phase 0). Send me any message and I'll "
    "echo it back to prove the plumbing works.\n\n"
    "Commands:\n"
    "/help — show this help\n"
    "/profile — your learning profile (coming soon)"
)

HELP = (
    "Karly — German tutor bot.\n\n"
    "/start — welcome\n"
    "/help — this help\n"
    "/profile — your learning profile\n\n"
    "More coming: /assess, conversation mode, /practice, PDF uploads."
)


@require_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME)


@require_auth
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP)


@require_auth
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Profile is not available yet — it arrives in Phase 2."
    )
