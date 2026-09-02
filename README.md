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

## Deployment (run on another machine, develop from yours)

Karly uses long polling, so the host needs no public IP — just power and
internet. To run it 24/7 on a dedicated box (e.g. the OptiPlex) while you keep
editing from your main PC, see **[deploy/SETUP_OPTIPLEX.md](deploy/SETUP_OPTIPLEX.md)**.

Once set up, the daily loop from your dev machine is:

```bash
make deploy    # push + pull + restart the remote service
make logs      # follow live logs
make status    # is it running?
```

(Requires `export KARLY_HOST=user@host` and a one-time setup on the target.)

## Single-user access

Set `ALLOWED_USER_ID` in `.env` to your Telegram user id to lock the bot to you.
If left unset, the first person to `/start` is adopted and persisted, and
everyone else is rejected.
