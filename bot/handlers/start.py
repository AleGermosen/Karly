"""/start, /help, /profile command handlers."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.middleware import require_auth
from db.repo import (
    count_due,
    get_bkt_state,
    get_user_by_telegram_id,
    latest_assessment,
    vocab_count,
)
from srs import bkt as bkt_mod

WELCOME = (
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

HELP = (
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

    "── System ──\n"
    "/status — Backend-Ladder & Groq-Quota (verbleibende Anfragen)\n"
    "/backend on|off — Backend-Label in jeder Antwort anzeigen\n"
    "/cancel — aktive Session abbrechen\n"
    "/stop — laufende Übung beenden (in /practice, /quiz, /daily, /roleplay)\n"
    "/start — Willkommen-Nachricht\n"
    "/help — diese Übersicht"
)


@require_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME)


@require_auth
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP)


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

    verdict = latest_assessment(user.id)
    count = vocab_count(user.id)

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
        lines.append(
            "Noch kein Einstufungstest gemacht. Starte mit /test."
        )
    lines.append(f"\nGespeicherte Vokabeln/Korrekturen: *{count}*")
    due = count_due(user.id)
    if due:
        lines.append(f"🃏 Fällig zum Üben: *{due}* — /flashcards")

    # BKT mastery bars — only show skills that have received at least one update.
    bkt_state = get_bkt_state(user.id)
    active = {
        s: entry for s, entry in bkt_state.items()
        if entry.get("p", 0) > bkt_mod.P_L0 + 0.001
    }
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
