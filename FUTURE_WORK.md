# Karly — Roadmap & Status

*Last updated: 2026-09-04*

---

## TL;DR — What's pending right now

> Everything above the line is the working list. Scan this first every session.

### 🔴 Bugs — confirmed, not yet fixed

| # | Bug | Where | Impact |
|---|-----|--------|--------|
| **B-1** | Roleplay turns and `/summary`, `/learn` cost 0 credits — budget leak | `roleplay.py`, `conversation.py`, `documents.py` | Medium — a student can bypass the credit system entirely via roleplay |
| **B-2** | Token cap for `assess` (512) may truncate verdict JSON; Gemini burns cap on thinking tokens | `router.py` `_TASK_MAX_TOKENS` | Medium — `/test` can silently fail when Groq is exhausted |
| **B-3** | Daily cache hits still charge full 2 credits; shared prompt bakes in one student's gaps | `daily.py` | Low — price cache hits at 1 credit; drop personal gaps from the shared prompt |
| **B-4** | Deck picker reverse-direction buttons hardcode `deck:all:rev`, ignoring specific deck choice | `practice.py` | Low |
| **B-5** | `telegram_id` and `approved_by` columns are `Integer` — overflows for new Telegram accounts (>2³¹) | `db/models.py` | Low now, breaks on Postgres migration |
| **B-6** | `get_or_create_user` never updates a user's name if it changed in Telegram | `db/repo.py` | Low |
| **B-7** | Job-queue extra (`python-telegram-bot[job-queue]`) — if not installed, `/remind` silently does nothing | `deploy/` | Operational — verify on OptiPlex |

### 🟡 Features — planned, not started

| # | Item | Priority | Notes |
|---|------|----------|-------|
| **F-1** | `/english` block in English mode — redirect to `/spanish` | Low | One-liner in `conversation.py` |
| **F-2** | Bilingual stale-correction message | Low | `conversation.py` — currently German-only |
| **F-3** | Backend notices in Spanish for English-mode students | Low | `_BACKEND_NOTICES` in `conversation.py` |
| **F-4** | Games section in `/help` and `/start` — The Impostor is invisible | Medium | `start.py`, `MENU_COMMANDS` in `main.py` |
| **F-5** | Correction strictness defaults from placement test (S.7) | Medium | Suggest level in `_finish()` |
| **F-6** | Teacher sets class default correction level (S.8) | Low | After S.7 |
| **F-7** | One-time correction nudge after first correction (S.9) | Low | `conversation.py` |
| **F-8** | First-5-minutes onboarding for newly approved students (Step 0.2) | Medium | `start.py` — approved students get a structured start sequence |
| **F-9** | Nightly database backup (Step 0.7) | High | `deploy/` — `karly.db` holds student work; a nightly copy is free insurance |
| **F-10** | Consent line in welcome message (Step 0.8) | Medium | One sentence at `/start`: what the teacher can see |
| **F-11** | `/mybudget` for students — show their own remaining credits | Low | New command; reuses `credits_remaining()` |
| **F-12** | Show correction level in `/profile` | Low | One line; helps students understand their current setting |
| **F-13** | Voice notes — speak German/English, get a text correction back | Future | Groq Whisper → existing correction pipeline |
| **F-14** | Assignments + CSV export (Step 6) | Future | After curriculum phase exists |

### ✅ Recently fixed (this session)

| Fix | What changed |
|-----|-------------|
| **Buttons not responding** | `require_auth` wrapper discarded handler return values — ConversationHandlers never entered their states. Fixed: `return await handler(...)` |
| **Roleplay silent after first turn** | History dicts used `"content"` key; all backends expect `"text"`. Fixed in `scene_message` and `scene_done` |
| **Roleplay corrections never fired** | `_correction_block()` compared integer (0–5) against strings. Fixed: now calls `prompts.build_correction_block(level, english=en)` |
| **Asterisks instead of bold text** | No `parse_mode` set anywhere. Fixed: `Defaults(parse_mode=ParseMode.MARKDOWN)` in `Application.builder()` |
| **Credit exhaustion buttons broken** | `switch_inline_query_current_chat` requires inline mode and puts text in input field — an error loop. Fixed: `callback_data` buttons with `on_free_feature_tap` handler |
| **`/start` showed picker to returning users** | Both branches were identical. Fixed: returning users see the welcome/commands message |
| **Button spinner on blocked taps** | Middleware returned early without calling `query.answer()`. Fixed: `_dismiss_button()` called in every early-return branch |
| **German reminders for English-mode students** | Reminder text was always German. Fixed: mode-aware text in `_send_reminder()` |
| **Assessment starts too hard, asks to describe things** | Started at A2, allowed open/production questions. Fixed: starts at A1, MCQ and fill-in-the-blank only, auto-graded |

---

## What's working today

**Dual-language tutor:** German mode (English speaker learning German) and English mode (Spanish speaker learning English) — both fully featured.

**Core features:** adaptive placement test (A1 start, MCQ + fill-in-the-blank, auto-graded), spaced-repetition flashcards (HLR scheduler, MCQ/cloze/sentence modes, deck picker, direction flip), daily mini-challenge (shared per level, cached), rapid skill quiz, roleplay scenes (6 German + 6 English scenarios, corrections at right level), weekly progress report, PDF vocabulary extraction, The Impostor social deduction game, BKT skill mastery, DKT LSTM (gated, activates at 50+ reviews).

**Classroom controls:** roster + roles, approval flow (`ACCESS_MODE=approval`), teacher dashboard (`/students`, `/student`, `/class`, `/budget`, `/grant`), per-student daily credit cap, global ceiling with reserve pool, rate limiting, concurrency queue, streak bonus, low-balance nudge.

**Backend ladder:** Groq 120b → Groq 20b → Gemini 3.6-flash → Ollama (chat only). Per-rung cooldowns in-process.

---

## Bug detail

### B-1 — Unmetered LLM usage (budget leak)

These handlers make LLM calls but have no `credits_check()` or `spend()`:

| Handler | Function | Has credit gate? |
|---------|----------|-----------------|
| `roleplay.py` | `_launch_scene`, `scene_message`, `scene_done` | ❌ No |
| `conversation.py` | `summary()` | ❌ No (cost defined in `COSTS` but never charged) |
| `documents.py` | `learn()` | ❌ No (cost defined in `COSTS` but never charged) |
| `conversation.py` | `english()`, `spanish()` | ❌ No |

Fix: add `credits_check` + `spend` calls to each, following the same pattern as `chat()`.

### B-2 — Token cap may break `/test` and Gemini structured tasks

`_TASK_MAX_TOKENS["assess"] = 512` is tight for the verdict JSON (skills + gaps + summary). Gemini 2.5/3.x models may consume the entire `max_output_tokens` budget on internal thinking tokens and return empty text, causing `LLMUnavailable` and falling through to Ollama — which can't produce JSON.

Fix: raise `assess` to 1024; consider passing a higher or uncapped limit to the Gemini rung specifically.

---

## Future directions

### Correction strictness — remaining tasks (S.7–S.9)

| # | Task | Notes |
|---|------|-------|
| **S.7** | Suggest correction level from placement test result | In `_finish()`: map CEFR level to suggested dial value; show as a one-time nudge |
| **S.8** | Teacher sets class default level | New env var or `/class setcorr <n>`; student can override |
| **S.9** | Mention corrections once, early | First time a correction fires, append: *"You can adjust correction detail with /corrections 0–5"* |

### Engineering quality

| Idea | Value |
|------|-------|
| `TypedDict` for history message dicts | Prevents the `"content"` vs `"text"` class of bug at type-check time |
| Ladder health check in `/status` | Show which rungs were recently poisoned by exceptions and why — the roleplay bug was invisible because failures silently become cooldowns |
| Smoke-test script (`scripts/smoke.py`) | Drive every handler once with a fake LLM backend; catches KeyError, wrong return types, missing credit gates without needing Telegram |
| Centralize credit metering | A single decorator/helper that wraps metered LLM calls — instead of each handler remembering to call `credits_check` + `spend`. The B-1 leak exists because the pattern is copy-paste |

### Voice notes (future)

Let students speak a German or English sentence and receive a text correction back.
- Input: Telegram voice message → Groq Whisper → text → existing correction pipeline
- Output (optional): Gemini TTS → voice reply
- Gate: `filters.VOICE` handler in `main.py`

### Curriculum phase (future)

A topic list per CEFR level with a short lesson and a set of banked exercises each — the way test-english.com is organised, written once into the repo instead of invented live. This is the single biggest capacity multiplier: banked exercises cost 0 credits to serve. See `CURRICULUM_PLAN.md`.

### Scale phase (when ready to open to the public)

1. **Multi-tenant foundation** — SQLite → Postgres (Neon free tier); fix sync SQLAlchemy in async handlers
2. **Usage metering** — already done (`LLMUsage` table); wire into entitlements
3. **Entitlements + gating** — `subscriptions` table; free tier = N msgs/day; paid = unlimited
4. **Telegram Stars payments** — `/subscribe` → recurring invoice → `successful_payment` handler
5. **Infrastructure** — long-polling → webhooks; Redis for cross-instance rate-limiting and durable cooldowns; cloud VM

---

## Technical notes (for future sessions)

**Why Ollama is excluded from structured tasks:** the local 3B model can't reliably produce valid JSON. Structured ladder (`Task.assess`, `Task.analyze`) stops at Gemini; Ollama only appears in `Task.chat`, `Task.generate`, `Task.lookup`, `Task.check`.

**Groq compound models 404:** `groq/compound` and `groq/compound-mini` are agentic systems — they 404 on `/v1/chat/completions`. Use `openai/gpt-oss-120b` and `openai/gpt-oss-20b`.

**BKT CEFR level tracking:** each BKT observation records the CEFR level of the item answered. "Grammar: 70%" means 70% mastery at A2, not a global score. A graduated BKT (separate instance per skill+level, graduating up at p > 0.95) is future work.

**SM-2 kept alongside HLR:** `apply_hlr_grade` runs both. SM-2 easiness/interval fields stay current so `/review` stats keep working.

**Reminder timezone:** stored as `HH:MM` in server local time. Fine for one timezone; needs per-user timezone when multi-tenant.

**Capacity at a glance:**

| | 50 daily students |
|---|---|
| No gates | ❌ Exhausts free tier |
| With credit gates (T.1–T.5) | ✅ Fits at ~20 credits each |
| With gates + shared daily cache (T.1–T.8) | ✅ Comfortable |
| + Groq Developer tier (free, add a card) | ✅ Comfortable at 100+ |
| + ~$27/month | ✅ Stop thinking about it |
