"""/pronounce — send a voice note with the pronunciation of a word or phrase.

Uses gTTS (Google Text-to-Speech) — free, no extra API key.
German mode: pronounces in German.
English mode: pronounces in English.

Also adds a 🔊 button to correction action keyboards so students can hear
the corrected form without typing /pronounce manually.
"""
from __future__ import annotations

import io
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.middleware import require_auth
from db.repo import get_user_by_telegram_id

logger = logging.getLogger(__name__)

# gTTS lang codes per learning mode.
_LANG = {"german": "de", "english": "en"}


def _tts_bytes(text: str, lang: str) -> bytes:
    """Return MP3 bytes for *text* using gTTS. Raises on failure."""
    from gtts import gTTS
    buf = io.BytesIO()
    gTTS(text=text, lang=lang, slow=False).write_to_fp(buf)
    buf.seek(0)
    return buf.read()


@require_auth
async def pronounce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/pronounce WORD — send a voice note with the pronunciation."""
    user = get_user_by_telegram_id(update.effective_user.id)
    en = getattr(user, "learning_mode", "german") == "english" if user else False
    lang = _LANG["english" if en else "german"]

    phrase = " ".join(context.args).strip() if context.args else ""
    if not phrase:
        if en:
            await update.effective_message.reply_text(
                "Usage: /pronounce WORD\nExample: /pronounce necessary"
            )
        else:
            await update.effective_message.reply_text(
                "Usage: /pronounce WORT\nBeispiel: /pronounce Gesundheit"
            )
        return

    if len(phrase) > 200:
        msg = "Too long — max 200 characters." if en else "Zu lang — max. 200 Zeichen."
        await update.effective_message.reply_text(msg)
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="record_voice"
    )
    try:
        audio = _tts_bytes(phrase, lang)
    except Exception as exc:
        logger.warning("gTTS failed for %r: %s", phrase, exc)
        msg = (
            "Sorry, pronunciation isn't available right now."
            if en else
            "Aussprache gerade nicht verfügbar. Versuch es später."
        )
        await update.effective_message.reply_text(msg)
        return

    await update.effective_message.reply_voice(
        voice=io.BytesIO(audio),
        caption=f"🔊 _{phrase}_",
    )


async def pronounce_word(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    word: str,
    lang: str,
) -> None:
    """Internal helper — pronounce *word* in *lang*, called from other handlers."""
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="record_voice"
    )
    try:
        audio = _tts_bytes(word, lang)
        await update.effective_message.reply_voice(
            voice=io.BytesIO(audio),
            caption=f"🔊 _{word}_",
        )
    except Exception as exc:
        logger.warning("gTTS failed for %r: %s", word, exc)
