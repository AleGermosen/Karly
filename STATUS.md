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
| 5 | Deployment & Ollama activation | ⬜ **Not started** |

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

## Phase 5 — Remaining work (do this ON the target machine / OptiPlex 3020M)

The LLM router already has Ollama hooks built and dormant; it health-checks on
startup and routes everything to Gemini while Ollama is unreachable. Phase 5 is
about deployment and turning Ollama on.

### 5a. Setup-from-scratch (already partly in README)
- [ ] Verify `README.md` steps on a fresh clone: venv, `pip install -r
      requirements.txt`, `.env` from `.env.example`, BotFather token, Gemini key.
- [ ] Confirm first run auto-creates `karly.db`.

### 5b. systemd user service (survive reboots, no public IP needed)
- [ ] Add `deploy/karly.service` (systemd **user** unit) running
      `python -m bot.main` with the project venv, `WorkingDirectory` set, and
      `Restart=on-failure`.
- [ ] Install instructions:
      `systemctl --user enable --now karly` and
      `loginctl enable-linger $USER` (so it runs without an active login).

### 5c. Ollama activation
- [ ] Install Ollama; `ollama pull qwen2.5:3b-instruct`.
- [ ] Confirm `OLLAMA_BASE_URL` / `OLLAMA_MODEL` in `.env` match.
- [ ] On startup the router health-check flips Ollama **active** automatically —
      verify `lookup` / `check` tasks route locally.
- [ ] Verify Gemini-quota fallback now lands on Ollama (temporarily break the
      Gemini key and confirm the bot still answers via Ollama).

### 5d. Final verification
- [ ] Fresh-machine dry run of the README.
- [ ] Reboot; confirm the service comes back up.

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
