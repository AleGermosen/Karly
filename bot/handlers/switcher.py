"""Auto-switch between conversation sessions without requiring an explicit /stop."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

# Maps user_data presence-key → (clear_fn, handler_ref).
# handler_ref is filled in at registration time via register().
_SESSIONS: dict[str, list] = {}  # key -> [clear_fn, conv_handler | None, display_name]

# Commands that start a new conversation session.
ENTRY_COMMANDS = ["daily", "quiz", "practice", "flashcards", "drill", "roleplay",
                  "test", "assess", "course"]


def register(mapping: dict[str, tuple]) -> None:
    """Register session clear functions and their ConversationHandler instances.

    mapping: { user_data_key: (clear_fn, conv_handler, display_name) }
    """
    for key, (clear_fn, handler, name) in mapping.items():
        _SESSIONS[key] = [clear_fn, handler, name]


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pre-handler: if the user is in an active session, clear it before the new command runs."""
    ud = context.user_data
    active_key = next((k for k in _SESSIONS if k in ud), None)
    if active_key is None:
        return  # No active session — nothing to do.

    clear_fn, conv_handler, name = _SESSIONS[active_key]

    # Wipe the session's user_data state.
    clear_fn(context)

    # Remove the user from the ConversationHandler's internal state machine so it
    # accepts the new entry command as a fresh start.
    if conv_handler is not None:
        key = (update.effective_chat.id, update.effective_user.id)
        conv_handler._conversations.pop(key, None)

    new_cmd = update.message.text.lstrip("/").split()[0].split("@")[0]
    await update.message.reply_text(
        f"_{name} session ended. Starting /{new_cmd}…_",
        parse_mode="Markdown",
    )
