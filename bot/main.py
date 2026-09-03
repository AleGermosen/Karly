"""Karly entrypoint: registers handlers and runs long polling."""
from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import config
from bot.handlers import (
    assessment,
    conversation,
    daily,
    documents,
    practice,
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
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start.start))
    app.add_handler(CommandHandler("help", start.help_cmd))
    app.add_handler(CommandHandler("profile", start.profile))

    # Conversation flows (registered before the catch-all handler).
    app.add_handler(assessment.build_handler())
    app.add_handler(practice.build_handler())
    app.add_handler(daily.build_handler())
    app.add_handler(quiz.build_handler())
    app.add_handler(roleplay.build_handler())

    # Global /cancel — only fires when no conversation is active (the assessment
    # and practice handlers consume /cancel/​/stop themselves while running).
    app.add_handler(CommandHandler("cancel", start.cancel_cmd))

    app.add_handler(CommandHandler("review", practice.review))
    app.add_handler(CommandHandler("weekly", report.weekly_report))
    app.add_handler(CommandHandler("remind", reminders.remind))
    app.add_handler(CommandHandler("topic", conversation.topic))
    app.add_handler(CommandHandler("english", conversation.english))
    app.add_handler(CommandHandler("corrections", conversation.corrections))
    app.add_handler(CommandHandler("summary", conversation.summary))
    app.add_handler(CommandHandler("status", conversation.status))
    app.add_handler(CommandHandler("backend", conversation.backend))

    # Documents (Phase 4).
    app.add_handler(CommandHandler("docs", documents.docs))
    app.add_handler(CommandHandler("learn", documents.learn))
    app.add_handler(CommandHandler("docfocus", documents.docfocus))
    app.add_handler(MessageHandler(filters.Document.ALL, documents.handle_document))

    # Inline action buttons attached to corrected replies (📖/➕/🎯).
    app.add_handler(
        CallbackQueryHandler(conversation.on_correction_action, pattern=r"^corr:")
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
    BotCommand("roleplay", "Roleplay-Szene auf Deutsch"),
    BotCommand("weekly", "Wöchentlicher Lernbericht"),
    BotCommand("test", "Einstufungstest starten"),
    BotCommand("profile", "Dein Lernprofil ansehen"),
    BotCommand("review", "Übungs-Statistik & Streak"),
    BotCommand("topic", "Gespräch auf ein Thema lenken"),
    BotCommand("summary", "Deine Fehler auswerten"),
    BotCommand("corrections", "Korrekturen ein/aus"),
    BotCommand("docs", "Deine Dokumente"),
    BotCommand("remind", "Tägliche Erinnerung setzen"),
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
