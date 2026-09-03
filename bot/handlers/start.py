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
    "Schreib mir einfach auf Deutsch — ich antworte und korrigiere jeden "
    "Fehler (❌ falsch → ✅ richtig — warum).\n\n"
    "Commands:\n"
    "/test — Einstufungstest (find your level)\n"
    "/profile — dein Lernprofil\n"
    "/practice — Vokabeln üben (auch /flashcards)\n"
    "/daily — tägliche Mini-Challenge\n"
    "/quiz — Schnell-Quiz auf deine schwächsten Skills\n"
    "/roleplay — Rollenspiel-Szene auf Deutsch\n"
    "/weekly — Wöchentlicher Lernbericht\n"
    "/review — Übungs-Statistik\n"
    "/remind HH:MM — tägliche Erinnerung\n"
    "/topic <x> — Thema steuern\n"
    "/english <q> — eine Frage auf Englisch stellen\n"
    "/corrections on|off — Korrekturen ein/aus\n"
    "/summary — Fehler-Auswertung\n"
    "📄 Schick mir eine Technik-PDF → /learn, /docs\n"
    "/help — Hilfe"
)

HELP = (
    "Karly — dein Deutsch-Tutor.\n\n"
    "/start — Willkommen\n"
    "/test — adaptiver Einstufungstest (~10-15 Fragen); /done früher fertig, "
    "/cancel abbrechen\n"
    "/profile — Level, Schwächen, Vokabelzahl\n"
    "/practice (oder /flashcards) — Vokabeln üben (Spaced Repetition); Deck & "
    "Richtung wählen; /flip wechselt DE↔EN; /stop beendet\n"
    "/daily — tägliche Mini-Challenge (Lückentext + Übersetzen + Antworten)\n"
    "/quiz — Schnell-Quiz (7 MCQ) auf deine schwächsten Skills; /stop beendet\n"
    "/roleplay — Rollenspiel: Szene wählen, Deutsch sprechen, /done für Feedback\n"
    "/weekly — Wöchentlicher Bericht: Sessions, Genauigkeit, Korrekturen, Mastery\n"
    "/review — Statistik: fällig, Streak, schwerste Vokabeln\n"
    "/remind HH:MM — tägliche Erinnerung (/remind off zum Ausschalten)\n"
    "/topic <x> — Gespräch auf ein Thema lenken (/topic clear zum Zurücksetzen)\n"
    "/english <q> — Meta-Frage auf Englisch\n"
    "/corrections on|off — Inline-Korrekturen ein/aus (frei plaudern)\n"
    "/summary — Auswertung deiner Fehler + speichern zum Üben\n\n"
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
