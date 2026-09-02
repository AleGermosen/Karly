"""/start, /help, /profile command handlers."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.middleware import require_auth
from db.repo import get_user_by_telegram_id, latest_assessment, vocab_count

WELCOME = (
    "Hallo! Ich bin Karly, dein Deutsch-Tutor. 🇩🇪\n\n"
    "Schreib mir einfach auf Deutsch — ich antworte und korrigiere jeden "
    "Fehler (❌ falsch → ✅ richtig — warum).\n\n"
    "Commands:\n"
    "/test — Einstufungstest (find your level)\n"
    "/profile — dein Lernprofil\n"
    "/practice — Vokabeln üben\n"
    "/review — Übungs-Statistik\n"
    "/remind HH:MM — tägliche Erinnerung\n"
    "/topic <x> — Thema steuern\n"
    "/english <q> — eine Frage auf Englisch stellen\n"
    "📄 Schick mir eine Technik-PDF → /learn, /docs\n"
    "/help — Hilfe"
)

HELP = (
    "Karly — dein Deutsch-Tutor.\n\n"
    "/start — Willkommen\n"
    "/test — adaptiver Einstufungstest (~10-15 Fragen); /done früher fertig, "
    "/cancel abbrechen\n"
    "/profile — Level, Schwächen, Vokabelzahl\n"
    "/practice — Vokabeln üben (Spaced Repetition); /stop beendet\n"
    "/review — Statistik: fällig, Streak, schwerste Vokabeln\n"
    "/remind HH:MM — tägliche Erinnerung (/remind off zum Ausschalten)\n"
    "/topic <x> — Gespräch auf ein Thema lenken (/topic clear zum Zurücksetzen)\n"
    "/english <q> — Meta-Frage auf Englisch\n\n"
    "📄 Dokumente:\n"
    "Schick mir eine deutsche Technik-PDF — ich extrahiere Fachbegriffe.\n"
    "/docs — deine Dokumente\n"
    "/learn <id> — Lektion aus einem Dokument\n"
    "/docfocus on|off — Gespräche aufs neueste Dokument lenken\n\n"
    "Sonst: schreib einfach auf Deutsch und ich korrigiere dich."
)


@require_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME)


@require_auth
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP)


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

    await update.effective_message.reply_text("\n".join(lines))
