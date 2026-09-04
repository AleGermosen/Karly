"""/addword — add a word to the student's personal flashcard deck (F-17)."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import credits as credit_mod
from bot.middleware import require_auth
from db.repo import add_personal_word, find_personal_word, get_user_by_telegram_id
from llm import prompts
from llm.errors import AllBackendsExhausted, LLMUnavailable, QuotaExceeded
from llm.router import Task
from llm.structured import generate_json

logger = logging.getLogger(__name__)


@require_auth
async def addword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addword <word> — look up a word and add it to your personal flashcard deck."""
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    en = getattr(user, "learning_mode", "german") == "english"

    word = " ".join(context.args).strip() if context.args else ""
    if not word:
        if en:
            await update.effective_message.reply_text(
                "Usage: /addword *word*\nExample: /addword therefore"
            )
        else:
            await update.effective_message.reply_text(
                "Verwendung: /addword *Wort*\nBeispiel: /addword Schadenfreude"
            )
        return

    if find_personal_word(user.id, word):
        if en:
            await update.effective_message.reply_text(
                f"_{word}_ is already in your deck — great word to keep practicing! /practice to review."
            )
        else:
            await update.effective_message.reply_text(
                f"_{word}_ ist schon in deinem Deck — weiter üben! /practice zum Wiederholen."
            )
        return

    _credit_status = credit_mod.credits_check(user.id, credit_mod.COSTS["explain"])
    if _credit_status != "ok":
        _text, _kb = credit_mod.credit_error_response(en, _credit_status, user.id)
        await update.effective_message.reply_text(_text, reply_markup=_kb)
        return

    lang_pair = "English-Spanish" if en else "German-English"
    system = prompts.ADDWORD_LOOKUP.format(lang_pair=lang_pair)

    try:
        result, _ = await generate_json(Task.lookup, word, system=system)
    except (QuotaExceeded, AllBackendsExhausted):
        msg = "Daily limit reached — try again later." if en else "Tageslimit erreicht — versuch es später."
        await update.effective_message.reply_text(msg)
        return
    except LLMUnavailable:
        msg = "Sorry, something went wrong." if en else "Entschuldigung, da ging etwas schief."
        await update.effective_message.reply_text(msg)
        return

    if not result or not isinstance(result, dict):
        msg = "Couldn't look up that word — try again." if en else "Das Wort konnte nicht gefunden werden."
        await update.effective_message.reply_text(msg)
        return

    canonical = result.get("word") or word
    pos = result.get("part_of_speech") or ""
    definition = result.get("definition") or ""
    example = result.get("example") or ""

    if not definition:
        msg = "Couldn't find a definition — check the spelling and try again." if en else "Keine Definition gefunden — bitte Schreibweise prüfen."
        await update.effective_message.reply_text(msg)
        return

    add_personal_word(user.id, canonical, definition, example, pos)
    credit_mod.spend(user.id, task="explain", model="lookup")

    if en:
        card = (
            f"✅ *{canonical}* _({pos})_\n"
            f"{definition}\n\n"
            f"_{example}_\n\n"
            "Added to your vocabulary deck. /practice to review it."
        )
    else:
        card = (
            f"✅ *{canonical}* _({pos})_\n"
            f"{definition}\n\n"
            f"_{example}_\n\n"
            "Zu deinem Vokabeldeck hinzugefügt. /practice zum Üben."
        )
    await update.effective_message.reply_text(card)
