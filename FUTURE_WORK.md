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
| Primary model | **Groq `groq/compound`** (best available on free tier; fallback `groq/compound-mini`) |

---

## Current backend ladder (live as of 2026-09-03)

```
⚡ Groq (groq/compound)       — primary; fast
⚡ Groq Mini (groq/compound-mini) — when compound daily limit hit
🤖 Gemini (gemini-3.6-flash)  — when both Groq limits hit (~20 req/day free)
🐌 Ollama (local)             — last resort; slow (~1 min), unlimited
```

Per-rung cooldowns track daily vs transient failures. State resets on restart
(in-process only — Phase B moves this to Redis). `/status` shows current rung;
`/backend on` appends a footer tag to every reply.

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
