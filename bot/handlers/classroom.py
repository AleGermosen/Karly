"""Teacher and superuser classroom commands.

Role hierarchy:
  superuser — approves students, assigns teachers, manages all
  teacher   — manages their own students/classes, sets topics, grants credits
  student   — regular learner

Commands by role:
  superuser only:   /addteacher, /removeteacher, /teachers
  teacher+super:    /students, /student, /class, /budget, /grant,
                    /newclass, /classes, /assign, /moveclass, /classtopic
  all:              /classtopic (read-only for students)

Approval callbacks (multi-step, DM to superuser):
  approve_s:<uid>:<mode>            — step 1: show teacher picker
  set_teacher_s:<uid>:<mode>:<tid>  — step 2: show class picker
  set_class_s:<uid>:<mode>:<tid>:<cid> — step 3: finalize
  decline_student:<uid>             — decline
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from bot.middleware import require_auth
from bot import credits as credit_mod
from db.repo import (
    approve_student,
    assign_student_class,
    assign_student_teacher,
    class_skill_error_rates,
    class_student_count,
    create_class,
    get_class_by_id,
    get_user_by_id,
    get_user_by_telegram_id,
    global_credits_used,
    grant_credits,
    latest_assessment,
    list_all_students,
    list_classes,
    list_students,
    list_students_by_teacher,
    list_students_for_teacher,
    list_students_in_class,
    list_teachers,
    log_broadcast,
    practice_streak,
    set_class_setting,
    set_class_topic,
    set_correction_level,
    set_placement_status,
    set_user_role,
    set_user_status,
    assign_unit,
    clear_assignment,
    set_unlimited_credits,
    student_last_active,
    top_credit_consumers,
    vocab_count,
    weekly_practice_count,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role helpers
# ---------------------------------------------------------------------------

def _is_superuser(user) -> bool:
    return (
        config.SUPERUSER_TELEGRAM_ID is not None
        and user is not None
        and user.telegram_id == config.SUPERUSER_TELEGRAM_ID
    )


def _is_teacher_or_above(user) -> bool:
    return user is not None and getattr(user, "role", "student") in ("teacher", "superuser")


def _caller(update: Update):
    return get_user_by_telegram_id(update.effective_user.id)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _time_ago(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    delta = datetime.utcnow() - dt
    if delta.days == 0:
        h = delta.seconds // 3600
        m = delta.seconds // 60
        if h >= 1:
            return f"{h}h ago"
        return f"{m}m ago" if m else "just now"
    return f"{delta.days}d ago"


def _status_icon(last_active: datetime | None, status: str) -> str:
    if status == "pending":
        return "⏳"
    if status == "removed":
        return "🚫"
    if last_active is None:
        return "🆕"
    delta = datetime.utcnow() - last_active
    if delta.days < 1:
        return "🟢"
    if delta.days < 7:
        return "🟡"
    return "🔴"


def _cefr_level(user) -> str:
    if user.cefr_estimate:
        try:
            data = json.loads(user.cefr_estimate)
            if isinstance(data, dict) and data.get("overall"):
                return str(data["overall"])
        except (ValueError, TypeError):
            pass
    return "—"


# ---------------------------------------------------------------------------
# /students
# ---------------------------------------------------------------------------

@require_auth
async def students(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return

    if _is_superuser(caller):
        roster = list_students(include_pending=True)
        header = "👥 *All students*"
    else:
        roster = list_students_for_teacher(caller.id, include_pending=True)
        header = "👥 *Your students*"

    if not roster:
        await update.effective_message.reply_text("No students yet.")
        return

    active = [s for s in roster if s.status == "active"]
    pending = [s for s in roster if s.status == "pending"]
    lines = [f"{header} — {len(active)} active, {len(pending)} pending\n"]

    for s in roster:
        last = student_last_active(s.id)
        icon = _status_icon(last, s.status)
        name = s.name or f"id={s.telegram_id}"
        level = _cefr_level(s)
        mode = "🇩🇪" if s.learning_mode == "german" else "🇺🇸"
        if s.status == "pending":
            lines.append(f"{icon} {name} {mode} — awaiting approval")
        else:
            streak = practice_streak(s.id)
            streak_txt = f" · 🔥{streak}d" if streak else ""
            class_txt = ""
            if s.class_id:
                cls = get_class_by_id(s.class_id)
                if cls:
                    class_txt = f" · {cls.name}"
            lines.append(f"{icon} {name} {mode} — {level}{class_txt} · {_time_ago(last)}{streak_txt}")

    lines.append("\n/student <name> for details.")
    await update.effective_message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# /student <name>
# ---------------------------------------------------------------------------

@require_auth
async def student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /student <name>")
        return

    query_name = " ".join(context.args).lower()
    if _is_superuser(caller):
        roster = list_students(include_pending=True)
    else:
        roster = list_students_for_teacher(caller.id, include_pending=True)

    matches = [s for s in roster if s.name and query_name in s.name.lower()]
    if not matches:
        await update.effective_message.reply_text(f"No student matching '{query_name}'.")
        return
    if len(matches) > 1:
        await update.effective_message.reply_text(
            "Multiple matches: " + ", ".join(s.name or "?" for s in matches) + "\nBe more specific."
        )
        return

    s = matches[0]
    last = student_last_active(s.id)
    verdict = latest_assessment(s.id)
    streak = practice_streak(s.id)
    cards = vocab_count(s.id)
    sessions = weekly_practice_count(s.id)
    mode = "English" if s.learning_mode == "english" else "German"

    lines = [f"👤 *{s.name}*\n"]
    lines.append(f"Mode: {mode} · Status: {s.status}")
    lines.append(f"Level: {_cefr_level(s)}")
    if s.class_id:
        cls = get_class_by_id(s.class_id)
        if cls:
            lines.append(f"Class: {cls.name}")
    if verdict and isinstance(verdict, dict):
        skills = verdict.get("skills") or {}
        if skills:
            lines.append("Skills: " + " · ".join(f"{k} {v}" for k, v in skills.items()))
        gaps = verdict.get("gaps") or []
        if gaps:
            lines.append("Gaps: " + ", ".join(gaps[:4]))
    lines.append(f"Last active: {_time_ago(last)}")
    lines.append(f"Streak: {streak} day(s) 🔥")
    lines.append(f"Saved cards: {cards}")
    lines.append(f"Practice sessions (7d): {sessions}")
    if s.joined_at:
        lines.append(f"Joined: {s.joined_at.strftime('%Y-%m-%d')}")

    await update.effective_message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# /class
# ---------------------------------------------------------------------------

@require_auth
async def class_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return

    if _is_superuser(caller):
        roster = list_students(include_pending=False)
        header = "📊 *Class — whole school*"
    else:
        roster = list_students_for_teacher(caller.id, include_pending=False)
        header = "📊 *Your class — weekly snapshot*"

    if not roster:
        await update.effective_message.reply_text("No active students yet.")
        return

    now = datetime.utcnow()
    active_week, inactive = [], []
    for s in roster:
        last = student_last_active(s.id)
        if last and (now - last).days < 7:
            active_week.append(s.name or f"id={s.telegram_id}")
        else:
            inactive.append((s.name or f"id={s.telegram_id}", _time_ago(last)))

    lines = [f"{header}\n"]
    lines.append(f"Active this week: {len(active_week)}/{len(roster)}")
    if active_week:
        lines.append("  " + ", ".join(active_week))
    if inactive:
        lines.append("\n⚠️ Inactive:")
        for name, when in inactive:
            lines.append(f"  • {name} — {when}")

    # Class breakdown (teacher's own classes).
    teacher_id = caller.id
    classes = list_classes(teacher_id)
    if classes:
        lines.append("\n📚 *Classes:*")
        for cls in classes:
            n = class_student_count(cls.id)
            topic_txt = f" · 📌 {cls.topic}" if cls.topic else ""
            lines.append(f"  • {cls.name} ({n} students){topic_txt}")

    # Skill error rates.
    rates = class_skill_error_rates()
    if rates:
        lines.append("\n📊 *Skill mastery (class average):*")
        for skill, data in sorted(rates.items(), key=lambda kv: kv[1]["mastery_avg"]):
            avg = data["mastery_avg"]
            struggling = data["struggling_pct"]
            bar = "█" * (avg // 10) + "░" * (10 - avg // 10)
            flag = " ⚠️" if struggling >= 50 else ""
            lines.append(
                f"  {skill.capitalize()}: {bar} {avg}% avg · {struggling}% struggling{flag}"
            )

    pending = [s for s in list_students(include_pending=True) if s.status == "pending"]
    if pending and _is_superuser(caller):
        lines.append(f"\n⏳ Pending approval: {len(pending)}")
        for s in pending:
            lines.append(f"  • {s.name or str(s.telegram_id)}")

    await update.effective_message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# /budget
# ---------------------------------------------------------------------------

@require_auth
async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return

    used = global_credits_used()
    full_limit = config.GLOBAL_DAILY_CREDIT_LIMIT
    effective_limit = credit_mod._global_limit_for_now()
    pct = round(used / full_limit * 100) if full_limit else 0
    alert = " ⚠️ HIGH" if pct >= 70 else ""
    reserve_note = (
        f" (75% reserve — full budget after {config.RESERVE_HOUR_UTC}:00 UTC)"
        if effective_limit < full_limit else ""
    )

    lines = ["📊 *Budget — today*\n"]
    lines.append(f"Global: *{used} / {effective_limit}* credits ({pct}%){alert}{reserve_note}")

    now = datetime.utcnow()
    if used > 0 and now.hour > 0:
        rate = used / now.hour
        remaining = effective_limit - used
        if rate > 0 and remaining > 0:
            lines.append(f"Projected: ~{remaining / rate:.1f}h until limit at current rate")

    lines.append(f"Per-student limit: {config.DAILY_CREDIT_LIMIT} credits/day (+streak bonus up to +5)")

    consumers = top_credit_consumers(5)
    if consumers:
        lines.append("\n🔝 *Top consumers today:*")
        for c in consumers:
            lines.append(f"  • {c['name']}: {c['credits']} credits")
    else:
        lines.append("\nNo credits spent yet today.")

    lines.append("\n/grant <name> <credits> to give a student extra credits.")
    await update.effective_message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# /grant
# ---------------------------------------------------------------------------

@require_auth
async def grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return
    if not context.args or len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /grant <student name> <credits>")
        return

    try:
        amount = int(context.args[-1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("Credits must be a positive whole number.")
        return

    name_query = " ".join(context.args[:-1]).lower()
    if _is_superuser(caller):
        roster = list_students(include_pending=False)
    else:
        roster = list_students_for_teacher(caller.id, include_pending=False)

    matches = [s for s in roster if s.name and name_query in s.name.lower()]
    if not matches:
        await update.effective_message.reply_text(f"No active student matching '{name_query}'.")
        return
    if len(matches) > 1:
        await update.effective_message.reply_text(
            "Multiple matches: " + ", ".join(s.name or "?" for s in matches)
        )
        return

    target = matches[0]
    grant_credits(target.id, granted_by=update.effective_user.id, amount=amount)
    try:
        await context.bot.send_message(
            chat_id=target.telegram_id,
            text=f"🎁 Your teacher gave you {amount} extra credits today. Keep going!",
        )
    except Exception:
        logger.exception("Could not notify student %s of grant", target.telegram_id)

    await update.effective_message.reply_text(
        f"✅ Granted *{amount}* extra credits to *{target.name}*."
    )


# ---------------------------------------------------------------------------
# /newclass <name>
# ---------------------------------------------------------------------------

@require_auth
async def newclass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /newclass <class name> [german|english]\n"
            "Example: /newclass A1 Beginners english"
        )
        return

    args = context.args
    if args[-1].lower() in ("german", "english"):
        mode = args[-1].lower()
        name = " ".join(args[:-1])
    else:
        mode = getattr(caller, "learning_mode", "german") or "german"
        name = " ".join(args)

    if not name:
        await update.effective_message.reply_text("Please provide a class name.")
        return

    cls = create_class(name=name, teacher_id=caller.id, learning_mode=mode)
    flag = "🇺🇸" if mode == "english" else "🇩🇪"
    await update.effective_message.reply_text(
        f"✅ Class *{cls.name}* {flag} created.\n"
        "Use /moveclass <student> <class> to assign students."
    )


# ---------------------------------------------------------------------------
# /classes
# ---------------------------------------------------------------------------

@require_auth
async def classes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return

    my_classes = list_classes(caller.id)
    if not my_classes:
        await update.effective_message.reply_text(
            "You have no classes yet. Use /newclass <name> to create one."
        )
        return

    lines = ["📚 *Your classes:*\n"]
    for cls in my_classes:
        n = class_student_count(cls.id)
        topic_txt = f"\n    📌 Topic: {cls.topic}" if cls.topic else ""
        lines.append(f"*{cls.name}* — {n} student(s){topic_txt}")

    lines.append("\n/assign <class> <topic> · /moveclass <student> <class>")
    await update.effective_message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# /assign <class name> <topic>  — or  /assign <topic> (all classes)
# ---------------------------------------------------------------------------

@require_auth
async def assign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return
    if not context.args:
        # Show current topics.
        my_classes = list_classes(caller.id)
        if not my_classes:
            await update.effective_message.reply_text(
                "You have no classes. Create one with /newclass first."
            )
            return
        lines = ["📌 *Current topics:*\n"]
        for cls in my_classes:
            lines.append(f"*{cls.name}*: {cls.topic or '(none)'}")
        lines.append("\n/assign <topic> — set for all classes")
        lines.append("/assign <class name>: <topic> — set for one class")
        lines.append("/assign clear — remove all topics")
        await update.effective_message.reply_text("\n".join(lines))
        return

    full = " ".join(context.args)

    if full.strip().lower() == "clear":
        for cls in list_classes(caller.id):
            set_class_topic(cls.id, None)
        await update.effective_message.reply_text("✅ All topics cleared.")
        return

    # Check for "ClassName: topic" syntax.
    my_classes = list_classes(caller.id)
    target_class = None
    topic = full
    if ":" in full:
        parts = full.split(":", 1)
        class_query = parts[0].strip().lower()
        topic = parts[1].strip()
        matches = [c for c in my_classes if class_query in c.name.lower()]
        if len(matches) == 1:
            target_class = matches[0]
        elif len(matches) > 1:
            await update.effective_message.reply_text(
                "Multiple class matches. Be more specific."
            )
            return

    if target_class:
        set_class_topic(target_class.id, topic)
        await update.effective_message.reply_text(
            f"✅ Topic set for *{target_class.name}*: *{topic}*\n"
            "Students in this class will drill this on /drill."
        )
    else:
        if not my_classes:
            await update.effective_message.reply_text(
                "You have no classes. Create one with /newclass first."
            )
            return
        for cls in my_classes:
            set_class_topic(cls.id, topic)
        await update.effective_message.reply_text(
            f"✅ Topic set for all your classes: *{topic}*\n"
            "Students will drill this on /drill."
        )


# ---------------------------------------------------------------------------
# /assignunit — teacher assigns a specific course unit to a student or class
# ---------------------------------------------------------------------------

@require_auth
async def assignunit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage:
      /assignunit <unit_id>                 → assign to all students in your classes
      /assignunit <unit_id> @username       → assign to one student
      /assignunit <unit_id> <class name>    → assign to a whole class
      /assignunit clear @username           → clear student assignment
      /assignunit clear <class name>        → clear class assignment
    """
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return

    args = context.args or []
    if not args:
        await update.effective_message.reply_text(
            "Usage:\n"
            "`/assignunit <unit_id>` — assign to all students in your classes\n"
            "`/assignunit <unit_id> @username` — assign to one student\n"
            "`/assignunit <unit_id> ClassName` — assign to a whole class\n"
            "`/assignunit clear @username` — clear assignment for a student\n"
            "`/assignunit clear ClassName` — clear assignment for a class",
            parse_mode="Markdown",
        )
        return

    unit_id = args[0].lower()
    target_str = " ".join(args[1:]).strip() if len(args) > 1 else ""

    # --- clear ---
    if unit_id == "clear":
        if not target_str:
            await update.effective_message.reply_text(
                "Specify a target: `/assignunit clear @username` or `/assignunit clear ClassName`",
                parse_mode="Markdown",
            )
            return
        if target_str.startswith("@"):
            handle = target_str.lstrip("@")
            student = get_user_by_telegram_id(
                next(
                    (s.telegram_id for s in list_students_for_teacher(caller.id)
                     if s.name and s.name.lower() == handle.lower()),
                    -1,
                )
            )
            if not student:
                # Try matching by name fragment
                matches = [s for s in list_students_for_teacher(caller.id)
                           if handle.lower() in (s.name or "").lower()]
                student = matches[0] if len(matches) == 1 else None
            if not student:
                await update.effective_message.reply_text("Student not found.")
                return
            n = clear_assignment(student_id=student.id)
            await update.effective_message.reply_text(f"✅ Assignment cleared for {student.name} ({n} removed).")
        else:
            my_classes = list_classes(caller.id)
            matches = [c for c in my_classes if target_str.lower() in c.name.lower()]
            if not matches:
                await update.effective_message.reply_text("Class not found.")
                return
            if len(matches) > 1:
                await update.effective_message.reply_text("Multiple class matches — be more specific.")
                return
            n = clear_assignment(class_id=matches[0].id)
            await update.effective_message.reply_text(f"✅ Assignment cleared for *{matches[0].name}* ({n} removed).", parse_mode="Markdown")
        return

    # --- validate unit exists ---
    from curriculum import loader as _loader
    unit = _loader.get_unit(unit_id)
    if unit is None:
        await update.effective_message.reply_text(
            f"Unit `{unit_id}` not found. Check spelling (e.g. `en.a1.g01`).",
            parse_mode="Markdown",
        )
        return

    # --- assign ---
    if not target_str:
        # Assign to all classes
        my_classes = list_classes(caller.id)
        if not my_classes:
            await update.effective_message.reply_text("You have no classes.")
            return
        for cls in my_classes:
            assign_unit(unit_id, caller.id, class_id=cls.id)
        names = ", ".join(c.name for c in my_classes)
        await update.effective_message.reply_text(
            f"✅ *{unit.title_target}* assigned to all your classes ({names}).\n"
            "Students will see it pinned at the top of `/course`.",
            parse_mode="Markdown",
        )
        return

    if target_str.startswith("@"):
        handle = target_str.lstrip("@")
        my_students = list_students_for_teacher(caller.id)
        matches = [s for s in my_students if handle.lower() in (s.name or "").lower()]
        if not matches:
            await update.effective_message.reply_text("Student not found.")
            return
        if len(matches) > 1:
            names = ", ".join(s.name for s in matches)
            await update.effective_message.reply_text(f"Multiple matches: {names}. Be more specific.")
            return
        student = matches[0]
        assign_unit(unit_id, caller.id, student_id=student.id)
        await update.effective_message.reply_text(
            f"✅ *{unit.title_target}* assigned to *{student.name}*.\n"
            "They'll see it pinned at the top of `/course`.",
            parse_mode="Markdown",
        )
        return

    # Class name
    my_classes = list_classes(caller.id)
    matches = [c for c in my_classes if target_str.lower() in c.name.lower()]
    if not matches:
        await update.effective_message.reply_text("Class not found.")
        return
    if len(matches) > 1:
        await update.effective_message.reply_text("Multiple class matches — be more specific.")
        return
    cls = matches[0]
    assign_unit(unit_id, caller.id, class_id=cls.id)
    await update.effective_message.reply_text(
        f"✅ *{unit.title_target}* assigned to *{cls.name}*.\n"
        "Students will see it pinned at the top of `/course`.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /classtopic  — students (and teachers) check their current topic
# ---------------------------------------------------------------------------

@require_auth
async def classtopic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    en = user and getattr(user, "learning_mode", "german") == "english"

    if _is_teacher_or_above(user):
        # Teachers see all their class topics.
        my_classes = list_classes(user.id)
        if not my_classes:
            await update.effective_message.reply_text("No classes yet. /newclass to create one.")
            return
        lines = ["📌 *Your class topics:*\n"]
        for cls in my_classes:
            lines.append(f"*{cls.name}*: {cls.topic or '(none)'}")
        await update.effective_message.reply_text("\n".join(lines))
        return

    # Student: show their class topic.
    if not user or not user.class_id:
        msg = (
            "You haven't been assigned to a class yet."
            if en else
            "Du bist noch keiner Klasse zugewiesen."
        )
        await update.effective_message.reply_text(msg)
        return

    cls = get_class_by_id(user.class_id)
    if not cls or not cls.topic:
        msg = (
            "Your class doesn't have a topic assigned yet."
            if en else
            "Deine Klasse hat noch kein Thema."
        )
        await update.effective_message.reply_text(msg)
        return

    msg = (
        f"📌 This week's topic: *{cls.topic}*\n\nUse /drill to practise it."
        if en else
        f"📌 Aktuelles Thema: *{cls.topic}*\n\nNutze /drill zum Üben."
    )
    await update.effective_message.reply_text(msg)


# ---------------------------------------------------------------------------
# /classsetcorr <class> <0-5>  — set default correction level for a class
# ---------------------------------------------------------------------------

_LEVEL_NAMES = {0: "off", 1: "gentle", 2: "light", 3: "balanced", 4: "thorough", 5: "exam"}


@require_auth
async def classsetcorr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/classsetcorr CLASS LEVEL — set default correction level for a class (teacher+).

    Applies to all students currently in that class. Students can still override
    their own level with /corrections at any time.
    """
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return
    if not context.args or len(context.args) < 2:
        await update.effective_message.reply_text(
            "Usage: /classsetcorr CLASS LEVEL\n"
            "Example: /classsetcorr Beginners 2\n\n"
            "Levels: 0=off  1=gentle  2=light  3=balanced  4=thorough  5=exam\n"
            "Students can always override with /corrections."
        )
        return

    raw_level = context.args[-1]
    if not raw_level.isdigit() or not (0 <= int(raw_level) <= 5):
        await update.effective_message.reply_text("Level must be 0–5.")
        return
    level = int(raw_level)
    class_query = " ".join(context.args[:-1]).lower()

    my_classes = list_classes(caller.id)
    matches = [c for c in my_classes if class_query in c.name.lower()]
    if not matches:
        await update.effective_message.reply_text(f"No class matching '{class_query}'. Use /classes to see yours.")
        return
    if len(matches) > 1:
        await update.effective_message.reply_text(
            "Multiple matches: " + ", ".join(c.name for c in matches) + ". Be more specific."
        )
        return

    target_class = matches[0]
    students = list_students_in_class(target_class.id)
    updated = 0
    for s in students:
        set_correction_level(s.id, level)
        updated += 1

    label = _LEVEL_NAMES.get(level, str(level))
    await update.effective_message.reply_text(
        f"✅ Correction level set to *{level} — {label}* for class *{target_class.name}* "
        f"({updated} student(s) updated).\n"
        "_Students can override this with /corrections at any time._"
    )


# ---------------------------------------------------------------------------
# /moveclass <student> <class>
# ---------------------------------------------------------------------------

@require_auth
async def moveclass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return
    if not context.args or len(context.args) < 2:
        await update.effective_message.reply_text(
            "Usage: /moveclass <student name> <class name>\n"
            "Example: /moveclass Ana A1 Beginners"
        )
        return

    # Last word(s) matched against class names, first word(s) against student name.
    # Try splitting at each position.
    my_classes = list_classes(caller.id)
    if not my_classes:
        await update.effective_message.reply_text("You have no classes. Create one with /newclass first.")
        return

    args = context.args
    target_class = None
    student_name_query = None

    for split in range(1, len(args)):
        class_query = " ".join(args[split:]).lower()
        cls_matches = [c for c in my_classes if class_query in c.name.lower()]
        if len(cls_matches) == 1:
            target_class = cls_matches[0]
            student_name_query = " ".join(args[:split]).lower()
            break

    if not target_class or not student_name_query:
        class_names = ", ".join(c.name for c in my_classes)
        await update.effective_message.reply_text(
            f"Couldn't parse. Your classes: {class_names}\n"
            "Usage: /moveclass <student> <class>"
        )
        return

    if _is_superuser(caller):
        roster = list_students(include_pending=False)
    else:
        roster = list_students_for_teacher(caller.id, include_pending=False)

    matches = [s for s in roster if s.name and student_name_query in s.name.lower()]
    if not matches:
        await update.effective_message.reply_text(f"No student matching '{student_name_query}'.")
        return
    if len(matches) > 1:
        await update.effective_message.reply_text(
            "Multiple matches: " + ", ".join(s.name or "?" for s in matches)
        )
        return

    target_student = matches[0]
    assign_student_class(target_student.id, target_class.id)
    await update.effective_message.reply_text(
        f"✅ *{target_student.name}* moved to class *{target_class.name}*."
    )


# ---------------------------------------------------------------------------
# /addteacher <name>  (superuser only)
# ---------------------------------------------------------------------------

@require_auth
async def addteacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_superuser(caller):
        await update.effective_message.reply_text("🚫 Superuser only.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /addteacher <student name>")
        return

    query = " ".join(context.args).lower()
    roster = list_students(include_pending=False)
    matches = [s for s in roster if s.name and query in s.name.lower()]
    if not matches:
        await update.effective_message.reply_text(
            f"No active student matching '{query}'.\n"
            "The person must have already started the bot."
        )
        return
    if len(matches) > 1:
        await update.effective_message.reply_text(
            "Multiple matches: " + ", ".join(s.name or "?" for s in matches)
        )
        return

    target = matches[0]
    set_user_role(target.id, "teacher")
    try:
        await context.bot.send_message(
            chat_id=target.telegram_id,
            text=(
                "👩‍🏫 You've been added as a teacher on Karly!\n"
                "Use /help to see your teacher commands.\n"
                "Create your first class with /newclass."
            ),
        )
    except Exception:
        logger.exception("Could not notify new teacher %s", target.telegram_id)

    await update.effective_message.reply_text(f"✅ *{target.name}* is now a teacher.")


# ---------------------------------------------------------------------------
# /removeteacher <name>  (superuser only)
# ---------------------------------------------------------------------------

@require_auth
async def removeteacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_superuser(caller):
        await update.effective_message.reply_text("🚫 Superuser only.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /removeteacher <name>")
        return

    query = " ".join(context.args).lower()
    teachers = list_teachers()
    # Exclude the superuser themselves.
    teachers = [t for t in teachers if not _is_superuser(t)]
    matches = [t for t in teachers if t.name and query in t.name.lower()]
    if not matches:
        await update.effective_message.reply_text(f"No teacher matching '{query}'.")
        return
    if len(matches) > 1:
        await update.effective_message.reply_text(
            "Multiple matches: " + ", ".join(t.name or "?" for t in matches)
        )
        return

    target = matches[0]
    set_user_role(target.id, "student")
    await update.effective_message.reply_text(f"✅ *{target.name}* demoted to student.")


# ---------------------------------------------------------------------------
# /grantunlimited <name> / /revokeunlimited <name>  (superuser only)
# ---------------------------------------------------------------------------

def _find_any_user(query: str):
    """Search all students (including pending) by name fragment."""
    roster = list_students(include_pending=True)
    q = query.lower()
    return [s for s in roster if s.name and q in s.name.lower()]


@require_auth
async def grantunlimited(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_superuser(caller):
        await update.effective_message.reply_text("🚫 Superuser only.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /grantunlimited <name>")
        return

    query = " ".join(context.args)
    matches = _find_any_user(query)
    if not matches:
        await update.effective_message.reply_text(
            f"No user matching '{query}'. They must have started the bot first."
        )
        return
    if len(matches) > 1:
        await update.effective_message.reply_text(
            "Multiple matches: " + ", ".join(s.name or "?" for s in matches)
        )
        return

    target = matches[0]
    set_unlimited_credits(target.id, True)
    await update.effective_message.reply_text(
        f"✅ *{target.name}* now has unlimited credits — no daily or session cap."
    )


@require_auth
async def revokeunlimited(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_superuser(caller):
        await update.effective_message.reply_text("🚫 Superuser only.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /revokeunlimited <name>")
        return

    query = " ".join(context.args)
    matches = _find_any_user(query)
    if not matches:
        await update.effective_message.reply_text(f"No user matching '{query}'.")
        return
    if len(matches) > 1:
        await update.effective_message.reply_text(
            "Multiple matches: " + ", ".join(s.name or "?" for s in matches)
        )
        return

    target = matches[0]
    set_unlimited_credits(target.id, False)
    await update.effective_message.reply_text(
        f"✅ *{target.name}* is back on the standard credit limits."
    )


# ---------------------------------------------------------------------------
# /teachers  (superuser only)
# ---------------------------------------------------------------------------

@require_auth
async def teachers_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = _caller(update)
    if not _is_superuser(caller):
        await update.effective_message.reply_text("🚫 Superuser only.")
        return

    all_teachers = list_teachers()
    if not all_teachers:
        await update.effective_message.reply_text("No teachers yet. /addteacher <name> to promote one.")
        return

    lines = ["👩‍🏫 *Teachers:*\n"]
    for t in all_teachers:
        role_label = "👑 superuser" if _is_superuser(t) else "teacher"
        my_classes = list_classes(t.id)
        student_count = sum(class_student_count(c.id) for c in my_classes)
        lines.append(
            f"*{t.name or str(t.telegram_id)}* ({role_label}) — "
            f"{len(my_classes)} class(es), {student_count} student(s)"
        )

    lines.append("\n/addteacher <name> · /removeteacher <name>")
    await update.effective_message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Approval callbacks (multi-step)
# ---------------------------------------------------------------------------

async def on_approve_student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Step 1 — superuser taps [✅ Approve]. Shows teacher picker."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    _, raw_id, mode = parts[0], parts[1], parts[2]
    user_db_id = int(raw_id)

    if not config.SUPERUSER_TELEGRAM_ID or update.effective_user.id != config.SUPERUSER_TELEGRAM_ID:
        await query.answer("Not authorized.", show_alert=True)
        return

    student_user = get_user_by_id(user_db_id)
    if student_user is None:
        await query.edit_message_text("⚠️ Student not found.")
        return
    if student_user.status == "active":
        await query.edit_message_text(f"ℹ️ {student_user.name or 'Student'} is already active.")
        return

    # Build teacher picker.
    all_teachers = list_teachers()
    buttons = []
    for t in all_teachers:
        label = f"👑 Me ({t.name})" if _is_superuser(t) else f"👩‍🏫 {t.name or str(t.telegram_id)}"
        buttons.append([InlineKeyboardButton(
            label, callback_data=f"set_teacher_s:{user_db_id}:{mode}:{t.id}"
        )])

    student_name = student_user.name or str(student_user.telegram_id)
    if len(all_teachers) == 1:
        # Only the superuser — skip teacher picker, go to class picker.
        superuser_user = all_teachers[0]
        await _show_class_picker(query, user_db_id, mode, superuser_user.id, student_name)
    else:
        await query.edit_message_text(
            f"✅ Approving *{student_name}* — assign to which teacher?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def _show_class_picker(query, user_db_id: int, mode: str, teacher_db_id: int, student_name: str) -> None:
    my_classes = list_classes(teacher_db_id)
    buttons = []
    for cls in my_classes:
        n = class_student_count(cls.id)
        buttons.append([InlineKeyboardButton(
            f"{cls.name} ({n})",
            callback_data=f"set_class_s:{user_db_id}:{mode}:{teacher_db_id}:{cls.id}"
        )])
    # "No class" option.
    buttons.append([InlineKeyboardButton(
        "No class yet",
        callback_data=f"set_class_s:{user_db_id}:{mode}:{teacher_db_id}:0"
    )])

    teacher = get_user_by_id(teacher_db_id)
    teacher_name = teacher.name if teacher else "?"
    await query.edit_message_text(
        f"Assign *{student_name}* to which class? (Teacher: {teacher_name})",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def on_set_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Step 2 — superuser picks a teacher. Shows class picker."""
    query = update.callback_query
    await query.answer()
    _, raw_id, mode, raw_tid = query.data.split(":")
    user_db_id, teacher_db_id = int(raw_id), int(raw_tid)

    if not config.SUPERUSER_TELEGRAM_ID or update.effective_user.id != config.SUPERUSER_TELEGRAM_ID:
        return

    student_user = get_user_by_id(user_db_id)
    student_name = student_user.name if student_user else "?"
    await _show_class_picker(query, user_db_id, mode, teacher_db_id, student_name)


async def on_set_class(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Step 3 — superuser picks a class. Finalizes approval."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    _, raw_id, mode, raw_tid, raw_cid = parts
    user_db_id, teacher_db_id, class_id_raw = int(raw_id), int(raw_tid), int(raw_cid)
    class_id = class_id_raw if class_id_raw != 0 else None

    if not config.SUPERUSER_TELEGRAM_ID or update.effective_user.id != config.SUPERUSER_TELEGRAM_ID:
        return

    student_user = get_user_by_id(user_db_id)
    if student_user is None:
        await query.edit_message_text("⚠️ Student not found.")
        return

    approve_student(user_db_id, approved_by=update.effective_user.id, mode=mode)
    assign_student_teacher(user_db_id, teacher_db_id)
    if class_id:
        assign_student_class(user_db_id, class_id)

    teacher = get_user_by_id(teacher_db_id)
    cls = get_class_by_id(class_id) if class_id else None
    student_name = student_user.name or str(student_user.telegram_id)
    lang_label = "German" if mode == "german" else "English"
    class_label = f" → {cls.name}" if cls else ""

    # Welcome the student with a structured onboarding message.
    first_name = (student_user.name or "").split()[0] or "there"
    class_line = f"\n📚 Class: *{cls.name}*" if cls else ""
    if mode == "german":
        welcome = (
            f"✅ *Willkommen bei Karly, {first_name}!*\n"
            f"Dein Lehrer hat dich freigeschaltet.{class_line}\n\n"
            "Hier sind deine ersten Schritte:\n\n"
            "1️⃣ */test* — mach den Einstufungstest (~10 Fragen)\n"
            "2️⃣ Schreib mir einfach auf Deutsch — ich korrigiere dich\n"
            "3️⃣ */practice* — Vokabeln mit Karteikarten üben\n"
            "4️⃣ */daily* — tägliche Mini-Challenge (3 kurze Aufgaben)\n\n"
            "ℹ️ Dein Lehrer kann deinen Fortschritt sehen (Level, Aktivität, Fehler-Schwerpunkte).\n\n"
            "/help zeigt alle Commands."
        )
    else:
        welcome = (
            f"✅ *Welcome to Karly, {first_name}!*\n"
            f"Your teacher has approved you.{class_line}\n\n"
            "Your first steps:\n\n"
            "1️⃣ */test* — take the placement test (~10 questions)\n"
            "2️⃣ Write to me in English — I'll correct and explain\n"
            "3️⃣ */practice* — practise vocabulary with flashcards\n"
            "4️⃣ */daily* — daily mini-challenge (3 short exercises)\n\n"
            "ℹ️ Your teacher can see your progress (level, activity, weak areas).\n\n"
            "/help shows all commands."
        )
    try:
        await context.bot.send_message(chat_id=student_user.telegram_id, text=welcome)
        await send_placement_prompt(context.bot, student_user)
    except Exception:
        logger.exception("Could not notify student %s of approval", student_user.telegram_id)

    # Notify the assigned teacher (if not the superuser).
    if teacher and not _is_superuser(teacher):
        try:
            await context.bot.send_message(
                chat_id=teacher.telegram_id,
                text=(
                    f"👤 *{student_name}* has been assigned to you{class_label}.\n"
                    f"Mode: {lang_label}. Use /students to see your roster."
                ),
            )
        except Exception:
            logger.exception("Could not notify teacher %s", teacher.telegram_id)

    teacher_name = teacher.name if teacher else "?"
    await query.edit_message_text(
        f"✅ *{student_name}* approved ({lang_label})"
        f" → {teacher_name}{class_label}"
    )


async def on_decline_student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, raw_id = query.data.split(":")
    user_db_id = int(raw_id)

    if not config.SUPERUSER_TELEGRAM_ID or update.effective_user.id != config.SUPERUSER_TELEGRAM_ID:
        return

    student_user = get_user_by_id(user_db_id)
    if student_user is None:
        await query.edit_message_text("⚠️ Student not found.")
        return

    set_user_status(user_db_id, "removed")
    student_name = student_user.name or str(student_user.telegram_id)
    await query.edit_message_text(f"❌ Declined: *{student_name}*")


# ---------------------------------------------------------------------------
# F-18 — /broadcast: teacher messages to class or all students
# ---------------------------------------------------------------------------

_BROADCAST_DELAY = 0.05  # 50 ms between sends — well within Telegram's 30 msg/s limit


@require_auth
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/broadcast [class] message — send a message to students."""
    import asyncio

    caller = _caller(update)
    if not _is_teacher_or_above(caller):
        await update.effective_message.reply_text("🚫 Teacher only.")
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage:\n"
            "/broadcast *message* — all your students\n"
            "/broadcast *ClassName* *message* — one class\n"
            "Superuser: /broadcast all *message* — every student"
        )
        return

    raw = " ".join(context.args)
    first = context.args[0].lower()

    # Determine recipients.
    if first == "all" and _is_superuser(caller):
        recipients = list_all_students()
        scope_label = "all students"
        class_id = None
        message_text = raw[len("all"):].strip()
    else:
        my_classes = list_classes(caller.id)
        match = next((c for c in my_classes if raw.lower().startswith(c.name.lower())), None)
        if match:
            message_text = raw[len(match.name):].strip()
            recipients = list_students_in_class(match.id)
            scope_label = f"class *{match.name}*"
            class_id = match.id
        else:
            recipients = list_students_by_teacher(caller.id)
            scope_label = "all your students"
            message_text = raw
            class_id = None

    if not message_text:
        await update.effective_message.reply_text("Message text cannot be empty.")
        return

    n = len(recipients)
    if n == 0:
        await update.effective_message.reply_text("No students found to message.")
        return

    # Confirmation step via inline buttons stored in context.
    context.user_data["_broadcast_pending"] = {
        "recipients": [u.telegram_id for u in recipients],
        "message_text": message_text,
        "scope_label": scope_label,
        "class_id": class_id,
    }
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Send to {n} student(s)", callback_data="broadcast:confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="broadcast:cancel"),
        ]
    ])
    await update.effective_message.reply_text(
        f"Send this to *{n}* student(s) in {scope_label}?\n\n_{message_text}_",
        reply_markup=kb,
    )


async def on_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle broadcast confirm/cancel inline buttons."""
    import asyncio

    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]
    pending = context.user_data.pop("_broadcast_pending", None)

    if action == "cancel" or pending is None:
        await query.edit_message_text("Broadcast cancelled.")
        return

    telegram_ids = pending["recipients"]
    message_text = pending["message_text"]
    sent = 0
    blocked = 0
    for tid in telegram_ids:
        try:
            await context.bot.send_message(chat_id=tid, text=message_text)
            sent += 1
        except Exception:
            blocked += 1
        await asyncio.sleep(_BROADCAST_DELAY)

    caller = _caller(update)
    log_broadcast(
        teacher_id=caller.id,
        message_text=message_text,
        recipient_count=sent,
        class_id=pending.get("class_id"),
    )
    summary = f"📤 Sent to *{sent}* student(s)."
    if blocked:
        summary += f" _{blocked} could not be reached (blocked or deactivated)._"
    await query.edit_message_text(summary)


# ---------------------------------------------------------------------------
# F-19 — placement prompt sent right after approval
# ---------------------------------------------------------------------------

async def send_placement_prompt(bot, student: "User") -> None:
    """Send the placement quiz offer to a newly approved student."""
    set_placement_status(student.id, "pending")
    mode = getattr(student, "learning_mode", "german")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Start now", callback_data=f"placement:start:{student.id}")],
        [InlineKeyboardButton("⏰ Later", callback_data=f"placement:later:{student.id}")],
        [InlineKeyboardButton("📋 I know my level", callback_data=f"placement:skip:{student.id}")],
    ])
    if mode == "german":
        text = (
            "🎯 *Einstufungstest*\n\n"
            "Bevor wir anfangen — möchtest du einen kurzen Einstufungstest machen? (~5 Minuten)\n"
            "Das hilft mir, das richtige Level für dich zu setzen."
        )
    else:
        text = (
            "🎯 *Placement quiz*\n\n"
            "Before we start — would you like a quick placement quiz? (~5 minutes)\n"
            "It helps me set the right level for you."
        )
    try:
        await bot.send_message(chat_id=student.telegram_id, text=text, reply_markup=kb)
    except Exception:
        logger.exception("Could not send placement prompt to %s", student.telegram_id)


async def on_placement_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle placement quiz option buttons."""
    query = update.callback_query
    await query.answer()
    _, action, raw_id = query.data.split(":")
    user_db_id = int(raw_id)

    user = get_user_by_id(user_db_id)
    if user is None:
        return
    mode = getattr(user, "learning_mode", "german")
    en = mode == "english"

    if action == "start":
        set_placement_status(user_db_id, "pending")
        await query.edit_message_text(
            "Perfect! Send /test to begin." if en else "Super! Schick /test um zu beginnen."
        )
    elif action == "later":
        context.user_data["_placement_remind"] = True
        await query.edit_message_text(
            "No problem — I'll remind you next time you write to me." if en
            else "Kein Problem — ich erinnere dich beim nächsten Mal."
        )
    elif action == "skip":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(lvl, callback_data=f"placement_level:{user_db_id}:{lvl}")
            for lvl in ["A1", "A2", "B1"]
        ], [
            InlineKeyboardButton(lvl, callback_data=f"placement_level:{user_db_id}:{lvl}")
            for lvl in ["B2", "C1"]
        ]])
        await query.edit_message_text(
            "Choose your level:" if en else "Level auswählen:", reply_markup=kb
        )


async def on_placement_level_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle manual level selection from the placement skip flow."""
    from db.repo import save_assessment

    query = update.callback_query
    await query.answer()
    _, raw_id, level = query.data.split(":")
    user_db_id = int(raw_id)

    user = get_user_by_id(user_db_id)
    if user is None:
        return
    en = getattr(user, "learning_mode", "german") == "english"

    save_assessment(user_db_id, {"overall": level, "gaps": []}, "[]")
    set_placement_status(user_db_id, "skipped")

    await query.edit_message_text(
        f"✅ Level set to *{level}*. Let's go!" if en
        else f"✅ Level auf *{level}* gesetzt. Los geht's!"
    )
