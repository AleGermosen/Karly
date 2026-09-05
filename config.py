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
    "GROQ_MODEL_PRIMARY", "openai/gpt-oss-120b"
).strip()
GROQ_MODEL_FALLBACK: str = os.getenv(
    "GROQ_MODEL_FALLBACK", "openai/gpt-oss-20b"
).strip()
GROQ_TEMPERATURE: float = float(os.getenv("GROQ_TEMPERATURE", "0.7"))
GROQ_MAX_TOKENS: int = int(os.getenv("GROQ_MAX_TOKENS", "1024"))
# seconds
GROQ_CONNECT_TIMEOUT: float = float(os.getenv("GROQ_CONNECT_TIMEOUT", "5.0"))
GROQ_READ_TIMEOUT: float = float(os.getenv("GROQ_READ_TIMEOUT", "30.0"))

# Conversation context window — 8 recent turns keeps input tokens ~40% lower
# than the old 20-turn window while preserving meaningful context.
CONTEXT_WINDOW_MESSAGES: int = 8

# Per-student daily LLM credit allowance. 20 credits ≈ 20 conversation turns,
# or a course unit + daily challenge + a few chat messages.
DAILY_CREDIT_LIMIT: int = int(os.getenv("DAILY_CREDIT_LIMIT", "20"))

# --- Classroom ---
# Telegram user-id of the superuser (school admin). Reads SUPERUSER_TELEGRAM_ID
# first; falls back to TEACHER_TELEGRAM_ID for backward compatibility.
_su = (
    os.getenv("SUPERUSER_TELEGRAM_ID", "").strip()
    or os.getenv("TEACHER_TELEGRAM_ID", "").strip()
)
SUPERUSER_TELEGRAM_ID: int | None = int(_su) if _su else None
# Kept as an alias so any code still referencing TEACHER_TELEGRAM_ID still works.
TEACHER_TELEGRAM_ID: int | None = SUPERUSER_TELEGRAM_ID

# "open"     — anyone who can reach the bot is let straight in (default).
# "approval" — new students are held as "pending" until the teacher approves.
ACCESS_MODE: str = os.getenv("ACCESS_MODE", "open").strip()

# --- Token budget (T.6 / T.7) ---
# Total credits all students combined can spend per day. At 50 students × 20
# each the theoretical max is 1,000; we run at 60% of the actual free-tier
# ceiling so the real number should be lower than the provider limit.
GLOBAL_DAILY_CREDIT_LIMIT: int = int(os.getenv("GLOBAL_DAILY_CREDIT_LIMIT", "1000"))
# Before this UTC hour, only 75% of the global budget is available — a simple
# reserve so night owls don't drain everything before the afternoon lesson.
RESERVE_HOUR_UTC: int = int(os.getenv("RESERVE_HOUR_UTC", "14"))

# Minimum seconds between metered actions for a single user (rate limit).
RATE_LIMIT_SECONDS: float = float(os.getenv("RATE_LIMIT_SECONDS", "3.0"))
# Maximum simultaneous LLM calls across the whole bot. Gemini's free tier
# allows ~10 req/min; 8 slots keeps us comfortably inside that.
LLM_CONCURRENCY_LIMIT: int = int(os.getenv("LLM_CONCURRENCY_LIMIT", "8"))
# How long (seconds) a request waits for a free concurrency slot before giving up.
LLM_QUEUE_TIMEOUT: float = float(os.getenv("LLM_QUEUE_TIMEOUT", "30.0"))

# --- Public subscription tiers (F-15, F-16, F-21) ---
# Session window: messages reset after this many hours of inactivity.
SESSION_WINDOW_HOURS: int = 3
# Per-session message caps.
SESSION_CAP_FREE: int = int(os.getenv("SESSION_CAP_FREE", "10"))
SESSION_CAP_SUBSCRIBER: int = int(os.getenv("SESSION_CAP_SUBSCRIBER", "40"))
# Per-week message caps (resets Monday 00:00 UTC).
WEEK_CAP_FREE: int = int(os.getenv("WEEK_CAP_FREE", "40"))
WEEK_CAP_SUBSCRIBER: int = int(os.getenv("WEEK_CAP_SUBSCRIBER", "200"))
# Subscription pricing.
# Stripe price in USD cents ($4.99 → 499). Set via STRIPE_TOKEN env var.
SUBSCRIBE_PRICE_USD_CENTS: int = int(os.getenv("SUBSCRIBE_PRICE_USD_CENTS", "499"))
# Telegram Stars price (250 ⭐ ≈ $6.50 — intentionally higher to signal card is better value).
SUBSCRIBE_PRICE_STARS: int = int(os.getenv("SUBSCRIBE_PRICE_STARS", "250"))
SUBSCRIBE_DAYS: int = int(os.getenv("SUBSCRIBE_DAYS", "30"))
# Stripe provider token from BotFather (empty string = Stars only).
STRIPE_TOKEN: str = os.getenv("STRIPE_TOKEN", "")
# Top-up packs: (label, extra_messages, stars_price).
TOPUP_PACKS: list[tuple[str, int, int]] = [
    ("Small",  10,  25),
    ("Medium", 30,  60),
    ("Large",  75, 120),
]
