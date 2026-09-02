"""Karly entrypoint: registers handlers and runs long polling."""
from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

import config
from bot.handlers import assessment, conversation, practice, reminders, start
from db.session import init_db
from llm import ollama_client

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("karly")


def build_application() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start.start))
    app.add_handler(CommandHandler("help", start.help_cmd))
    app.add_handler(CommandHandler("profile", start.profile))

    # Conversation flows (registered before the catch-all handler).
    app.add_handler(assessment.build_handler())
    app.add_handler(practice.build_handler())

    app.add_handler(CommandHandler("review", practice.review))
    app.add_handler(CommandHandler("remind", reminders.remind))
    app.add_handler(CommandHandler("topic", conversation.topic))
    app.add_handler(CommandHandler("english", conversation.english))

    # Any non-command text goes to the tutor conversation handler.
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, conversation.chat)
    )

    return app


async def _post_init(app: Application) -> None:
    """Startup hooks: probe Ollama (dormant until Phase 5); restore reminders."""
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
