"""/remind — optional daily practice reminder (Phase 3 🔀 option).

Default is OFF. `/remind 19:30` schedules a daily nudge; `/remind off` cancels;
`/remind` alone shows the current setting. Times are in the server's local
timezone. Reminder settings persist in the DB and are re-scheduled on startup.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

from telegram import Update
from telegram.ext import Application, ContextTypes

from bot.middleware import require_auth
from db.repo import (
    count_due,
    get_user_by_telegram_id,
    set_reminder,
    users_with_reminders,
)

logger = logging.getLogger(__name__)

_TIME_RE = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})$")
_LOCAL_TZ = dt.datetime.now().astimezone().tzinfo


def _job_name(telegram_id: int) -> str:
    return f"reminder:{telegram_id}"


def _cancel_jobs(app: Application, telegram_id: int) -> None:
    if app.job_queue is None:
        return
    for job in app.job_queue.get_jobs_by_name(_job_name(telegram_id)):
        job.schedule_removal()


def _schedule(app: Application, telegram_id: int, hhmm: str) -> None:
    if app.job_queue is None:
        logger.warning("No job queue available; cannot schedule reminder.")
        return
    h, m = (int(x) for x in hhmm.split(":"))
    _cancel_jobs(app, telegram_id)
    app.job_queue.run_daily(
        _send_reminder,
        time=dt.time(hour=h, minute=m, tzinfo=_LOCAL_TZ),
        name=_job_name(telegram_id),
        data={"telegram_id": telegram_id},
    )
    logger.info("Scheduled daily reminder for %s at %s", telegram_id, hhmm)


async def _send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = context.job.data["telegram_id"]
    user = get_user_by_telegram_id(telegram_id)
    if user is None:
        return
    due = count_due(user.id)
    if due > 0:
        text = f"⏰ Zeit zum Üben! {due} Vokabeln sind fällig. /practice 💪"
    else:
        text = "⏰ Zeit für etwas Deutsch! Schreib mir was oder mach /practice. 🇩🇪"
    await context.bot.send_message(chat_id=telegram_id, text=text)


@require_auth
async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    arg = " ".join(context.args).strip().lower() if context.args else ""

    if not arg:
        current = user.reminder_time
        if current:
            await update.effective_message.reply_text(
                f"Tägliche Erinnerung: *{current}* Uhr.\n"
                "/remind off zum Ausschalten, /remind HH:MM zum Ändern."
            )
        else:
            await update.effective_message.reply_text(
                "Keine Erinnerung gesetzt. /remind HH:MM aktiviert eine tägliche "
                "Erinnerung (z.B. /remind 19:30)."
            )
        return

    if arg in ("off", "aus", "none", "stop"):
        set_reminder(user.id, None)
        _cancel_jobs(context.application, user.telegram_id)
        await update.effective_message.reply_text("Erinnerung ausgeschaltet. (Off.)")
        return

    match = _TIME_RE.match(arg)
    if not match or not (0 <= int(match["h"]) < 24) or not (0 <= int(match["m"]) < 60):
        await update.effective_message.reply_text(
            "Format: /remind HH:MM (z.B. /remind 19:30) oder /remind off."
        )
        return

    hhmm = f"{int(match['h']):02d}:{int(match['m']):02d}"
    set_reminder(user.id, hhmm)
    _schedule(context.application, user.telegram_id, hhmm)
    await update.effective_message.reply_text(
        f"Alles klar — ich erinnere dich täglich um *{hhmm}* Uhr. ⏰"
    )


async def reschedule_all(app: Application) -> None:
    """On startup, re-create daily jobs from stored reminder settings."""
    for _user_id, telegram_id, hhmm in users_with_reminders():
        if hhmm:
            _schedule(app, telegram_id, hhmm)
