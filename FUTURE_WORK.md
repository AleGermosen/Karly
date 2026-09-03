# Karly — Roadmap & Future Work

Living plan for Karly's evolution. Updated 2026-09-03.

---

## TL;DR

**What's working today:** Full German tutor bot — conversation with inline corrections, adaptive placement test, spaced-repetition flashcards (HLR scheduler, MCQ mode, deck picker, DE↔EN flip), daily challenge, rapid quiz targeting weak skills, roleplay scenes, weekly progress report, BKT skill mastery, DKT LSTM (gated), PDF vocabulary extraction, systemd deploy on OptiPlex.

**What to build next (solo phase):**
1. Voice notes — speak German, get a text correction back
2. Assessment JSON hardening — retry/skip on bad output instead of raw dump
3. Manual grade override buttons on typed answers

**When you're ready to open to other users:**
→ Multi-tenant foundation → Usage metering → Entitlements → Telegram Stars payments

---

## Vision

Turn Karly into a subscription SaaS: many Telegram users, **Groq as the primary LLM** (sub-2s replies are the product's edge), sold via **Telegram Stars**. Build only as far as demand justifies.

**Locked decisions:**

| Decision | Choice |
|---|---|
| First scale target | Paid beta — ≤ hundreds of users |
| Payments | Telegram Stars (native, recurring) |
| Free vs paid split | Same model quality for all; gate on volume + features |
| Primary LLM | Groq `openai/gpt-oss-120b` (fallback `openai/gpt-oss-20b`). Note: `groq/compound*` are agentic systems, not chat-completion — they 404 on `/chat/completions`. |

---

## Current system snapshot

### Backend ladder (live)

```
⚡ Groq (openai/gpt-oss-120b)     — primary; fast
⚡ Groq Mini (openai/gpt-oss-20b) — Groq 120b daily limit hit
🤖 Gemini (gemini-3.6-flash)      — both Groq limits hit
🐌 Ollama (local 3B)              — last resort; chat only
```

Ollama is excluded from structured tasks (`/test`, doc analysis) — the 3B model can't reliably produce JSON. Per-rung cooldowns are in-process only; they reset on restart (Redis moves this in Phase B).

### Cost today

| Scenario | Volume | LLM cost | Infra |
|---|---|---|---|
| Just me (now) | ~1,500 turns/mo | $0 (free tier) | $0 |
| Beta (hundreds) | 60k turns/mo | ~$20–100/mo | ~$10–20/mo |
| Scale (thousands) | 600k turns/mo | ~$200–950/mo | ~$100–300/mo |

One tutor turn ≈ 2,000 input + 500 output tokens. Verify Groq rates at console.groq.com — they change.

---

## Solo phase — what to build next

These are quality improvements that make sense before opening to other users.

### Voice notes (STT/TTS)

Let AJ speak a German sentence and receive a text correction back. Optionally have Karly read her reply aloud.

- **Input:** Telegram voice message → Groq Whisper (or Google STT) → text → normal correction pipeline
- **Output (optional):** Gemini TTS or gTTS → send voice reply
- **Gate:** voice message handler in `bot/main.py` (`filters.VOICE`); transcription replaces the text message in the conversation flow
- **Why:** speaking practice is the hardest skill to drill over text; this is the highest-impact stretch feature

### Assessment JSON hardening

When the LLM returns malformed JSON during `/test`, the current fallback dumps the raw string as an open item. Better: retry once with a simpler prompt, then skip the item entirely if it still fails.

- File: `bot/handlers/assessment.py` → `_next_item()`
- One retry with a stripped-down prompt; skip + log on second failure

### Manual grade override on typed answers

Cloze and sentence answers are auto-mapped to grade 2 (wrong) or 4 (correct). Power users want to say "I knew it but typed it wrong" → grade 5.

- After feedback is shown, append the grade buttons (`_grade_keyboard()`) so the user can override before advancing
- Small change to `on_typed()` in `practice.py`

---

## Scale phase — open to other users

> **Don't touch until you're ready to invite the first beta users.** While it's just you, none of this is worth building — the bot works fine as-is.

### Step 1 — Multi-tenant foundation

- Remove the single-user gate; every Telegram user auto-provisions a `User` row
- **SQLite → Postgres** (Neon free tier to start)
- **Fix sync SQLAlchemy in async handlers** — fine at one user, blocks the event loop under concurrency; this is the main lift

### Step 2 — Usage metering

One row per LLM call (`user_id, model, tokens_in, tokens_out, task, ts`). The router already returns `RouteResult` with token counts — the handler just needs to persist them. Prerequisite for entitlements.

### Step 3 — Entitlements + gating

`subscriptions` table; extend `require_auth` → `require_tier` / `check_quota`. Free = N msgs/day, no PDF, no `/summary`; paid = unlimited, PDFs, priority.

### Step 4 — Telegram Stars payments

`/subscribe` sends a recurring Stars invoice; handle `pre_checkout_query` → `successful_payment` → renewal/cancel; grace period + auto-downgrade on lapse.

### Step 5 — Cross-cutting (required at beta)

- Privacy policy + ToS (storing user writing + taking payment; GDPR export/delete is easy given the per-`user_id` schema)
- Hard per-user daily cost cap — one runaway user burns Groq budget
- Move to a cloud VM/container; OptiPlex becomes dev/staging

### Step 6 — Infrastructure (Phase B/C, when needed)

- Long-polling → webhooks + stateless instances behind a load balancer
- Redis for cross-instance rate-limiting and durable `LadderState` (cooldowns survive restarts)
- Durable reminder scheduler (current in-process job-queue doesn't survive multi-instance)
- Read replicas, response streaming, multi-region

---

## ML roadmap

All three stages are approved and architecturally designed. Stages 1 and 2 are **live**. Stage 3 is built but gated.

### Stage 1 — HLR recall scheduler ✅ Live

`srs/hlr.py` replaces SM-2's fixed-multiplier with a per-item memory half-life. Every review logs to `ReviewLog`; `apply_hlr_grade` updates both HLR and SM-2 (for stats compatibility).

### Stage 2 — BKT skill mastery ✅ Live

`srs/bkt.py` tracks mastery probability per skill (grammar / reading / comprehension / production / functional / vocab) using classic Bayesian Knowledge Tracing. Updates fire after every assessment item and quiz answer. State is stored in `ConceptMastery` as `{skill: {p, level}}` — the CEFR level of the item is recorded alongside the probability so `/profile` shows e.g. `Grammar (A2): ███████░░░ 70%`. Powers `/quiz` target selection.

### Stage 3 — DKT LSTM (TensorFlow) ⏳ Built, gated

`srs/dkt.py` implements an LSTM over the user's full review sequence. Gated behind: (a) TensorFlow importable and (b) ≥ 50 reviews logged. With a single user the model will overfit; it becomes meaningful at multi-user beta scale. `review_history_for_dkt()` in `repo.py` builds the training data. No action needed — it activates automatically when the gate opens.

---

## Technical notes

These are implementation details worth preserving so future sessions don't re-derive them.

### Why Ollama is excluded from structured tasks

The local 3B model cannot reliably produce valid JSON. During assessment it returned an answer instead of a question (the JSON blob was the answer string). The structured ladder (`Task.assess`, `Task.analyze`) stops at Gemini; Ollama only appears in `Task.chat`, `Task.generate`, `Task.lookup`, `Task.check`.

### Groq compound models

`groq/compound` and `groq/compound-mini` are agentic systems, not chat-completion endpoints — they return 404 on `/v1/chat/completions`. Use `openai/gpt-oss-120b` and `openai/gpt-oss-20b` instead. Check `config.py` defaults and the OptiPlex `.env` for any overrides.

### BKT CEFR level tracking

Each BKT observation records the CEFR level of the item that was answered. This means "Grammar: 70%" is always "70% mastery of grammar at A2" (or whatever level was being tested), not an undifferentiated global score. A proper graduated BKT (separate instance per skill+level, graduating up when mastery > 0.95) is future work post-beta.

### SM-2 kept alongside HLR

`apply_hlr_grade` runs both HLR and SM-2 on every review. SM-2 easiness/interval fields stay current so `/review` stats (hardest items by easiness factor) keep working without changes.

### Reminder timezone

Reminder times are stored as "HH:MM" and interpreted in server local time. Fine for a single user; needs per-user timezone when multi-tenant.
