"""Shared bot utilities."""
from __future__ import annotations

from telegram import InlineKeyboardMarkup, Message


async def safe_reply(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Send reply_text, falling back to parse_mode=None on Markdown parse errors."""
    try:
        await message.reply_text(text, reply_markup=reply_markup)
    except Exception:
        await message.reply_text(text, parse_mode=None, reply_markup=reply_markup)


async def safe_edit(query, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Call edit_message_text on a CallbackQuery, falling back to parse_mode=None."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except Exception:
        await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)


async def safe_send(bot, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Call bot.send_message, falling back to parse_mode=None on Markdown parse errors."""
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception:
        await bot.send_message(chat_id, text, parse_mode=None, reply_markup=reply_markup)
