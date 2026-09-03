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
OLLAMA_MODEL: str = os.getenv(
    "OLLAMA_MODEL", "llama3.2:3b-instruct-q4_K_M"
).strip()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///karly.db").strip()

# --- Groq (optional — absence means Groq rungs are skipped) ---
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
GROQ_BASE_URL: str = os.getenv(
    "GROQ_BASE_URL", "https://api.groq.com/openai/v1"
).strip()
GROQ_MODEL_PRIMARY: str = os.getenv(
    "GROQ_MODEL_PRIMARY", "groq/compound"
).strip()
GROQ_MODEL_FALLBACK: str = os.getenv(
    "GROQ_MODEL_FALLBACK", "groq/compound-mini"
).strip()
GROQ_TEMPERATURE: float = float(os.getenv("GROQ_TEMPERATURE", "0.7"))
GROQ_MAX_TOKENS: int = int(os.getenv("GROQ_MAX_TOKENS", "1024"))
# seconds
GROQ_CONNECT_TIMEOUT: float = float(os.getenv("GROQ_CONNECT_TIMEOUT", "5.0"))
GROQ_READ_TIMEOUT: float = float(os.getenv("GROQ_READ_TIMEOUT", "30.0"))

# Conversation context window (messages) to respect free-tier limits.
CONTEXT_WINDOW_MESSAGES: int = 20
