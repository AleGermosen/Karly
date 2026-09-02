"""/assess — adaptive placement interview ending in a JSON verdict.

Implemented as a ConversationHandler. The interview transcript lives in
context.user_data during the session. After enough exchanges the model produces
a strict-JSON verdict, which is stored and used to update the user's level.
"""
from __future__ import annotations

import json
import logging

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.middleware import require_auth
from db.repo import get_user_by_telegram_id, save_assessment
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task, route
from llm.structured import generate_json

logger = logging.getLogger(__name__)

ASSESSING = 1
MIN_EXCHANGES = 10
MAX_EXCHANGES = 15

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏 (Gemini quota reached.)"
ERROR_MSG = "Da ging etwas schief bei der Einstufung. Versuch es später mit /test."


def _transcript_text(transcript: list[dict]) -> str:
    lines = []
    for t in transcript:
        who = "KARLY" if t["role"] == "assistant" else "AJ"
        lines.append(f"{who}: {t['text']}")
    return "\n".join(lines)


async def _next_item(transcript: list[dict]) -> str:
    prompt = (
        "Interview transcript so far:\n"
        + (_transcript_text(transcript) or "(none yet — this is the first item)")
        + "\n\nGive the next interview item."
    )
    return await route(Task.assess, prompt, system=prompts.ASSESS_INTERVIEW)


@require_auth
async def assess_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["assess_transcript"] = []
    context.user_data["assess_count"] = 0
    await update.effective_message.reply_text(
        "Los geht's — kurze Einstufung (~10-15 Fragen). Antworte auf Deutsch, "
        "so gut du kannst. /cancel bricht ab.\n(Starting your placement — "
        "answer in German; /cancel to stop.)"
    )
    try:
        item = await _next_item([])
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        return ConversationHandler.END
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
        return ConversationHandler.END

    context.user_data["assess_transcript"].append({"role": "assistant", "text": item})
    await update.effective_message.reply_text(item)
    return ASSESSING


@require_auth
async def assess_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    transcript: list[dict] = context.user_data.get("assess_transcript", [])
    answer = (update.effective_message.text or "").strip()
    transcript.append({"role": "user", "text": answer})
    context.user_data["assess_count"] = context.user_data.get("assess_count", 0) + 1
    count = context.user_data["assess_count"]

    await context.bot.send_chat_action(
        chat_id=update.effective_message.chat_id, action="typing"
    )

    if count >= MAX_EXCHANGES:
        return await _finish(update, context, transcript)

    try:
        item = await _next_item(transcript)
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        return ConversationHandler.END
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
        return ConversationHandler.END

    transcript.append({"role": "assistant", "text": item})

    # Offer an early exit once past the minimum.
    if count == MIN_EXCHANGES:
        await update.effective_message.reply_text(
            "(Fast fertig — noch ein paar Fragen, oder /done für die Auswertung.)"
        )
    await update.effective_message.reply_text(item)
    return ASSESSING


@require_auth
async def assess_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    transcript: list[dict] = context.user_data.get("assess_transcript", [])
    if context.user_data.get("assess_count", 0) < 3:
        await update.effective_message.reply_text(
            "Beantworte bitte noch ein paar Fragen zuerst. (A few more first.)"
        )
        return ASSESSING
    return await _finish(update, context, transcript)


async def _finish(
    update: Update, context: ContextTypes.DEFAULT_TYPE, transcript: list[dict]
) -> int:
    await update.effective_message.reply_text(
        "Danke! Ich werte deine Antworten aus… (Scoring your answers…)"
    )
    prompt = (
        "Full interview transcript:\n"
        + _transcript_text(transcript)
        + "\n\nProduce the verdict JSON."
    )
    try:
        verdict, raw = await generate_json(
            Task.assess, prompt, system=prompts.ASSESS_VERDICT
        )
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        return ConversationHandler.END
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
        return ConversationHandler.END

    user = get_user_by_telegram_id(update.effective_user.id)
    if not isinstance(verdict, dict):
        # Defensive fallback: store raw text so nothing is lost.
        logger.warning("Verdict was not valid JSON; storing raw.")
        if user:
            save_assessment(
                user.id, {"overall": None, "raw": raw, "gaps": []}, transcript
            )
        await update.effective_message.reply_text(
            "Ich konnte die Auswertung nicht sauber strukturieren, aber hier ist "
            "meine Einschätzung:\n\n" + raw[:1500]
        )
        _clear(context)
        return ConversationHandler.END

    if user:
        save_assessment(user.id, verdict, transcript)

    await update.effective_message.reply_text(_format_verdict(verdict))
    _clear(context)
    return ConversationHandler.END


def _format_verdict(v: dict) -> str:
    skills = v.get("skills") or {}
    skill_lines = "\n".join(
        f"  • {k.capitalize()}: {val}" for k, val in skills.items()
    )
    gaps = v.get("gaps") or []
    gap_lines = "\n".join(f"  • {g}" for g in gaps)
    parts = [f"📊 *Einstufung fertig!*\n\nOverall: *{v.get('overall', '?')}*"]
    if skill_lines:
        parts.append("\nPer skill:\n" + skill_lines)
    if gap_lines:
        parts.append("\nGaps to work on:\n" + gap_lines)
    if v.get("summary"):
        parts.append("\n" + v["summary"])
    parts.append("\nSieh dir /profile an. Jetzt einfach drauflos schreiben!")
    return "\n".join(parts)


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("assess_transcript", None)
    context.user_data.pop("assess_count", None)


@require_auth
async def assess_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear(context)
    await update.effective_message.reply_text(
        "Einstufung abgebrochen. (Assessment cancelled.)"
    )
    return ConversationHandler.END


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler(["test", "assess"], assess_start)],
        states={
            ASSESSING: [
                CommandHandler("done", assess_done),
                CommandHandler("cancel", assess_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, assess_answer),
            ]
        },
        fallbacks=[CommandHandler("cancel", assess_cancel)],
        name="assessment",
    )
