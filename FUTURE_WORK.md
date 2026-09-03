# Karly — Roadmap & Future Work

The single living plan for Karly's evolution from a single-user bot into a
Groq-powered, subscription-sold German tutor. Records *what*, *why*, and
*concrete starting points* so any future session can pick up without
re-deriving the diagnosis. **Planning doc — no code here.**

> **Shipped (2026-09-02), no longer tracked here:** Phases 0–5 (assessment,
> conversation, SM-2 practice, PDF learning, systemd deploy to the OptiPlex);
> the token-in-logs fix; the `/corrections on|off` toggle + `/summary`; the
> typing-indicator keep-alive. See git history for detail.

---

## Vision

Turn Karly into a subscription SaaS: many Telegram users, **Groq as the primary
LLM** (sub-2s replies are the product's edge), sold via **Telegram Stars**.
Build only as far as demand justifies.

### Decisions locked (2026-09-02)

| Decision | Choice |
|---|---|
| First scale target | **Paid beta — ≤ hundreds of users** |
| Payments | **Telegram Stars** (native, recurring, no external provider) |
| Free vs paid split | **Same model for all; gate on volume + features**, not model quality |
| Primary model | **Groq `llama-3.3-70b-versatile`** (best German; free-user cost bounded by volume caps) |

The "same model for all" decision is about *product tiering* (paid ≠ smarter
model). It is **separate** from the *free-tier fallback ladder* below, which
exists only to survive free-tier rate limits and keeps the bot alive when a
model's daily allowance is spent.

---

## Model strategy: Groq-first, with a free-tier fallback ladder

**Primary, always tried first: Groq `llama-3.3-70b-versatile`.**

Each backend/model on the free tier has its own daily allowance (Groq's
per-model RPD/TPD; Gemini's ~20 requests/day). When the active one is
exhausted, degrade down the ladder rather than erroring:

1. **Groq `llama-3.3-70b-versatile`** — primary (fast + best German).
2. **Groq `llama-3.1-8b-instant`** — when the 70B free daily limit is hit
   (still fast, lighter quality).
3. **Gemini `gemini-3.6-flash`** — when both Groq free limits are hit
   (slower, ~24s).
4. **Ollama on the OptiPlex** — last resort; slow (~70s, CPU-only) but free and
   unlimited. Retire this rung once the bot moves to cloud hosting.

The router tracks per-model exhaustion state, resets it daily, and remembers
which rung is currently active so it doesn't re-probe an exhausted model every
turn.

This is exactly the **"just me, not ready to invest"** mode: everything runs on
free tiers, cost is **$0**, and the ladder keeps Karly responsive even after a
model's free daily limit is spent.

---

## Backend transparency & user messages (build early — needed now)

The user wants to know *which* backend is answering and *when it changes*.
Design:

- **Notify on change, not every message** (avoids clutter). The bot sends a
  one-time notice whenever the active rung changes, then stays quiet until it
  changes again.
- **`/status` command** — on demand: shows the current model, which rungs are
  exhausted, and the reset time.
- **Optional `/backend on|off` toggle** — when on, every reply carries a small
  footer tag (e.g. `⚡ Groq 70B`) for users who always want to see it. Default
  off; recommended **on** for the current solo phase.

### Planned message wording (bilingual, matching the bot's style)

- **Startup / first message of the day (on primary):**
  `⚡ Läuft auf Groq (llama-3.3-70b) — schnell. (Talking to Groq's fast model.)`
- **70B → 8B (Groq 70B free limit spent):**
  `⚡ Groqs schnelles Modell (70B) hat sein Tageslimit erreicht — ich wechsle zum leichteren Groq-Modell (8B). Immer noch schnell, etwas einfacher. Reset um Mitternacht (UTC). (Switched to Groq 8B.)`
- **Groq → Gemini (both Groq free limits spent):**
  `🐢 Groqs Gratis-Limit ist heute aufgebraucht — ich wechsle zu Gemini. Etwas langsamer (~20s). (Switched to Gemini; slower.)`
- **Gemini → Ollama (all cloud free limits spent):**
  `🐌 Alle Cloud-Gratis-Limits sind heute erschöpft — ich laufe jetzt lokal (Ollama). Langsam (~1 Min/Antwort), aber es geht. (Running locally now; slow.)`
- **Recovered to primary (new day / limits reset):**
  `⚡ Zurück auf Groqs schnellem Modell! (Back on Groq's fast model.)`
- **`/status` output (example):**
  `Aktuell: ⚡ Groq 70B. | Groq 8B: frei | Gemini: frei | Reset: 00:00 UTC.`

---

## Expenses — what this actually costs

**Assumptions** (adjust as real usage data arrives via metering below):
- One tutor turn ≈ **~2,000 input tokens** (persona + up to 20-message history)
  and **~500 output tokens**.
- Groq pricing used (⚠️ **verify — my figures are ~Aug 2025 and Groq changes them**):
  `llama-3.3-70b-versatile` ≈ **$0.59 / 1M in, $0.79 / 1M out**;
  `llama-3.1-8b-instant` ≈ **$0.05 / 1M in, $0.08 / 1M out**.
- ⇒ **Per turn:** ~**$0.0016** on 70B, ~**$0.00014** on 8B.

| Scenario | Volume | LLM cost (70B) | LLM cost (8B) | + Infra | Notes |
|---|---|---|---|---|---|
| **Just me (now)** | ~1,500 turns/mo | **$0** on free tier | $0 | $0 | Free tiers cover it; ladder handles limits. If paid: ~**$2.40/mo** on 70B. |
| **Hundreds (beta)** | 200 users × ~300 turns = 60k/mo | ~**$95/mo** | ~$8/mo | ~$10–20/mo | Past free tier → Groq paid dev tier. Postgres (Neon free) + small VM. |
| **Scale (thousands)** | 2,000 users × ~300 turns = 600k/mo | ~**$950/mo** | ~$84/mo | ~$100–300/mo | Strong case to route **free users to 8B** here — ~11× cheaper. |

**Revenue context:** a Telegram Stars sub at ~$5–9/mo covers costs at modest
paid conversion — e.g. at 200 users, ~20 paying subscribers ≈ $100–180/mo,
which already offsets the ~$95 LLM + infra. The "same model for all" choice
keeps quality high; **volume caps on the free tier are what protect the
margin**, so set them deliberately.

**Bottom line for your current stance:** running solo on free tiers = **$0**.
No spend until you choose to open it to others.

---

## Phase A build — the paid-beta path

Smallest viable SaaS. One process, long-polling, no Redis, no webhooks.

1. **Groq backend + fallback-ladder router.** Add a `GroqBackend`
   (OpenAI-compatible, thin) as primary; wire the 70B → 8B → Gemini → Ollama
   ladder with per-model daily-exhaustion tracking + the transparency messages
   above. In-process token bucket for Groq's org rate limits (no Redis needed
   at one instance). **Full design: [`GROQ_ROUTER_DESIGN.md`](GROQ_ROUTER_DESIGN.md).**
   ⛔ **Build pauses partway** for a human step — you must create a free Groq API
   key (console.groq.com → API Keys) and add `GROQ_API_KEY` to `.env` before
   Groq can be switched on. Steps before that gate ship safely with no key
   (ladder falls back to Gemini/Ollama). See the design doc's rollout section
   for the exact stop point and instructions.
2. **Multi-tenant foundation.** Remove the single-user gate (every Telegram
   user auto-provisions a `User`). **SQLite → managed Postgres.** **Fix the
   sync-SQLAlchemy-in-async-handlers issue** — fine at one user, blocks the
   event loop under concurrency. This is the main existing-code lift.
3. **Usage metering** (before billing). One row per LLM call
   (`user_id, model, tokens_in, tokens_out, ts`). Powers quota enforcement,
   real cost/margin numbers, and abuse detection.
4. **Entitlements + gating.** `subscriptions` table
   (`user_id, tier, status, current_period_end, provider_charge_id`); extend
   `require_auth` → `require_tier`/`check_quota`. Gate on **volume + features**:
   free = N msgs/day, no PDF, no `/summary`; paid = high/unlimited msgs, PDFs,
   `/summary`, priority in the rate-limiter.
5. **Telegram Stars subscriptions.** `/subscribe` sends a recurring Stars
   invoice; handle `pre_checkout_query` → `successful_payment` → renewal/cancel
   updates; grace period + auto-downgrade on lapse.

**Critical path:** Groq adapter → multi-tenant + Postgres + async fix →
metering → entitlements → Stars.

---

## Deferred until the beta earns it (Phase B/C)

- Long-polling → **webhooks** + multiple stateless instances behind a load
  balancer (horizontal scale).
- **Redis** for cross-instance rate-limiting/token-buckets and a job queue.
- **Durable scheduler** for reminders (current in-process `job-queue` only
  survives one instance).
- Read replicas, response streaming to Telegram, caching common lookups,
  routing free users to 8B for cost, multi-region.

---

## Cross-cutting (required even at beta scale)

- **Privacy policy + ToS** — you'll store other users' writing and take payment.
  GDPR export/delete is easy given the per-`user_id` schema.
- **Hard per-user daily cost cap even on paid** — one runaway user directly
  burns Groq budget.
- **Hosting** — move to a small always-on cloud VM/container; a paid product
  shouldn't depend on the OptiPlex. The OptiPlex becomes dev/staging (and the
  Ollama last-resort rung).

---

## Smaller open items

- Auto-trigger `/summary` when corrections toggle back on, or after N idle mins
  (on-demand only today).
- Manual SM-2 override buttons for typed answers (auto-mapped today).
- Reminder times use server local timezone (fine single-user; revisit for
  multi-tenant across timezones).
- OCR for scanned PDFs — intentionally out of scope.
