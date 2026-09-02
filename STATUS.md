# Karly — Build Status & Remaining Work

Karly is a single-user German-tutor Telegram bot (see `README.md` for what it is
and how to run it, and the master plan for the full design).

## Progress

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Scaffold & plumbing (config, DB schema, auth gate, echo) | ✅ Done |
| 1 | LLM layer (Gemini + dormant Ollama + router + prompts) | ✅ Done |
| 2 | Assessment (`/test`) + conversation with corrections | ✅ Done |
| 3 | Spaced-repetition practice loop (`/practice`, `/review`, `/remind`) | ✅ Done |
| 4 | Document-driven learning (PDF upload, term extraction, `/learn`) | ✅ Done |
| 5 | Deployment & Ollama activation | 🟡 **Artifacts ready; run on OptiPlex** |

## What works today

- `/start`, `/help`, single-user auth gate (env `ALLOWED_USER_ID`, else first
  user adopted).
- `/test` — adaptive placement interview → JSON verdict → `cefr_estimate`.
  (`/assess` kept as a hidden alias.)
- `/profile` — level, per-skill, top gaps, saved-vocab count.
- Conversation mode — German replies, corrects **every** mistake (emphasis on
  grammar/word order), short English glosses where needed; corrections logged as
  vocab. `/topic`, `/english`.
- `/practice` (flashcard / cloze / LLM-checked sentence, SM-2 grading),
  `/review` (due, streak, hardest), `/remind HH:MM` (opt-in daily reminder).
- PDF upload → engineering-term extraction + summary; `/docs`, `/learn [id]`,
  `/docfocus on|off`. Document terms flow into `/practice`.
- Gemini quota (429) handled everywhere with a friendly message.
- Tests: `python -m unittest` (SM-2 + router fallback).

## Phase 5 — Deployment & Ollama

**Deploy model chosen:** the OptiPlex runs the bot as a `systemd --user` service;
you develop on your main PC and deploy over **LAN SSH** with a one-command
script. All artifacts are committed:

- `deploy/karly.service` — systemd user unit
- `deploy/deploy.sh` + `Makefile` — one-command `make deploy` (push + remote
  pull + restart), plus `make logs/status/restart/stop`
- `deploy/SETUP_OPTIPLEX.md` — full step-by-step runbook (SSH, clone, venv,
  `.env`, service, linger, Ollama)

Remaining is **operational** — run the runbook on the OptiPlex once it's ready:

### 5a. Prep the OptiPlex (SETUP_OPTIPLEX.md Parts A–B)
- [ ] Enable SSH, install git/python; note its LAN IP → `KARLY_HOST`.
- [ ] `ssh-copy-id` from this PC; clone the private repo (PAT over HTTPS).
- [ ] venv + `pip install -r requirements.txt`; copy `.env` (`scp`).

### 5b. Install the service (Part B6–B7)
- [ ] Copy `karly.service` into `~/.config/systemd/user/`,
      `systemctl --user enable --now karly`.
- [ ] `loginctl enable-linger $USER`; reboot and confirm it comes back.

### 5c. Ollama activation (Part D)
- [ ] Install Ollama; `ollama pull qwen2.5:3b-instruct`.
- [ ] `make restart`; confirm logs show "Ollama is available".
- [ ] Verify quota fallback lands on Ollama (temporarily break the Gemini key).

### 5d. Final verification
- [ ] `make deploy` round-trip works from this PC.
- [ ] Reboot survives; bot responds on Telegram.

## Known deviations from the original plan

- **Model:** plan said `gemini-2.5-flash`, but Google retired it for new API
  keys (404). Karly uses **`gemini-3.6-flash`** (config default + `.env`).
- **`/assess` renamed to `/test`** (alias kept) per user request.
- **Extra schema** added in Phase 3 (all additive): `User.reminder_time`,
  `PracticeLog` table (for the streak). `python-telegram-bot[job-queue]` extra
  added for reminders.

## Notes / possible future improvements

- SM-2 grading of typed cloze/sentence answers is auto-mapped (correct→Gut,
  wrong→Nochmal); could add manual override buttons.
- Reminder times use the **server's local timezone**.
- OCR for scanned PDFs is intentionally out of scope.
- Conversation context window is the last 20 messages (free-tier friendly).
