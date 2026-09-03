# Karly — Roadmap & Future Work

The single living plan for Karly's evolution from a single-user bot into a
Groq-powered, subscription-sold German tutor. Records *what*, *why*, and
*concrete starting points* so any future session can pick up without
re-deriving the diagnosis. **Planning doc — no code here.**

> **Shipped (through 2026-09-03), no longer tracked here:**
> Phases 0–5 (assessment, conversation, SM-2 practice, PDF learning, systemd
> deploy to the OptiPlex); the token-in-logs fix; `/corrections on|off` +
> `/summary`; typing-indicator keep-alive; **Phase A step 1 — Groq-first
> fallback ladder** (`llm/errors.py`, `llm/groq_client.py`, router rewrite);
> **backend-change notifications**; **`/status`** and **`/backend on|off`**.
> See git history for detail.

---

## Vision

Turn Karly into a subscription SaaS: many Telegram users, **Groq as the primary
LLM** (sub-2s replies are the product's edge), sold via **Telegram Stars**.
Build only as far as demand justifies.

### Decisions locked (2026-09-03)

| Decision | Choice |
|---|---|
| First scale target | **Paid beta — ≤ hundreds of users** |
| Payments | **Telegram Stars** (native, recurring, no external provider) |
| Free vs paid split | **Same model for all; gate on volume + features**, not model quality |
| Primary model | **Groq `openai/gpt-oss-120b`** (fallback `openai/gpt-oss-20b`). NB: `groq/compound*` are agentic systems, **not** chat-completion models — they 404 on `/chat/completions`; do not use them here. |

---

## Current backend ladder (live as of 2026-09-03)

```
⚡ Groq (openai/gpt-oss-120b)     — primary; fast
⚡ Groq Mini (openai/gpt-oss-20b) — when the 120b daily limit is hit
🤖 Gemini (gemini-3.6-flash)      — when both Groq limits hit (~20 req/day free)
🐌 Ollama (local)                 — last resort; slow, unlimited — CHAT ONLY
```

Per-rung cooldowns track daily vs transient failures. State resets on restart
(in-process only — Phase B moves this to Redis). `/status` shows current rung;
`/backend on` appends a footer tag to every reply.

**Ollama is excluded from structured tasks** (`Task.assess`, doc analysis): the
3B local model cannot produce reliable JSON, which corrupted the assessment
(returned an answer instead of a question). Those ladders stop at Gemini.

**Cost today:** $0 — all free tiers. Groq free limits handle solo use.

---

## Phase A — remaining items (paid-beta path)

> ⛔ **IGNORE UNTIL READY TO OPEN KARLY TO OTHER USERS.**
> Everything below in this section is only needed when you decide to let other
> people in. While it's just you, none of this is worth touching — the bot
> works fine as-is. Come back here when you're ready to invite the first beta
> users.

### A2. Multi-tenant foundation

Remove the single-user gate (every Telegram user auto-provisions a `User`).
**SQLite → managed Postgres** (Neon free tier to start).
**Fix the sync-SQLAlchemy-in-async-handlers issue** — fine at one user, blocks
the event loop under concurrency. This is the main existing-code lift.

### A3. Usage metering

One row per LLM call (`user_id, model, tokens_in, tokens_out, task, ts`).
The router already returns `RouteResult` with token counts — the handler just
needs to persist them. Powers quota enforcement, real cost/margin numbers,
and abuse detection. Prerequisite for A4.

### A4. Entitlements + gating

`subscriptions` table (`user_id, tier, status, current_period_end,
provider_charge_id`); extend `require_auth` → `require_tier` / `check_quota`.
Gate on **volume + features**: free = N msgs/day, no PDF, no `/summary`;
paid = high/unlimited msgs, PDFs, `/summary`, priority in the rate-limiter.

### A5. Telegram Stars subscriptions

`/subscribe` sends a recurring Stars invoice; handle `pre_checkout_query` →
`successful_payment` → renewal/cancel updates; grace period + auto-downgrade
on lapse.

**Critical path:** A2 (multi-tenant + async fix) → A3 (metering) → A4
(entitlements) → A5 (Stars).

---

## Expenses — what this actually costs

**Assumptions** (adjust as real usage data arrives via metering):
- One tutor turn ≈ **~2,000 input tokens** and **~500 output tokens**.
- Groq pricing: verify current rates at console.groq.com — they change.

| Scenario | Volume | LLM cost | + Infra | Notes |
|---|---|---|---|---|
| **Just me (now)** | ~1,500 turns/mo | **$0** on free tier | $0 | Free tiers cover it. |
| **Hundreds (beta)** | 200 users × ~300 turns = 60k/mo | ~$20–100/mo | ~$10–20/mo | Past free tier → Groq paid. Postgres (Neon free) + small VM. |
| **Scale (thousands)** | 2,000 users × ~300 turns = 600k/mo | ~$200–950/mo | ~$100–300/mo | Route free users to Mini here — much cheaper. |

**Revenue context:** a Telegram Stars sub at ~$5–9/mo covers costs at modest
paid conversion. Volume caps on the free tier protect the margin — set them
deliberately.

---

## Deferred until the beta earns it (Phase B/C)

- Long-polling → **webhooks** + multiple stateless instances behind a load
  balancer (horizontal scale).
- **Redis** for cross-instance rate-limiting/token-buckets and a job queue
  (also moves `LadderState` out of process so restarts don't reset cooldowns).
- **Durable scheduler** for reminders (current in-process job-queue only
  survives one instance).
- Read replicas, response streaming to Telegram, caching common lookups,
  routing free users to Mini for cost, multi-region.

---

## Cross-cutting (required even at beta scale)

- **Privacy policy + ToS** — storing other users' writing and taking payment.
  GDPR export/delete is easy given the per-`user_id` schema.
- **Hard per-user daily cost cap even on paid** — one runaway user directly
  burns Groq budget.
- **Hosting** — move to a small always-on cloud VM/container; a paid product
  shouldn't depend on the OptiPlex. The OptiPlex becomes dev/staging (and the
  Ollama last-resort rung).

---

## Interactivity roadmap (started 2026-09-03)

A push to make Karly more interactive. Original plan had five threads; the
**assessment revamp shipped first**, the rest are still open.

### Shipped
- **Assessment revamp** (`/test`): structured JSON items, MCQ answer buttons
  with local scoring, adaptive CEFR difficulty, per-skill quotas (grammar /
  reading / comprehension / production / functional / vocab — no longer
  vocab-heavy), auto-graded open answers **batched 5 at a time** to save LLM
  calls, per-skill breakdown in the verdict. Ollama excluded from the assess
  ladder so bad JSON can't leak an answer. Global `/cancel` added.

### Still missing from the plan
1. **Command menu button** (was "step 1", never built). Use Telegram
   `setMyCommands` in a `post_init` hook in `bot/main.py` to populate the
   native `≡` menu. **Static, hand-picked order** (decided): practice, test,
   profile, review, topic, summary, docs, remind, help — hide `/status`,
   `/backend`. Optionally a `/menu` reply-keyboard for big tappable buttons.
   Dynamic usage-sorted ordering deferred.
2. **Flashcard upgrades** — `/practice` already has SM-2 flashcard/cloze/
   sentence. Add: `/flashcards` alias + menu entry, due-count badge in
   `/profile` & reminders, MCQ flashcard mode (LLM distractors), auto-graded
   typed answers, DE↔EN direction toggle, themed decks (filter by `source` /
   `document_id`), "➕ Add to flashcards" button on corrections/doc vocab.
3. **Correction-attached buttons** — inline buttons under each correction:
   "Explain why", "Save word", "Another example", "Drill this". Uses stored
   `corrections_json`.
4. **`/daily` mixed challenge** — one bite-sized daily task (cloze + translate
   + "reply to this"), tied to the existing `PracticeLog` streak.
5. **Stretch** — voice notes (STT/TTS), roleplay scenarios, weekly progress
   report, `/quiz` rapid MCQ from weak areas.

**Assessment follow-ups not yet done:** explicit running-estimate refinements,
harden the JSON fallback further (retry/skip rather than any raw dump).

---

## ML roadmap — personalized learning models (AFTER the interactivity pipeline)

**Sequencing:** build this only once the interactivity items above (command
menu → flashcards → correction buttons → `/daily`) have shipped. These three
stages are ordered cheapest-first and each earns the next; do not jump to the
LSTM before the data exists to train it. All three approved by the user
(2026-09-03).

**Why not just TensorFlow from the start:** a deep net is data-hungry; a single
learner won't generate enough signal for it to beat a simple model, and the LLM
already handles generation. The real ML win is **smarter review scheduling and
knowledge tracing**, so we escalate model complexity as data grows.

### Stage 1 — Half-Life Regression (HLR) recall scheduler
**What:** learn a per-item *memory half-life* from review history and schedule
`next_review_at` when predicted recall drops to a target (e.g. 0.5), replacing
the fixed SM-2 formula.
- **Model:** logistic/linear regression on features (past correct/incorrect
  count, elapsed time, item difficulty, source). **scikit-learn — no TF.**
- **Data needed:** log every review outcome + timestamp. `PracticeLog` already
  logs sessions; add per-item review events (correct?, latency, prior interval).
- **Integration:** new `srs/hlr.py` alongside `srs/sm2.py`; a config flag picks
  the scheduler so we can A/B against SM-2. Retrain offline (cron) on the
  accumulated log; store learned weights, not a live-trained model.
- **Why first:** biggest UX payoff (better retention), smallest dependency,
  works on modest single-user data.

### Stage 2 — Bayesian Knowledge Tracing (BKT) concept mastery
**What:** track mastery probability per *concept* (grammar rules, e.g. "dative
after two-way prepositions") so Karly can target weak concepts in `/daily`,
`/quiz`, and assessment gap selection.
- **Model:** classic BKT (4 params per skill: prior, learn, slip, guess) —
  interpretable, low-data, no neural net. Tag items/corrections with concept
  ids to feed it.
- **Data needed:** concept tagging on assessment items and corrections
  (`corrections_json` already stores the mistakes; add a concept label).
- **Integration:** `ml/bkt.py`; surface mastery in `/profile` and use it to
  pick drill targets.

### Stage 3 — Deep Knowledge Tracing (DKT, LSTM) — **TensorFlow**
**What:** sequence model (LSTM) over the full interaction history to predict
next-item correctness / mastery across many concepts at once. This is where
TensorFlow earns its place.
- **Gate:** only after the paid beta (Phase B+) produces enough multi-user
  interaction sequences to train a net that beats BKT. Until then it will
  overfit — keep it on the shelf.
- **Model:** LSTM/GRU over (concept, correct) sequences (the standard DKT
  formulation). **TensorFlow** (user preference); PyTorch acceptable alt.
- **Integration:** offline training pipeline producing a served model;
  `ml/dkt/` module; inference feeds the same scheduler/target-selection
  interfaces as HLR/BKT so it's a drop-in upgrade.

**Dependency note:** Stages 1–2 add only scikit-learn (light). Stage 3 adds
TensorFlow — a heavy dependency; defer it until data justifies, and decide
container/resource impact on the OptiPlex before committing.

---

## Planned features (solo phase — build whenever ready)

### Correction strictness level

**What:** Replace the binary `/corrections on|off` toggle with a three-level
strictness dial. The user sets a level once and the tutor calibrates how
aggressively it corrects.

**Levels:**

| Level | Command | Behaviour |
|---|---|---|
| `off` | `/corrections off` | No corrections at all. Converse freely; use `/summary` to review later. *(Existing)* |
| `relaxed` | `/corrections relaxed` | Catch only real errors that would confuse a native speaker: wrong case, wrong verb conjugation, missing agreement. Ignore word order choices, stylistic variation, and minor article slips. |
| `strict` | `/corrections strict` | Catch everything: grammar, word order, article gender, register mismatches, awkward phrasing. Maximum learning pressure. |

`relaxed` is the new recommended default for daily conversation practice.
`strict` is for deliberate drilling sessions.

**Slang handling (applies at all levels):**
Slang is never treated as an error. If the user writes something colloquial or
slangy, Karly notes it with a neutral tag — `💬 "[word]" — Slang/umgangssprachlich`
— so the user knows it's informal but doesn't feel corrected. This note appears
regardless of strictness level and is not stored as a vocab item.

**Storage:** a `correction_level` string column (`"off"` / `"relaxed"` /
`"strict"`) on the `User` model, replacing the existing `corrections_on` bool.
During migration, map `corrections_on=True → "relaxed"`, `False → "off"` to
preserve existing behaviour.

**Prompt impact:** the `CORRECTION_BLOCK` prompt snippet becomes
level-specific. Each level gets its own instruction paragraph telling the tutor
exactly what to flag and what to silently ignore. The slang note instruction is
added once, shared across all levels.

**Command UX:** `/corrections` with no argument shows the current level.
`/corrections relaxed|strict|off` sets it. Keep `on` as an alias for `strict`
so any muscle memory from the old toggle still works.

---

## Smaller open items

- Auto-trigger `/summary` when corrections toggle back on, or after N idle
  mins (on-demand only today).
- Manual SM-2 override buttons for typed answers (auto-mapped today).
- Reminder times use server local timezone (fine single-user; revisit for
  multi-tenant across timezones).
- OCR for scanned PDFs — intentionally out of scope.
- `last_backend_label` stored in `context.user_data` (lost on restart) — move
  to a `User` column for persistence when multi-tenant lands (A2).
