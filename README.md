# Karly — German Tutor Telegram Bot

A single-user Telegram bot that helps polish German with a focus on engineering
vocabulary and certification prep. AI backend is hybrid: Google Gemini free tier
for conversation/assessment/document analysis, with a local Ollama model for
quick lookups and quota fallback (activated in Phase 5).

## Status

Phase 0 — Scaffold & plumbing (in progress).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Then edit .env and fill in:
#   TELEGRAM_BOT_TOKEN  — from @BotFather on Telegram
#   GEMINI_API_KEY      — from https://aistudio.google.com
```

## Run

```bash
source .venv/bin/activate
python -m bot.main
```

The SQLite database (`karly.db`) is created automatically on first run.

## Single-user access

Set `ALLOWED_USER_ID` in `.env` to your Telegram user id to lock the bot to you.
If left unset, the first person to `/start` is adopted and persisted, and
everyone else is rejected.
