# Karly — Future Work

Backlog of known issues and wanted features, captured 2026-09-02. Each item
records *what*, *why it matters*, and *concrete starting points*, so whoever
picks it up (including a future Claude session) doesn't have to re-derive the
diagnosis.

See `STATUS.md` for the phased build history; this file is for work that comes
after Phase 5.

---

## 1. SECURITY — Telegram bot token is written to the system journal

**Severity: high. Do this first.**

`python-telegram-bot` talks to Telegram over `httpx`, and `httpx` logs every
request line at `INFO`. Because the bot token is part of the Telegram API *URL
path*, every poll writes the full token into journald:

```
INFO httpx: HTTP Request: POST https://api.telegram.org/bot<TOKEN>/getUpdates "HTTP/1.1 200 OK"
```

`bot/main.py` calls `logging.basicConfig(level=logging.INFO)`, which applies to
third-party loggers too, so this is on by default. With long polling this
repeats roughly every 10 seconds, so the token is smeared across the entire
journal history.

**Why it matters:** anyone who can read your user journal can extract the token
and take full control of the bot — read every message you've sent it, send
messages as it, or hijack it entirely. It also lands in any journal export,
backup, or log bundle you might share while debugging.

**Fix (small):** in `bot/main.py`, right after `logging.basicConfig(...)`, quiet
the HTTP client loggers:

```python
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
```

This keeps Karly's own INFO logs intact while dropping the token-bearing lines.
Verify with:

```bash
journalctl --user -u karly --since "-5 min" | grep -c "api.telegram.org"   # expect 0
```

**Also required — the token is already leaked into existing history:**

1. Rotate the token with `@BotFather` (`/revoke` → `/token`), then update
   `TELEGRAM_BOT_TOKEN` in `.env` and `systemctl --user restart karly`.
2. Clear the old journal entries, e.g. `journalctl --user --vacuum-time=1s`
   (nukes *all* your user-journal history, so weigh that) or simply accept the
   old token becomes worthless once rotated — rotation alone is sufficient
   protection, vacuuming is just hygiene.

Do the code fix *before* rotating, otherwise the fresh token is immediately
leaked the same way.

---

## 2. Responses are too slow

**Measured 2026-09-02** (real timed calls, same prompt, empty history):

| Backend | Model | Time | Output |
|---|---|---|---|
| Gemini (cloud) | `gemini-3.6-flash` | **24.3 s** | ~450 chars |
| Ollama (local) | `llama3.2:3b-instruct-q4_K_M` | **76.8 s** / **69.6 s** | ~300-600 chars |

Gemini's 24 s is with *empty* history and short output — that's the floor, not
the worst case. Real turns carry up to 20 messages of history and generate more
text.

**The local model is ~3x slower than the cloud, not faster.** This box has no
GPU (Intel integrated only), a 4-core i5-4590T @ 2.0 GHz from 2014, and ~1 GB
RAM free of 7 GB total; Ollama reports `size_vram=0`, i.e. running fully on CPU.
The bigger `llama3.1:8b-instruct-q4_K_M` that's also pulled would be slower
still and would likely thrash given the available RAM. Do **not** assume
"local = fast" here — it isn't, and any plan built on that assumption will make
things worse.

### Root causes, most significant first

**a. Output length dominates.** `TUTOR_PERSONA` in `llm/prompts.py` (~1.4 k
chars) instructs the model to correct *every* mistake with a per-line
explanation *before* the conversational reply. Generation time scales with
output tokens, so the correction block roughly doubles each response. Item 3
below (toggling corrections off) is therefore also the **single most promising
performance fix**, and it needs no new infrastructure.

**b. The typing indicator expires long before the reply lands.**
`send_chat_action("typing")` is sent once (`conversation.py:99`) but Telegram
clears it after ~5 s. On a 24 s reply the chat looks *dead* for ~19 s, which
feels far worse than the raw number. Cheapest perceived-speed win available,
and independent of any real optimisation.

**c. Full history is resent every turn.** `CONTEXT_WINDOW_MESSAGES = 20` in
`config.py`; `conversation.chat` passes `recent_history(...)` on every call, so
input grows until it saturates at 20 messages. Trimming this cuts input cost,
though output length (a) matters more.

**d. Gemini free tier is capped at 20 requests/day for this model** — a
*separate* problem that shares a solution space with latency. Hit during
testing:

```
429 RESOURCE_EXHAUSTED — quota metric: generate_content_free_tier_requests,
limit: 20, model: gemini-3.6-flash
```

Twenty messages is less than one real practice session, so the bot goes dead
partway through most days and shows `QUOTA_MSG`. Arguably a bigger day-to-day
problem than the latency.

### Suggested approach

1. **Shorten the output** — implement item 3 (corrections off) and measure the
   Gemini turn again. Fewer output tokens is the most direct latency win and
   costs nothing architecturally.
2. **Keep the typing indicator alive** — re-send `send_chat_action` on a ~4 s
   loop while awaiting the LLM. Doesn't make it faster, makes it *feel* far less
   broken.
3. **Stream the reply**, or at minimum send corrections and the conversational
   reply as two separate messages, so the first text arrives sooner.
4. **For the quota cap, not for speed:** Ollama is the only local fallback, but
   accept it as a ~3x latency hit — a slow answer beats `QUOTA_MSG`. Options,
   roughly in order of appeal:
   - Raise the cap: a different free-tier Gemini model with a higher daily
     limit, or a second API key/project.
   - Route only *cheap, short* tasks (`lookup`, `check` — already Ollama-bound
     in `llm/router.py`) locally, keeping conversation on Gemini.
   - Fall back to Ollama for chat *only* once Gemini 429s, which
     `llm/router.py` already does — verify that path actually works end-to-end,
     since it's the difference between "slow" and "dead".
   - Better hardware (a GPU box, or the OptiPlex if it's stronger) would change
     this calculus entirely — re-measure there before deciding.
5. **Re-measure after each step.** The numbers above are real timings, not
   estimates; beat them rather than guessing.

**Config trap:** `config.py` defaults `OLLAMA_MODEL` to `qwen2.5:3b-instruct`,
which is **not** among the locally pulled models
(`llama3.1:8b-instruct-q4_K_M`, `llama3.2:3b-instruct-q4_K_M`). `.env` overrides
it correctly, so it works today, but a fresh install without that `.env` line
would fail at first use. Worth aligning.

---

## 3. Toggle corrections on/off, with an end-of-session summary

**Wanted behaviour:** a command to turn grammar corrections off so conversation
can flow naturally, and — when they're off — a summary at the end of what was
gotten wrong and is worth working on.

This is both a UX feature *and* a speed improvement (see 2c): with corrections
suppressed, the model writes far fewer output tokens per turn.

### Design sketch

- **Command:** `/corrections on|off` (mirrors the existing `/docfocus on|off`
  in `bot/handlers/documents.py` — reuse that shape and its
  `context.user_data` pattern). Consider persisting to `User` instead of
  `user_data` so the setting survives restarts, the way `reminder_time`
  already does.
- **Prompt switching:** `TUTOR_PERSONA` currently hardcodes the correction
  rules. Split it into a base persona plus an appendable "correction block", and
  only include the block when corrections are on. When off, add an explicit
  instruction *not* to correct inline.
- **Still detect mistakes silently.** For the end-of-session summary to work,
  errors must be captured even when not shown. Two options:
  - *Cheap:* keep asking the model for corrections but in a machine-readable
    trailer that the bot strips before replying — no extra API call, but output
    tokens (and latency) stay high, losing the speed benefit.
  - *Better:* let the conversation run clean, then at summary time send the
    session's user messages in **one** batch to the LLM for analysis. One extra
    request per session instead of per turn — strictly better for both latency
    and the 20/day quota.
- **Summary trigger:** `/summary` on demand, and/or automatically when
  corrections are toggled back on or after N minutes idle. Group by error type
  (word order, cases, adjective endings, separable verbs — the categories
  `TUTOR_PERSONA` already emphasises) rather than listing raw mistakes, so it
  reads as "what to work on" rather than a wall of errors.
- **Feed it back into practice.** Corrections already flow into vocab via
  `_parse_corrections` → `add_vocab_items(..., source=VocabSource.conversation)`
  (`bot/handlers/conversation.py`). Whatever the summary path produces should
  land in the same place so mistakes still enter the SM-2 practice loop —
  otherwise turning corrections off silently stops the spaced-repetition system
  from learning what you struggle with.

### Watch out for

`_parse_corrections` relies on the exact `❌ … → ✅ … — reason` line format. Any
prompt change risks silently breaking that regex, which would quietly stop vocab
capture (no error, just nothing saved). Cover it with a test — `tests/` already
uses `python -m unittest`.
