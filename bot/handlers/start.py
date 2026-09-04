"""/start, /help, /profile, /language command handlers."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from bot.middleware import require_auth
from db.repo import (
    count_due,
    get_bkt_state,
    get_user_by_telegram_id,
    latest_assessment,
    set_language_chosen,
    set_learning_mode,
    vocab_count,
)
from srs import bkt as bkt_mod

logger = logging.getLogger(__name__)

WELCOME_GERMAN = (
    "Hallo! Ich bin Karly, dein Deutsch-Tutor. 🇩🇪\n\n"
    "Schreib mir einfach auf Deutsch — ich antworte und korrigiere dich.\n\n"
    "Wichtigste Commands:\n"
    "/practice — Karteikarten üben (auch /flashcards)\n"
    "/daily — Mini-Challenge (3 kurze Aufgaben)\n"
    "/quiz — Schnell-Quiz auf deine schwächsten Skills\n"
    "/roleplay — Rollenspiel-Szene auf Deutsch\n"
    "/test — Einstufungstest\n"
    "/profile — dein Lernprofil\n"
    "/weekly — Wochenbericht\n\n"
    "/help — alle Commands"
)

WELCOME_ENGLISH = (
    "Hello! I'm Karly, your English tutor. 🇺🇸\n\n"
    "Write to me in English — I'll reply and correct you.\n\n"
    "Main commands:\n"
    "/practice — vocabulary flashcards (also /flashcards)\n"
    "/daily — daily challenge: 3 short exercises\n"
    "/quiz — quick quiz on your weakest skills\n"
    "/roleplay — conversation scene in English\n"
    "/test — adaptive placement test\n"
    "/profile — your learning profile\n"
    "/weekly — weekly progress report\n"
    "/docs — practice from a PDF\n"
    "🎭 /impostor — social deduction game for the class\n\n"
    "/help — all commands"
)

LANGUAGE_PICKER = (
    "¡Hola! / Hello! 👋\n\n"
    "¿Qué idioma quieres aprender? / What do you want to learn?"
)

_PICKER_KB = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("🇩🇪 Deutsch lernen", callback_data="lang:german"),
        InlineKeyboardButton("🇺🇸 Learn English", callback_data="lang:english"),
    ]
])

HELP_GERMAN = (
    "Karly — dein Deutsch-Tutor.\n"
    "Schreib einfach auf Deutsch; ich korrigiere dich. Alle Commands:\n\n"

    "── Lernen ──\n"
    "/practice — Karteikarten (auch /flashcards): Deck & Richtung wählen\n"
    "/flip — DE↔EN Richtung wechseln (während /practice)\n"
    "/daily — Mini-Challenge: Lückentext + Übersetzen + Antworten\n"
    "/quiz — 7 MCQ auf deine schwächsten Skills\n"
    "/roleplay — Rollenspiel-Szene: Szene wählen, /done für Feedback\n"
    "/test — adaptiver Einstufungstest (~10 Fragen); /done früher, /cancel abbrechen\n\n"

    "── Profil & Statistik ──\n"
    "/profile — Level, Skill-Mastery, fällige Karten\n"
    "/review — Streak, fällige Karten, schwerste Vokabeln\n"
    "/weekly — Wochenbericht: Sessions, Genauigkeit, Korrekturen, Mastery\n"
    "/summary — deine Fehler auswerten + zum Üben speichern\n\n"

    "── Gesprächs-Tools ──\n"
    "/corrections strict|relaxed|off — Korrektur-Level setzen (kein Arg = Status)\n"
    "/topic <Thema> — Gespräch auf ein Thema lenken (/topic clear zum Löschen)\n"
    "/english <Frage> — Meta-Frage auf Englisch stellen\n"
    "/remind HH:MM — tägliche Erinnerung setzen (/remind off zum Ausschalten)\n\n"

    "── Dokumente ──\n"
    "/docs — deine hochgeladenen PDFs\n"
    "/learn <id> — Lektion aus einem Dokument starten\n"
    "/docfocus on|off — Gespräch aufs neueste Dokument lenken\n"
    "📄 Schick eine deutsche PDF → Fachbegriffe werden automatisch extrahiert\n\n"

    "── Spiel ──\n"
    "/impostor new — neues Impostor-Spiel erstellen (gibt Code zurück)\n"
    "/impostor join <code> <name> — Spiel beitreten\n"
    "/impostor start — Rollen austeilen (nur Host)\n"
    "/impostor vote <name> — abstimmen\n"
    "/impostor help — alle Spielbefehle\n\n"

    "── Sistema ──\n"
    "/language — cambiar a modo inglés\n"
    "/status — Backend-Ladder & Groq-Quota (verbleibende Anfragen)\n"
    "/backend on|off — Backend-Label in jeder Antwort anzeigen\n"
    "/cancel — aktive Session abbrechen\n"
    "/stop — laufende Übung beenden (in /practice, /quiz, /daily, /roleplay)\n"
    "/start — Willkommen-Nachricht\n"
    "/help — diese Übersicht"
)

HELP_ENGLISH = (
    "Karly — your English tutor.\n"
    "Write in English; I'll correct you. All commands:\n\n"

    "── Learning ──\n"
    "/practice — flashcards (also /flashcards): choose deck and direction\n"
    "/flip — switch EN↔ES direction (during /practice)\n"
    "/daily — daily challenge: fill-in-the-blank + translate + reply\n"
    "/quiz — 7 MCQ questions on your weakest skills\n"
    "/roleplay — conversation scene: choose a scenario, /done for feedback\n"
    "/test — adaptive placement test (~10 questions); /done to finish early, /cancel to quit\n\n"

    "── Profile & Stats ──\n"
    "/profile — level, skill mastery, cards due\n"
    "/review — streak, cards due, hardest vocabulary\n"
    "/weekly — weekly report: sessions, accuracy, corrections, mastery\n"
    "/summary — review recent mistakes and save them for practice\n\n"

    "── Conversation tools ──\n"
    "/corrections strict|relaxed|off — correction level (no arg = current status)\n"
    "/topic <topic> — steer the conversation to a topic (/topic clear to reset)\n"
    "/spanish <question> — ask a question in Spanish\n"
    "/remind HH:MM — set a daily reminder (/remind off to disable)\n\n"

    "── Documents ──\n"
    "/docs — your uploaded PDFs\n"
    "/learn <id> — start a lesson from a document\n"
    "/docfocus on|off — focus conversation on the latest document\n"
    "📄 Send an English PDF → vocabulary is extracted automatically\n\n"

    "── Games ──\n"
    "/impostor new — create an Impostor game (generates a code)\n"
    "/impostor join <code> <name> — join a game\n"
    "/impostor start — assign roles (host only)\n"
    "/impostor vote <name> — vote to eliminate\n"
    "/impostor help — all game commands\n\n"

    "── System ──\n"
    "/language — switch to German mode\n"
    "/status — backend status and Groq quota\n"
    "/backend on|off — show active model in every reply\n"
    "/cancel — cancel the active session\n"
    "/stop — end current exercise (/practice, /quiz, /daily, /roleplay)\n"
    "/start — welcome message\n"
    "/help — this overview"
)


@require_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user and getattr(user, "status", "active") == "pending" and user.language_chosen:
        await update.effective_message.reply_text(
            "⏳ Still waiting for your teacher to approve you. "
            "We'll send you a message as soon as you're in!"
        )
        return
    if user and user.language_chosen:
        # Returning user — show the welcome/command list, not the language picker.
        en = getattr(user, "learning_mode", "german") == "english"
        await update.effective_message.reply_text(WELCOME_ENGLISH if en else WELCOME_GERMAN)
        return
    await update.effective_message.reply_text(LANGUAGE_PICKER, reply_markup=_PICKER_KB)


async def language_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the language-picker inline buttons."""
    query = update.callback_query
    await query.answer()
    mode = query.data.split(":")[1]  # "german" or "english"

    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return

    was_new = not user.language_chosen
    set_learning_mode(user.id, mode)
    set_language_chosen(user.id)

    # Approval flow: hold pending students and notify the teacher.
    if (
        config.ACCESS_MODE == "approval"
        and getattr(user, "status", "active") == "pending"
        and was_new
        and config.SUPERUSER_TELEGRAM_ID
    ):
        lang_label = "🇩🇪 German" if mode == "german" else "🇺🇸 English"
        student_name = user.name or str(update.effective_user.id)
        tg_handle = (
            f"@{update.effective_user.username}"
            if update.effective_user.username
            else f"id={update.effective_user.id}"
        )
        from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM
        kb = IKM([[
            IKB("✅ Approve", callback_data=f"approve_s:{user.id}:{mode}"),
            IKB("❌ Decline", callback_data=f"decline_student:{user.id}"),
        ]])
        try:
            await context.bot.send_message(
                chat_id=config.SUPERUSER_TELEGRAM_ID,
                text=(
                    f"👤 *{student_name}* ({tg_handle}) wants to join Karly!\n"
                    f"They chose: {lang_label}\n\n"
                    "Approve or decline:"
                ),
                reply_markup=kb,
            )
        except Exception:
            logger.exception("Failed to notify teacher of pending student %s", user.id)

        if mode == "german":
            await query.edit_message_text(
                "⏳ Danke! Dein Lehrer muss dich noch freischalten. "
                "Wir melden uns bald!\n\n"
                "(Your teacher will approve you shortly.)"
            )
        else:
            await query.edit_message_text(
                "⏳ Thanks! Your teacher needs to approve you before you start. "
                "We'll notify you soon!"
            )
        return

    if mode == "german":
        welcome = WELCOME_GERMAN + (
            "\n\n👉 *Start here:* do /test to find your level, "
            "then just write to me in German!"
        )
        await query.edit_message_text(welcome)
    else:
        welcome = WELCOME_ENGLISH + (
            "\n\n👉 *Start here:* do /test to find your level, "
            "then just write to me in English!"
        )
        await query.edit_message_text(welcome)


@require_auth
async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/language — show the language picker to switch modes."""
    await update.effective_message.reply_text(LANGUAGE_PICKER, reply_markup=_PICKER_KB)


HELP_TEACHER = (
    "👩‍🏫 *Teacher commands*\n\n"

    "── Roster ──\n"
    "/students — your roster: status, level, streak, last active\n"
    "/student <name> — full profile (CEFR, skills, gaps, activity)\n"
    "/class — weekly snapshot + skill error rates + class topics\n\n"

    "── Classes ──\n"
    "/newclass <name> — create a new class\n"
    "/classes — list your classes with student count and topics\n"
    "/moveclass <student> <class> — move a student to another class\n\n"

    "── Topic & Drills ──\n"
    "/assign — show current topics for your classes\n"
    "/assign <topic> — set topic for all your classes (e.g. /assign present perfect)\n"
    "/assign <class>: <topic> — set topic for one class\n"
    "/assign clear — remove all topics\n"
    "/classtopic — show the current topic (same command students use)\n\n"

    "── Credits & Budget ──\n"
    "/budget — global credit usage, reserve status, top consumers\n"
    "/grant <name> <n> — give a student N extra credits today\n\n"

    "── Superuser only ──\n"
    "/addteacher <name> — promote a student to teacher\n"
    "/removeteacher <name> — demote a teacher to student\n"
    "/teachers — list all teachers with class and student counts\n\n"

    "── Your learning ──\n"
    "All student commands work for you too: /test, /practice, /drill, /quiz,\n"
    "/daily, /roleplay, /weekly, /profile, /corrections, /summary, /docs\n\n"

    "── Setup ──\n"
    "ACCESS_MODE=approval in .env → new users wait for your approval\n"
    "SUPERUSER_TELEGRAM_ID=<your id> → grants superuser role"
)


@require_auth
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    is_teacher = user is not None and getattr(user, "role", "student") in ("teacher", "superuser")
    if is_teacher:
        await update.effective_message.reply_text(HELP_TEACHER)
        # Also send the student help so teacher sees all commands.
        base = HELP_ENGLISH if (user and user.learning_mode == "english") else HELP_GERMAN
        await update.effective_message.reply_text(base)
    elif user and user.learning_mode == "english":
        await update.effective_message.reply_text(HELP_ENGLISH)
    else:
        await update.effective_message.reply_text(HELP_GERMAN)


@require_auth
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global /cancel. The assessment/practice conversations consume /cancel
    while active; this only fires when nothing is running, so the user always
    gets a reply instead of silence."""
    await update.effective_message.reply_text(
        "Es läuft gerade nichts zum Abbrechen. (Nothing active to cancel.)"
    )


@require_auth
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        await update.effective_message.reply_text("Kein Profil gefunden.")
        return

    en = getattr(user, "learning_mode", "german") == "english"
    verdict = latest_assessment(user.id)
    count = vocab_count(user.id)

    if en:
        lines = ["📋 *Your Profile*\n"]
        if verdict:
            lines.append(f"Level (overall): *{verdict.get('overall', '?')}*")
            skills = verdict.get("skills") or {}
            if skills:
                lines.append("By skill:")
                for k, v in skills.items():
                    lines.append(f"  • {k.capitalize()}: {v}")
            gaps = verdict.get("gaps") or []
            if gaps:
                lines.append("\nTop gaps:")
                for g in gaps[:5]:
                    lines.append(f"  • {g}")
        else:
            lines.append("No placement test yet. Start with /test.")
        lines.append(f"\nSaved vocabulary/corrections: *{count}*")
        due = count_due(user.id)
        if due:
            lines.append(f"🃏 Due for practice: *{due}* — /flashcards")
        bkt_state = get_bkt_state(user.id)
        active = {s: e for s, e in bkt_state.items() if e.get("p", 0) > bkt_mod.P_L0 + 0.001}
        if active:
            lines.append("\n🧠 *Skill mastery (BKT):*")
            for skill, entry in active.items():
                p = entry.get("p", 0.0)
                lvl = entry.get("level")
                label = f"{skill.capitalize()} ({lvl})" if lvl else skill.capitalize()
                bar = bkt_mod.mastery_bar(p)
                star = " ✅" if bkt_mod.mastered(p) else ""
                lines.append(f"  {label}: {bar}{star}")
    else:
        lines = ["📋 *Dein Profil*\n"]
        if verdict:
            lines.append(f"Level (overall): *{verdict.get('overall', '?')}*")
            skills = verdict.get("skills") or {}
            if skills:
                lines.append("Per skill:")
                for k, v in skills.items():
                    lines.append(f"  • {k.capitalize()}: {v}")
            gaps = verdict.get("gaps") or []
            if gaps:
                lines.append("\nTop gaps:")
                for g in gaps[:5]:
                    lines.append(f"  • {g}")
        else:
            lines.append("Noch kein Einstufungstest gemacht. Starte mit /test.")
        lines.append(f"\nGespeicherte Vokabeln/Korrekturen: *{count}*")
        due = count_due(user.id)
        if due:
            lines.append(f"🃏 Fällig zum Üben: *{due}* — /flashcards")
        bkt_state = get_bkt_state(user.id)
        active = {s: e for s, e in bkt_state.items() if e.get("p", 0) > bkt_mod.P_L0 + 0.001}
        if active:
            lines.append("\n🧠 *Skill mastery (BKT):*")
            for skill, entry in active.items():
                p = entry.get("p", 0.0)
                lvl = entry.get("level")
                label = f"{skill.capitalize()} ({lvl})" if lvl else skill.capitalize()
                bar = bkt_mod.mastery_bar(p)
                star = " ✅" if bkt_mod.mastered(p) else ""
                lines.append(f"  {label}: {bar}{star}")

    await update.effective_message.reply_text("\n".join(lines))
