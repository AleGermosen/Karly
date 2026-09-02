"""Configuration loader. Reads .env and fails fast with a clear message."""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.stderr.write(
            f"\n[config] Missing required environment variable: {name}\n"
            f"         Copy .env.example to .env and fill it in.\n\n"
        )
        sys.exit(1)
    return value


# --- Required ---
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY: str = _require("GEMINI_API_KEY")

# --- Optional ---
_allowed = os.getenv("ALLOWED_USER_ID", "").strip()
ALLOWED_USER_ID: int | None = int(_allowed) if _allowed else None

GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct").strip()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///karly.db").strip()

# Conversation context window (messages) to respect free-tier limits.
CONTEXT_WINDOW_MESSAGES: int = 20
