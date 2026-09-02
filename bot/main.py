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
from bot.handlers import conversation, start
from db.session import init_db

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

    # Any non-command text goes to the conversation handler (echo in Phase 0).
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, conversation.echo)
    )

    return app


def main() -> None:
    init_db()
    logger.info("Database ready.")
    app = build_application()
    logger.info("Starting Karly (long polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
