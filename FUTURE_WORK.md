# Karly — Roadmap & Status

*Last updated: 2026-09-04*

---

## TL;DR — What's pending right now

> Everything above the line is the working list. Scan this first every session.

### 🔴 Bugs — confirmed, not yet fixed

| # | Bug | Where | Impact |
|---|-----|--------|--------|
| **B-6** | `get_or_create_user` never updates a user's name if it changed in Telegram | `db/repo.py` | Low |
| **B-7** | Job-queue extra (`python-telegram-bot[job-queue]`) — if not installed, `/remind` silently does nothing | `deploy/` | Operational — verify on OptiPlex |

### 🟡 Features — planned, not started

| # | Item | Priority | Notes |
|---|------|----------|-------|
| **F-1** | `/english` block in English mode — redirect to `/spanish` | Low | One-liner in `conversation.py` |
| **F-2** | Bilingual stale-correction message | Low | `conversation.py` — currently German-only |
| **F-3** | Backend notices in Spanish for English-mode students | Low | `_BACKEND_NOTICES` in `conversation.py` |
| **F-6** | Teacher sets class default correction level | Low | New command `/class setcorr N`; student can override |
| **F-13** | Voice notes — speak German/English, get a text correction back | Future | Groq Whisper → existing correction pipeline |
| **F-14** | Assignments + CSV export | Future | After curriculum phase exists |

### ✅ Recently completed (this session)

| Fix | What changed |
|-----|-------------|
| **Multi-teacher architecture** | Superuser role, `/addteacher`, `/removeteacher`, `/teachers`, multi-step approval (approve → teacher → class), per-teacher class management |
| **Class management** | `/newclass [german\|english]`, `/classes`, `/moveclass`, `/assign` scoped per teacher, `/classtopic` |
| **F-9 Nightly DB backup** | `deploy/karly-backup.{sh,service,timer}` — sqlite3 backup at 03:00, 14-day rolling window |
| **B-1 Credit leak fixed** | Roleplay turns, `/english`, `/spanish`, `/summary`, `/learn` now all check and spend credits |
| **B-2 Token cap raised** | `Task.assess` 512 → 1024 — fixes silent `/test` failures on Gemini |
| **B-3 Cache credit fixed** | `/daily` cache hit costs 1 credit; fresh generation costs 2 |
| **B-4 Deck picker fixed** | Each deck now shows fwd (→) and rev (←) buttons — any deck, any direction |
| **B-5 BigInteger** | `telegram_id` and `approved_by` changed to `BigInteger` — safe for new Telegram accounts |
| **F-4 Impostor visible** | `/impostor` added to German welcome message |
| **F-5 Correction nudge from test** | After `/test`, correction level auto-set to match CEFR result; student notified |
| **F-8 Student onboarding** | Approved students get a structured 4-step welcome instead of the generic message |
| **F-10 Consent line** | Welcome messages explain what the teacher can (and cannot) see |
| **F-11 `/mybudget`** | Students can check remaining credits, streak bonus, and cost table |
| **F-12 Correction level in profile** | `/profile` shows current correction level (n/5 + label) |
| **S.9 Corrections nudge** | First correction each session → one message explaining `/corrections 0–5` |
| **`/help` markdown fix** | Angle brackets in help text were breaking Telegram's Markdown parser |

---

## What's working today

**Dual-language tutor:** German mode (English speaker learning German) and English mode (Spanish speaker learning English) — both fully featured.

**Core features:** adaptive placement test (A1 start, MCQ + fill-in-the-blank, auto-graded), spaced-repetition flashcards (HLR scheduler, MCQ/cloze/sentence modes, deck picker with per-deck fwd/rev direction), daily mini-challenge (shared per level, cached), rapid skill quiz, roleplay scenes (6 German + 6 English scenarios, corrections at right level), weekly progress report, PDF vocabulary extraction, The Impostor social deduction game, BKT skill mastery, DKT LSTM (gated, activates at 50+ reviews).

**Classroom controls:** superuser + teacher roles, multi-step approval flow (approve → assign teacher → assign class), per-teacher class management (`/newclass`, `/classes`, `/moveclass`, `/assign`), drill topic per class, roster views, skill error rates dashboard, per-student daily credit cap, global ceiling with reserve pool, rate limiting, concurrency queue, streak bonus, low-balance nudge, `/mybudget` for students.

**Backend ladder:** Groq 120b → Groq 20b → Gemini 3.6-flash → Ollama (chat only). Per-rung cooldowns in-process.

---

## Future directions

### Engineering quality

| Idea | Value |
|------|-------|
| `TypedDict` for history message dicts | Prevents the `"content"` vs `"text"` class of bug at type-check time |
| Ladder health check in `/status` | Show which rungs were recently poisoned by exceptions and why |
| Smoke-test script (`scripts/smoke.py`) | Drive every handler once with a fake LLM backend; catches KeyError, wrong return types, missing credit gates |
| Centralize credit metering | A single decorator that wraps metered LLM calls — prevents future B-1-style leaks |

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

**BKT CEFR level tracking:** each BKT observation records the CEFR level of the item answered. "Grammar: 70%" means 70% mastery at A2, not a global score.

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
