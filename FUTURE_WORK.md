# Karly — Future Work

The single living backlog for Karly. Records *what*, *why it matters*, and
*concrete starting points* so whoever picks an item up (including a future
Claude session) doesn't have to re-derive the diagnosis.

The full phased build history lived in the old `STATUS.md` (Phases 0–5, all
done and deployed to the OptiPlex); that file has been folded into this one.

---

## ✅ Done — 2026-09-02

These were the top three backlog items; all implemented and deployed.

### 1. Telegram token no longer written to the journal
`bot/main.py` now quiets the `httpx`/`httpcore` INFO loggers, so the token
(which sits in the Telegram API URL path) never lands in journald. Verify:

```bash
journalctl --user -u karly --since "-5 min" | grep -c "api.telegram.org"   # 0
```

**Still recommended (operational, not code):** rotate the token with
`@BotFather` (`/revoke` → `/token`), update `.env`, `make restart` — the code
fix stops *new* leaks but the old token is already in existing history.
Optionally `journalctl --user --vacuum-time=1s` for hygiene.

### 2. Corrections toggle + session summary  (also the main latency win)
- `/corrections on|off` — persisted on `User.corrections_on` (survives
  restarts; SQLite column auto-added by `db/session.py:_apply_migrations`).
- `TUTOR_PERSONA` split into base + `CORRECTION_BLOCK` / `NO_CORRECTION_NOTE`
  in `llm/prompts.py`; when off, the model is told not to correct inline, so it
  writes far fewer output tokens per turn.
- `/summary` sends the recent user messages in **one** batch to the LLM
  (`SESSION_SUMMARY` prompt → JSON), groups mistakes by type, and feeds the
  corrections back into the same `add_vocab_items(source=conversation)` SM-2
  pipeline — so turning corrections off doesn't stop spaced repetition from
  learning your weak spots. One request per session, not per turn (kinder to
  the 20/day quota).
- `tests/test_corrections.py` guards the `❌ … → ✅ … — reason` parse format.

### 3. Perceived-latency + config fixes
- Typing indicator now kept alive on a 4 s loop while awaiting the LLM
  (`_keep_typing` in `bot/handlers/conversation.py`) — a 24 s reply no longer
  looks dead. Applied to chat, `/english`, and `/summary`.
- `config.py` / `.env.example` default `OLLAMA_MODEL` aligned to
  `llama3.2:3b-instruct-q4_K_M` (the model actually pulled on the OptiPlex), so
  a fresh install without an `.env` override no longer fails at first use.

---

## Still open

### A. Real latency (not just perceived)
Item 2 above shortened output, which is the biggest lever, but the floor is
still high on this hardware. Remaining ideas, roughly in order of appeal:
- **Stream the reply**, or send corrections and the conversational reply as two
  separate messages, so the first text arrives sooner.
- Trim `CONTEXT_WINDOW_MESSAGES` (currently 20 in `config.py`) — input cost,
  smaller lever than output length.
- Re-measure on the OptiPlex after each change; don't guess. Baseline (dev box,
  empty history): Gemini `gemini-3.6-flash` ~24 s; Ollama `llama3.2:3b` ~70 s
  (CPU-only, no GPU) — local is ~3× *slower*, so it's a quota fallback, not a
  speed play.

### B. Gemini free-tier quota (20 requests/day)
Less than one real practice session, so the bot goes dead partway through most
days (`429 RESOURCE_EXHAUSTED`, `QUOTA_MSG`). `llm/router.py` already falls back
to Ollama on 429 — verify that path end-to-end (the difference between "slow"
and "dead"). Also consider a higher-limit free model or a second key/project.

### C. Nice-to-haves
- Auto-trigger `/summary` when corrections are toggled back on, or after N
  minutes idle (currently on-demand only).
- Manual SM-2 override buttons for typed cloze/sentence answers (auto-mapped
  correct→Gut, wrong→Nochmal today).
- Reminder times use the server's local timezone (fine for single-user).
- OCR for scanned PDFs — intentionally out of scope.
