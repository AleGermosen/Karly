"""/start, /help, /profile, /language command handlers."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from bot.middleware import require_auth
from bot import credits as credit_mod
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
    "/weekly — Wochenbericht\n"
    "🎭 /impostor — soziales Detektivspiel für die Klasse\n\n"
    "/help — alle Commands\n\n"
    "ℹ️ Dein Lehrer kann deinen Lernfortschritt sehen (Level, Aktivität, Fehler-Schwerpunkte) — aber nicht deine genauen Nachrichten."
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
    "/help — all commands\n\n"
    "ℹ️ Your teacher can see your learning progress (level, activity, weak areas) — but not your exact messages."
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
    "/mybudget — verbleibende Credits heute anzeigen\n"
    "/subscribe — Abonnement abschließen (mehr Nachrichten)\n"
    "/topup — Nachrichten-Paket kaufen (verfallen nie)\n"
    "/pronounce WORT — Aussprache als Sprachnachricht\n"
    "/topic THEMA — Gespräch auf ein Thema lenken (/topic clear zum Löschen)\n"
    "/english FRAGE — Meta-Frage auf Englisch stellen\n"
    "/remind HH:MM — tägliche Erinnerung setzen (/remind off zum Ausschalten)\n\n"

    "── Dokumente ──\n"
    "/docs — deine hochgeladenen PDFs\n"
    "/learn ID — Lektion aus einem Dokument starten\n"
    "/docfocus on|off — Gespräch aufs neueste Dokument lenken\n"
    "📄 Schick eine deutsche PDF → Fachbegriffe werden automatisch extrahiert\n\n"

    "── Spiel ──\n"
    "/impostor new — neues Impostor-Spiel erstellen (gibt Code zurück)\n"
    "/impostor join CODE NAME — Spiel beitreten\n"
    "/impostor start — Rollen austeilen (nur Host)\n"
    "/impostor vote NAME — abstimmen\n"
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
    "/mybudget — show your remaining credits today\n"
    "/subscribe — get a subscription (more messages)\n"
    "/topup — buy a message pack (never expires)\n"
    "/pronounce WORD — hear the pronunciation as a voice note\n"
    "/topic TOPIC — steer the conversation to a topic (/topic clear to reset)\n"
    "/spanish QUESTION — ask a question in Spanish\n"
    "/remind HH:MM — set a daily reminder (/remind off to disable)\n\n"

    "── Documents ──\n"
    "/docs — your uploaded PDFs\n"
    "/learn ID — start a lesson from a document\n"
    "/docfocus on|off — focus conversation on the latest document\n"
    "📄 Send an English PDF → vocabulary is extracted automatically\n\n"

    "── Games ──\n"
    "/impostor new — create an Impostor game (generates a code)\n"
    "/impostor join CODE NAME — join a game\n"
    "/impostor start — assign roles (host only)\n"
    "/impostor vote NAME — vote to eliminate\n"
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
    "/student NAME — full profile (CEFR, skills, gaps, activity)\n"
    "/class — weekly snapshot + skill error rates + class topics\n\n"

    "── Classes ──\n"
    "/newclass NAME — create a class (/newclass Beginners english)\n"
    "/classes — list your classes with student count and topics\n"
    "/moveclass STUDENT CLASS — move a student to another class\n"
    "/classsetcorr CLASS LEVEL — set default correction level for a class (0–5)\n\n"

    "── Topic & Drills ──\n"
    "/assign — show current topics for your classes\n"
    "/assign TOPIC — set topic for all your classes\n"
    "/assign CLASS: TOPIC — set topic for one class\n"
    "/assign clear — remove all topics\n"
    "/classtopic — show the current topic\n\n"

    "── Credits & Budget ──\n"
    "/budget — global credit usage, reserve status, top consumers\n"
    "/grant NAME N — give a student N extra credits today\n\n"
    "── Export ──\n"
    "/export — download a CSV of your students' progress\n\n"

    "── Superuser only ──\n"
    "/addteacher NAME — promote a student to teacher\n"
    "/removeteacher NAME — demote a teacher to student\n"
    "/teachers — list all teachers with class and student counts\n\n"

    "── Your learning ──\n"
    "All student commands work for you too — see the next message."
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

    _LEVEL_NAMES = {0: "off", 1: "gentle", 2: "light", 3: "balanced", 4: "thorough", 5: "exam"}
    corr_label = _LEVEL_NAMES.get(user.correction_level, str(user.correction_level))

    if en:
        lines = ["📋 *Your Profile*\n"]
        lines.append(f"Corrections: *{corr_label}* ({user.correction_level}/5) — /corrections to change")
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
        lines.append(f"Korrekturen: *{corr_label}* ({user.correction_level}/5) — /corrections zum Ändern")
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


@require_auth
async def mybudget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/mybudget — show the student their remaining credits and tier status."""
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    en = getattr(user, "learning_mode", "german") == "english"
    remaining = credit_mod.credits_remaining(user.id)
    limit = credit_mod._effective_user_limit(user.id)

    from db.repo import practice_streak, reset_expired_windows, get_public_limits_state
    import config as _cfg
    reset_expired_windows(user.id)
    streak = practice_streak(user.id)
    bonus = min(streak, 5)
    pub = get_public_limits_state(user.id)
    subscribed = pub.get("subscribed", False)
    session_count = pub.get("session_count", 0)
    week_count = pub.get("week_count", 0)
    topup = pub.get("topup_credits", 0)
    session_cap = _cfg.SESSION_CAP_SUBSCRIBER if subscribed else _cfg.SESSION_CAP_FREE
    week_cap = _cfg.WEEK_CAP_SUBSCRIBER if subscribed else _cfg.WEEK_CAP_FREE
    sub_until = user.subscription_expires_at.strftime("%Y-%m-%d") if (subscribed and user.subscription_expires_at) else None

    if en:
        lines = ["⚡ *Your budget*\n"]
        tier = "⭐ Subscriber" if subscribed else "Free tier"
        lines.append(f"Plan: *{tier}*" + (f" (until {sub_until})" if sub_until else ""))
        lines.append(f"Classroom credits today: *{remaining} / {limit}*")
        if bonus:
            lines.append(f"_(includes +{bonus} streak bonus 🔥)_")
        lines.append(f"\nSession messages: *{session_count} / {session_cap}*  _(resets every {_cfg.SESSION_WINDOW_HOURS}h)_")
        lines.append(f"Weekly messages: *{week_count} / {week_cap}*  _(resets Monday)_")
        if topup:
            lines.append(f"Top-up credits: *{topup}* _(never expire)_")
        lines.append("\nCredit costs:")
        lines.append("  • Chat message / roleplay turn: 1")
        lines.append("  • Quiz session: 2")
        lines.append("  • Daily challenge: 1–2")
        lines.append("  • Summary: 1")
        lines.append("  • Lesson from PDF: 3")
        lines.append("\nFlashcards, games, and /test are always free. 🃏")
        if not subscribed:
            lines.append("\n_/subscribe — upgrade for more practice time_")
    else:
        lines = ["⚡ *Dein Budget*\n"]
        tier = "⭐ Abonnent" if subscribed else "Gratis-Tarif"
        lines.append(f"Tarif: *{tier}*" + (f" (bis {sub_until})" if sub_until else ""))
        lines.append(f"Klassen-Credits heute: *{remaining} / {limit}*")
        if bonus:
            lines.append(f"_(inkl. +{bonus} Streak-Bonus 🔥)_")
        lines.append(f"\nSession-Nachrichten: *{session_count} / {session_cap}*  _(Reset alle {_cfg.SESSION_WINDOW_HOURS}h)_")
        lines.append(f"Wöchentliche Nachrichten: *{week_count} / {week_cap}*  _(Reset montags)_")
        if topup:
            lines.append(f"Top-up-Credits: *{topup}* _(verfallen nie)_")
        lines.append("\nCredit-Kosten:")
        lines.append("  • Chat-Nachricht / Roleplay-Runde: 1")
        lines.append("  • Quiz-Session: 2")
        lines.append("  • Tägliche Challenge: 1–2")
        lines.append("  • Auswertung (/summary): 1")
        lines.append("  • Lektion aus PDF: 3")
        lines.append("\nKarteikarten, Spiel und /test sind immer kostenlos. 🃏")
        if not subscribed:
            lines.append("\n_/subscribe — mehr Übungszeit mit Abo_")
    await update.effective_message.reply_text("\n".join(lines))
