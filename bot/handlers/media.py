"""Media comprehension grading — /setmedia, /task, /results, /clearmedia (F-22)."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot import credits as credit_mod
from bot.middleware import require_auth
from db.repo import (
    get_active_media_task,
    get_class_by_id,
    get_media_submissions,
    get_user_by_telegram_id,
    close_media_task,
    create_media_task,
    upsert_media_submission,
)
from llm import prompts
from llm.errors import AllBackendsExhausted, LLMUnavailable, QuotaExceeded
from llm.router import Task
from llm.structured import generate_json

logger = logging.getLogger(__name__)

# ConversationHandler states for /setmedia wizard.
_SM_TITLE, _SM_URL, _SM_SUMMARY = range(3)

# context.user_data key holding wizard state.
_WIZ = "_setmedia_wiz"


def _is_teacher(user) -> bool:
    return getattr(user, "role", "student") in ("teacher", "superuser")


# ---------------------------------------------------------------------------
# /setmedia wizard (teacher)
# ---------------------------------------------------------------------------

@require_auth
async def setmedia_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/setmedia — start the media task wizard."""
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None or not _is_teacher(user):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return ConversationHandler.END

    context.user_data[_WIZ] = {"teacher_id": user.id, "class_id": user.class_id}
    await update.effective_message.reply_text(
        "📽 *New media task* — step 1/3\n\n"
        "Send a title for this task (e.g. 'Short film: La Boda, 4 min').\n\n"
        "/cancel to quit."
    )
    return _SM_TITLE


async def setmedia_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[_WIZ]["title"] = update.effective_message.text.strip()
    await update.effective_message.reply_text(
        "📽 *New media task* — step 2/3\n\n"
        "Send the URL or location where students can find the media "
        "(YouTube link, shared drive link, etc.).\n"
        "Type *skip* if there's no URL — students already have the file."
    )
    return _SM_URL


async def setmedia_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.effective_message.text.strip()
    context.user_data[_WIZ]["url"] = None if text.lower() == "skip" else text
    await update.effective_message.reply_text(
        "📽 *New media task* — step 3/3\n\n"
        "Send your *reference summary* — this is the answer key the bot grades against.\n"
        "Write it in the target language (4–8 sentences is ideal)."
    )
    return _SM_SUMMARY


async def setmedia_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    wiz = context.user_data.pop(_WIZ, {})
    reference = update.effective_message.text.strip()
    teacher_id = wiz.get("teacher_id")
    class_id = wiz.get("class_id")

    task_id = create_media_task(
        teacher_id=teacher_id,
        title=wiz.get("title", "Untitled"),
        reference_summary=reference,
        media_url=wiz.get("url"),
        class_id=class_id,
    )

    cls = get_class_by_id(class_id) if class_id else None
    scope = f"class *{cls.name}*" if cls else "your students"
    await update.effective_message.reply_text(
        f"✅ *Media task #{task_id} saved!*\n"
        f"Scope: {scope}\n\n"
        "Students can now send /task to see it and submit their summary."
    )
    return ConversationHandler.END


async def setmedia_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(_WIZ, None)
    await update.effective_message.reply_text("Media task cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /task — student submits summary
# ---------------------------------------------------------------------------

@require_auth
async def task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/task — show the active media task and accept a summary submission."""
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    en = getattr(user, "learning_mode", "german") == "english"

    task = get_active_media_task(class_id=user.class_id)
    if task is None:
        msg = (
            "No media task right now — check back later." if en
            else "Kein Medien-Auftrag gerade — komm später wieder."
        )
        await update.effective_message.reply_text(msg)
        return

    url_line = f"\n🔗 {task.media_url}" if task.media_url else ""
    if en:
        prompt_text = (
            f"📽 *{task.title}*{url_line}\n\n"
            "Watch/listen, then reply with your summary in English (4–6 sentences).\n"
            "I'll grade it and give you feedback."
        )
    else:
        prompt_text = (
            f"📽 *{task.title}*{url_line}\n\n"
            "Schau/hör dir das Material an und schreib dann eine Zusammenfassung auf Deutsch (4–6 Sätze).\n"
            "Ich bewerte sie und gebe dir Feedback."
        )

    context.user_data["_pending_media_task"] = task.id
    await update.effective_message.reply_text(prompt_text)


@require_auth
async def task_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain-text messages when a media task is pending for the user."""
    task_id = context.user_data.get("_pending_media_task")
    if task_id is None:
        return  # not waiting for a submission — let the chat handler deal with it

    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    en = getattr(user, "learning_mode", "german") == "english"

    submission = (update.effective_message.text or "").strip()
    if not submission:
        return

    task = get_active_media_task(class_id=user.class_id)
    if task is None or task.id != task_id:
        context.user_data.pop("_pending_media_task", None)
        return

    _credit_status = credit_mod.credits_check(user.id, credit_mod.COSTS["summary"])
    if _credit_status != "ok":
        _text, _kb = credit_mod.credit_error_response(en, _credit_status, user.id)
        await update.effective_message.reply_text(_text, reply_markup=_kb)
        return

    await update.effective_message.reply_text(
        "Grading your summary... ⏳" if en else "Bewertet deine Zusammenfassung... ⏳"
    )

    system = prompts.MEDIA_GRADE.format(
        reference=task.reference_summary,
        submission=submission,
    )

    try:
        result, _ = await generate_json(Task.assess, submission, system=system)
    except (QuotaExceeded, AllBackendsExhausted, LLMUnavailable):
        await update.effective_message.reply_text(
            "Grading failed — try again later." if en else "Bewertung fehlgeschlagen — versuch es später."
        )
        return

    if not result or not isinstance(result, dict):
        await update.effective_message.reply_text(
            "Couldn't grade this time — try again." if en else "Konnte nicht bewertet werden — versuch es nochmal."
        )
        return

    comp = int(result.get("comprehension") or 0)
    acc = int(result.get("accuracy") or 0)
    lang = int(result.get("language") or 0)
    total = comp + acc + lang
    fb_comp = result.get("feedback_comprehension") or ""
    fb_lang = result.get("feedback_language") or ""

    upsert_media_submission(
        task_id=task_id,
        student_id=user.id,
        submission_text=submission,
        score_comprehension=comp,
        score_accuracy=acc,
        score_language=lang,
        feedback=f"{fb_comp} {fb_lang}".strip(),
    )
    credit_mod.spend(user.id, task="summary", model="assess")
    context.user_data.pop("_pending_media_task", None)

    if en:
        reply = (
            f"📊 *Your score: {total}/10*\n"
            f"  Comprehension: {comp}/4\n"
            f"  Accuracy: {acc}/3\n"
            f"  Language: {lang}/3\n\n"
        )
        if fb_comp:
            reply += f"📖 *Content:* {fb_comp}\n"
        if fb_lang:
            reply += f"✍️ *Language:* {fb_lang}"
    else:
        reply = (
            f"📊 *Dein Ergebnis: {total}/10*\n"
            f"  Inhalt: {comp}/4\n"
            f"  Genauigkeit: {acc}/3\n"
            f"  Sprache: {lang}/3\n\n"
        )
        if fb_comp:
            reply += f"📖 *Inhalt:* {fb_comp}\n"
        if fb_lang:
            reply += f"✍️ *Sprache:* {fb_lang}"

    await update.effective_message.reply_text(reply)


# ---------------------------------------------------------------------------
# /results — teacher views all submissions
# ---------------------------------------------------------------------------

@require_auth
async def results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/results — show all student submissions for the active media task."""
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None or not _is_teacher(user):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return

    task = get_active_media_task(class_id=user.class_id, teacher_id=user.id)
    if task is None:
        await update.effective_message.reply_text("No active media task. Use /setmedia to create one.")
        return

    subs = get_media_submissions(task.id)
    if not subs:
        await update.effective_message.reply_text(
            f"📽 *{task.title}* — no submissions yet."
        )
        return

    lines = [f"📽 *{task.title}* — {len(subs)} submission(s)\n"]
    for s in subs:
        name = s["name"]
        total = s["total"] if s["total"] is not None else "?"
        lines.append(f"  {name}: *{total}/10*")
    await update.effective_message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# /clearmedia — teacher closes the task
# ---------------------------------------------------------------------------

@require_auth
async def clearmedia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/clearmedia — close the active media task."""
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None or not _is_teacher(user):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return

    task = get_active_media_task(class_id=user.class_id, teacher_id=user.id)
    if task is None:
        await update.effective_message.reply_text("No active media task to close.")
        return

    close_media_task(task.id)
    await update.effective_message.reply_text(
        f"✅ *{task.title}* closed. No more submissions accepted."
    )


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------

def build_setmedia_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setmedia", setmedia_start)],
        states={
            _SM_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, setmedia_title)],
            _SM_URL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, setmedia_url)],
            _SM_SUMMARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, setmedia_summary)],
        },
        fallbacks=[CommandHandler("cancel", setmedia_cancel)],
        name="setmedia",
        persistent=False,
    )
