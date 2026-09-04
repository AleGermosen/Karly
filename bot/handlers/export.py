"""/export — teacher downloads a CSV of their students' progress.

Columns: Name, Telegram ID, Status, Class, Level, Streak (days),
         Last Active, Cards Saved, Sessions (7d), Weak Skills
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from bot.middleware import require_auth
from db.repo import (
    get_class_by_id,
    get_user_by_telegram_id,
    latest_assessment,
    list_students,
    list_students_for_teacher,
    practice_streak,
    student_last_active,
    vocab_count,
    weekly_practice_count,
)

logger = logging.getLogger(__name__)


def _time_ago(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    delta = datetime.utcnow() - dt
    if delta.days == 0:
        h = delta.seconds // 3600
        return f"{h}h ago" if h else "today"
    return f"{delta.days}d ago"


def _cefr(user) -> str:
    if not user.cefr_estimate:
        return ""
    try:
        data = json.loads(user.cefr_estimate)
        if isinstance(data, dict):
            return str(data.get("overall", ""))
    except (ValueError, TypeError):
        pass
    return ""


def _weak_skills(user) -> str:
    verdict = latest_assessment(user.id)
    if not isinstance(verdict, dict):
        return ""
    gaps = verdict.get("gaps") or []
    return "; ".join(gaps[:3])


def _build_csv(students) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Name", "Telegram ID", "Status", "Mode", "Class",
        "Level", "Streak (days)", "Last Active", "Cards Saved",
        "Sessions (7d)", "Weak Skills",
    ])
    for s in students:
        last = student_last_active(s.id)
        cls = get_class_by_id(s.class_id) if s.class_id else None
        writer.writerow([
            s.name or "",
            s.telegram_id,
            s.status,
            getattr(s, "learning_mode", "german"),
            cls.name if cls else "",
            _cefr(s),
            practice_streak(s.id),
            _time_ago(last),
            vocab_count(s.id),
            weekly_practice_count(s.id),
            _weak_skills(s),
        ])
    return buf.getvalue().encode("utf-8-sig")  # utf-8-sig = Excel-friendly BOM


@require_auth
async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/export — download a CSV of your students' progress."""
    from bot.handlers.classroom import _is_teacher_or_above, _is_superuser, _caller
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return

    if _is_superuser(caller):
        students = list_students(include_pending=True)
        filename = "karly-all-students.csv"
    else:
        students = list_students_for_teacher(caller.id, include_pending=True)
        filename = "karly-my-students.csv"

    if not students:
        await update.effective_message.reply_text("No students yet.")
        return

    await update.effective_message.reply_text("⏳ Building CSV…")
    try:
        data = _build_csv(students)
    except Exception:
        logger.exception("CSV export failed")
        await update.effective_message.reply_text("Export failed — try again.")
        return

    stamp = datetime.utcnow().strftime("%Y-%m-%d")
    await update.effective_message.reply_document(
        document=io.BytesIO(data),
        filename=f"{stamp}-{filename}",
        caption=f"📊 {len(students)} student(s) · {stamp}",
    )
