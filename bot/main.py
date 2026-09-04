"""Karly entrypoint: registers handlers and runs long polling."""
from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    Defaults,
    MessageHandler,
    filters,
)

import config
from bot.handlers import (
    assessment,
    classroom,
    conversation,
    daily,
    documents,
    drill,
    export,
    game,
    practice,
    pronounce,
    quiz,
    reminders,
    report,
    roleplay,
    start,
)
from db.session import init_db
from llm import ollama_client

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
# python-telegram-bot talks to Telegram over httpx, which logs every request
# line at INFO — and the bot token is part of the Telegram API URL path. Quiet
# the HTTP client loggers so the token never lands in journald.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("karly")


def build_application() -> Application:
    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.MARKDOWN))
        .build()
    )

    app.add_handler(CommandHandler("start", start.start))
    app.add_handler(CommandHandler("help", start.help_cmd))
    app.add_handler(CommandHandler("language", start.language_cmd))
    app.add_handler(CommandHandler("profile", start.profile))
    app.add_handler(CommandHandler("mybudget", start.mybudget))
    app.add_handler(CommandHandler("pronounce", pronounce.pronounce))
    # Language picker callback (from /start and /language inline buttons).
    app.add_handler(
        CallbackQueryHandler(start.language_pick, pattern=r"^lang:")
    )

    # Teacher classroom commands.
    app.add_handler(CommandHandler("students", classroom.students))
    app.add_handler(CommandHandler("student", classroom.student))
    app.add_handler(CommandHandler("class", classroom.class_summary))
    app.add_handler(CommandHandler("budget", classroom.budget))
    app.add_handler(CommandHandler("grant", classroom.grant))
    app.add_handler(CommandHandler("assign", classroom.assign))
    app.add_handler(CommandHandler("classtopic", classroom.classtopic))
    app.add_handler(CommandHandler("newclass", classroom.newclass))
    app.add_handler(CommandHandler("classes", classroom.classes))
    app.add_handler(CommandHandler("moveclass", classroom.moveclass))
    app.add_handler(CommandHandler("classsetcorr", classroom.classsetcorr))
    app.add_handler(CommandHandler("export", export.export_csv))
    # Superuser-only teacher management.
    app.add_handler(CommandHandler("addteacher", classroom.addteacher))
    app.add_handler(CommandHandler("removeteacher", classroom.removeteacher))
    app.add_handler(CommandHandler("teachers", classroom.teachers_list))
    # Approval flow callbacks (multi-step DM to superuser).
    app.add_handler(
        CallbackQueryHandler(classroom.on_approve_student, pattern=r"^approve_s:")
    )
    app.add_handler(
        CallbackQueryHandler(classroom.on_set_teacher, pattern=r"^set_teacher_s:")
    )
    app.add_handler(
        CallbackQueryHandler(classroom.on_set_class, pattern=r"^set_class_s:")
    )
    app.add_handler(
        CallbackQueryHandler(classroom.on_decline_student, pattern=r"^decline_student:")
    )

    # Conversation flows (registered before the catch-all handler).
    app.add_handler(assessment.build_handler())
    app.add_handler(practice.build_handler())
    app.add_handler(daily.build_handler())
    app.add_handler(quiz.build_handler())
    app.add_handler(drill.build_handler())
    app.add_handler(roleplay.build_handler())

    # Global /cancel — only fires when no conversation is active (the assessment
    # and practice handlers consume /cancel/​/stop themselves while running).
    app.add_handler(CommandHandler("cancel", start.cancel_cmd))

    app.add_handler(CommandHandler("review", practice.review))
    app.add_handler(CommandHandler("weekly", report.weekly_report))
    app.add_handler(CommandHandler("remind", reminders.remind))
    app.add_handler(CommandHandler("topic", conversation.topic))
    app.add_handler(CommandHandler("english", conversation.english))
    app.add_handler(CommandHandler("spanish", conversation.spanish))
    app.add_handler(CommandHandler("corrections", conversation.corrections))
    app.add_handler(CommandHandler("summary", conversation.summary))
    app.add_handler(CommandHandler("status", conversation.status))
    app.add_handler(CommandHandler("backend", conversation.backend))

    # Documents (Phase 4).
    app.add_handler(CommandHandler("docs", documents.docs))
    app.add_handler(CommandHandler("learn", documents.learn))
    app.add_handler(CommandHandler("docfocus", documents.docfocus))
    app.add_handler(MessageHandler(filters.Document.ALL, documents.handle_document))

    # The Impostor game.
    for handler in game.build_handlers():
        app.add_handler(handler)

    # "Free features" buttons shown on credit/quota exhaustion messages.
    app.add_handler(
        CallbackQueryHandler(conversation.on_free_feature_tap, pattern=r"^free:")
    )

    # Inline action buttons attached to corrected replies (📖/➕/🎯).
    app.add_handler(
        CallbackQueryHandler(conversation.on_correction_action, pattern=r"^corr:")
    )
    # Correction level picker buttons.
    app.add_handler(
        CallbackQueryHandler(conversation.on_corrections_pick, pattern=r"^setcorr:")
    )

    # Any non-command text goes to the tutor conversation handler.
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, conversation.chat)
    )

    return app


# The native Telegram command menu (the ≡ button), curated and ordered by
# expected frequency. Debug commands (/status, /backend) are intentionally
# omitted. Order is static for now; usage-sorted ordering is future work.
MENU_COMMANDS = [
    BotCommand("practice", "Vokabeln üben (Spaced Repetition)"),
    BotCommand("flashcards", "Karteikarten üben (wie /practice)"),
    BotCommand("daily", "Tägliche Mini-Challenge (3 Aufgaben)"),
    BotCommand("quiz", "Schnell-Quiz auf schwache Skills"),
    BotCommand("drill", "Gezieltes Themen-Drill (10 Übungen)"),
    BotCommand("classtopic", "Aktuelles Klassen-Thema anzeigen"),
    BotCommand("roleplay", "Roleplay-Szene auf Deutsch"),
    BotCommand("weekly", "Wöchentlicher Lernbericht"),
    BotCommand("test", "Einstufungstest starten"),
    BotCommand("profile", "Dein Lernprofil ansehen"),
    BotCommand("mybudget", "Verbleibende Credits heute"),
    BotCommand("pronounce", "Aussprache als Sprachnachricht"),
    BotCommand("review", "Übungs-Statistik & Streak"),
    BotCommand("topic", "Gespräch auf ein Thema lenken"),
    BotCommand("summary", "Deine Fehler auswerten"),
    BotCommand("corrections", "Korrekturen ein/aus"),
    BotCommand("docs", "Deine Dokumente"),
    BotCommand("remind", "Tägliche Erinnerung setzen"),
    BotCommand("impostor", "🎮 Play The Impostor with friends"),
    BotCommand("start", "Willkommen / neu starten"),
    BotCommand("help", "Alle Befehle anzeigen"),
]


async def _post_init(app: Application) -> None:
    """Startup hooks: publish the command menu; probe Ollama; restore reminders."""
    await app.bot.set_my_commands(MENU_COMMANDS)
    await ollama_client.health_check()
    await reminders.reschedule_all(app)


def main() -> None:
    init_db()
    logger.info("Database ready.")
    app = build_application()
    app.post_init = _post_init
    logger.info("Starting Karly (long polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
