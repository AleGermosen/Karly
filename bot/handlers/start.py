"""/start, /help, /profile, /language command handlers."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.middleware import require_auth
from db.repo import (
    count_due,
    get_bkt_state,
    get_user_by_telegram_id,
    latest_assessment,
    set_learning_mode,
    vocab_count,
)
from srs import bkt as bkt_mod

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
    "¡Hola! Soy Karly, tu tutora de inglés. 🇺🇸\n\n"
    "Escríbeme en inglés — te respondo y te corrijo.\n\n"
    "Comandos principales:\n"
    "/practice — tarjetas de vocabulario (también /flashcards)\n"
    "/daily — reto diario: 3 ejercicios cortos\n"
    "/quiz — quiz rápido sobre tus puntos más débiles\n"
    "/roleplay — escena de conversación en inglés\n"
    "/test — prueba de nivel adaptativa\n"
    "/profile — tu perfil de aprendizaje\n"
    "/weekly — informe semanal de progreso\n\n"
    "/help — todos los comandos"
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
    "Karly — tu tutora de inglés.\n"
    "Escríbeme en inglés; te corrijo. Todos los comandos:\n\n"

    "── Aprender ──\n"
    "/practice — tarjetas de vocabulario (también /flashcards): elige mazo y dirección\n"
    "/flip — cambiar dirección EN↔ES (dentro de /practice)\n"
    "/daily — reto diario: espacio en blanco + traducir + responder\n"
    "/quiz — 7 preguntas MCQ sobre tus habilidades más débiles\n"
    "/roleplay — escena de conversación: elige escenario, /done para feedback\n"
    "/test — prueba de nivel adaptativa (~10 preguntas); /done para terminar antes, /cancel para cancelar\n\n"

    "── Perfil y estadísticas ──\n"
    "/profile — nivel, dominio de habilidades, tarjetas pendientes\n"
    "/review — racha, tarjetas pendientes, vocabulario más difícil\n"
    "/weekly — informe semanal: sesiones, precisión, correcciones, dominio\n"
    "/summary — analizar tus errores recientes y guardarlos para practicar\n\n"

    "── Conversación ──\n"
    "/corrections strict|relaxed|off — nivel de correcciones (sin arg = estado actual)\n"
    "/topic <tema> — enfocar la conversación en un tema (/topic clear para borrar)\n"
    "/spanish <pregunta> — hacer una pregunta en español\n"
    "/remind HH:MM — recordatorio diario (/remind off para desactivar)\n\n"

    "── Documentos ──\n"
    "/docs — tus PDFs subidos\n"
    "/learn <id> — lección a partir de un documento\n"
    "/docfocus on|off — orientar la conversación hacia el último documento\n"
    "📄 Envía un PDF en inglés → se extrae el vocabulario automáticamente\n\n"

    "── Sistema ──\n"
    "/language — cambiar a modo alemán\n"
    "/status — estado del backend y cuota de Groq\n"
    "/backend on|off — mostrar el modelo activo en cada respuesta\n"
    "/cancel — cancelar la sesión activa\n"
    "/stop — terminar el ejercicio en curso (/practice, /quiz, /daily, /roleplay)\n"
    "/start — mensaje de bienvenida\n"
    "/help — este resumen"
)


@require_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None or user.learning_mode == "german":
        await update.effective_message.reply_text(
            LANGUAGE_PICKER, reply_markup=_PICKER_KB
        )
    else:
        await update.effective_message.reply_text(
            LANGUAGE_PICKER, reply_markup=_PICKER_KB
        )


async def language_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the language-picker inline buttons."""
    query = update.callback_query
    await query.answer()
    mode = query.data.split(":")[1]  # "german" or "english"

    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return
    set_learning_mode(user.id, mode)

    if mode == "german":
        await query.edit_message_text(WELCOME_GERMAN)
    else:
        await query.edit_message_text(WELCOME_ENGLISH)


@require_auth
async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/language — show the language picker to switch modes."""
    await update.effective_message.reply_text(LANGUAGE_PICKER, reply_markup=_PICKER_KB)


@require_auth
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user_by_telegram_id(update.effective_user.id)
    if user and user.learning_mode == "english":
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
        lines = ["📋 *Tu Perfil*\n"]
        if verdict:
            lines.append(f"Nivel (general): *{verdict.get('overall', '?')}*")
            skills = verdict.get("skills") or {}
            if skills:
                lines.append("Por habilidad:")
                for k, v in skills.items():
                    lines.append(f"  • {k.capitalize()}: {v}")
            gaps = verdict.get("gaps") or []
            if gaps:
                lines.append("\nPuntos débiles:")
                for g in gaps[:5]:
                    lines.append(f"  • {g}")
        else:
            lines.append("Todavía no has hecho la prueba de nivel. Empieza con /test.")
        lines.append(f"\nVocabulario/correcciones guardados: *{count}*")
        due = count_due(user.id)
        if due:
            lines.append(f"🃏 Pendientes para practicar: *{due}* — /flashcards")
        bkt_state = get_bkt_state(user.id)
        active = {s: e for s, e in bkt_state.items() if e.get("p", 0) > bkt_mod.P_L0 + 0.001}
        if active:
            lines.append("\n🧠 *Dominio de habilidades (BKT):*")
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
