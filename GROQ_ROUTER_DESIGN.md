# Groq Adapter + Router Design

Detailed design for making **Groq the primary LLM** and evolving the router into
a **fallback ladder** with per-model daily-limit tracking, backend-change
notifications, and usage metering. Companion to `FUTURE_WORK.md`. **Design only
— no code.**

Grounded in the current code:
- `llm/gemini.py` — `async generate(prompt, *, system, history, json_output,
  max_retries) -> str`; raises `QuotaExceeded` / `LLMUnavailable`.
- `llm/ollama_client.py` — `async generate(prompt, *, system, timeout) -> str`;
  `is_available()`, `health_check()`; module-level `_available` flag.
- `llm/router.py` — `async route(task, prompt, *, system, history, json_output)`;
  task-based (`chat/assess/analyze/generate`→Gemini, `lookup/check`→Ollama);
  reactive Gemini→Ollama fallback on `QuotaExceeded`.
- Callers: `bot/handlers/conversation.py` (chat, /english, /summary via
  `structured.generate_json`), `documents.py`, `assessment.py`, `practice.py`.

---

## 1. Goals

1. Groq is tried **first** for conversational tasks; Gemini and Ollama become
   fallbacks.
2. When a model's **free daily limit** is spent, degrade down a ladder instead
   of erroring, and surface *which* backend is now serving the user.
3. Expose current state (`/status`) and an optional per-reply backend tag
   (`/backend on|off`).
4. Capture per-call token usage at the choke point for cost metering.
5. Backward compatible: with **no Groq key**, the ladder simply starts at
   Gemini and nothing breaks — Groq is a config-flag activation.
6. Single-process/in-memory for Phase A; state shape chosen so it can move to
   Redis in Phase B without touching callers.

---

## 2. Unified backend interface

Today each backend has a slightly different `generate` signature. Introduce one
shared shape so the router can treat rungs uniformly.

**`Generation` result object:** `{ text, model, tokens_in, tokens_out }`
(tokens may be `None` when a backend doesn't report them, e.g. Ollama).

**Backend protocol:** `async generate(prompt, *, system, history, json_output,
model) -> Generation`.
- `model` is passed **in** so one backend can serve several models (Groq 70B and
  8B share `GroqBackend`, differ only by `model`).
- Gemini/Ollama ignore `model` (or accept an override of their configured one).
- Wrap the existing `gemini.generate` / `ollama_client.generate` in thin
  shims that return `Generation` and accept the new kwargs — no rewrite of
  their internals.

**Unified exception taxonomy** (`llm/errors.py`), superseding the per-module
copies:
- `RateLimited(reset_at: datetime | None, scope: "requests"|"tokens")` — the
  model/backend hit its rate or daily limit. Carries when it frees up.
- `BackendUnavailable` — transient outage / network / empty response.
- `AllBackendsExhausted` — raised by the router when every rung is down.
- Keep `QuotaExceeded`/`LLMUnavailable` as **aliases** during migration so
  existing `except` clauses in handlers keep working until updated.

---

## 3. Groq adapter (`llm/groq_client.py`)

**Endpoint:** OpenAI-compatible — `POST {GROQ_BASE_URL}/chat/completions`
(`GROQ_BASE_URL = https://api.groq.com/openai/v1`). Reuse `httpx.AsyncClient`
like the Ollama client (no new SDK dependency required).

**Message mapping:** Karly's history is `[{"role": "user"|"assistant", "text"}]`.
Convert to OpenAI `messages`:
- `system` → `{"role": "system", "content": system}` (first).
- each history item → `{"role": role, "content": text}` (`assistant`/`model`
  normalize to `assistant`).
- final `{"role": "user", "content": prompt}`.

**Request params (from config):** `model`, `temperature`, `max_tokens`,
`stream=false`. For `json_output`, set `response_format={"type":"json_object"}`
(Groq supports it — cleaner than Gemini's `response_mime_type`).

**Response:** read `choices[0].message.content` for text and `usage`
(`prompt_tokens`, `completion_tokens`) for metering → `Generation`.

**Rate-limit signals — read the headers on *every* response** (Groq returns
them): `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`,
`x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`, and `retry-after` on
429. These drive **proactive** exhaustion (see §5) so we can switch rungs
*before* wasting a failed call.

**Error mapping:**
- HTTP 429 → `RateLimited(reset_at = now + retry-after or reset header,
  scope=...)`.
- HTTP 401/403 → `BackendUnavailable` (bad key) — log loudly, this is a config
  error.
- 5xx / network / timeout → retry with backoff (mirror Gemini's 2-retry loop);
  on persistent failure raise `BackendUnavailable`.
- Empty content → `BackendUnavailable`.

**Timeouts:** short connect + generous read (Groq is fast; a long hang means
trouble — fail over rather than block the user).

---

## 4. Config additions (`config.py`, `.env.example`)

- `GROQ_API_KEY` — **optional**; its presence is the activation flag.
- `GROQ_BASE_URL` — default `https://api.groq.com/openai/v1`.
- `GROQ_MODEL_PRIMARY` — default `llama-3.3-70b-versatile`.
- `GROQ_MODEL_FALLBACK` — default `llama-3.1-8b-instant`.
- `GROQ_TEMPERATURE`, `GROQ_MAX_TOKENS`, timeouts.
- Ladder ordering stays a **code constant** in Phase A (see §5), not env.

---

## 5. Router redesign — the fallback ladder

### 5.1 Rungs and ladders

A **Rung** = `{ backend, model, label }`, e.g.
`(GroqBackend, "llama-3.3-70b-versatile", "⚡ Groq 70B")`.

**Ladders are per task** (`dict[Task, list[Rung]]`):
- `chat` / `assess` / `generate`:
  `[Groq70B, Groq8B, Gemini, Ollama]`.
- `lookup` / `check` (cheap, short): `[Groq8B, Gemini, Ollama]` — start on the
  cheap model; no need for 70B on a dictionary lookup.
- `analyze` (doc extraction, `/summary`): `[Groq70B, Groq8B, Gemini]`.

If `GROQ_API_KEY` is unset, Groq rungs are dropped at build time → ladders
collapse to `[Gemini, Ollama]` (today's behaviour). **Backward compatible.**

### 5.2 Per-rung state

`RungState`: `{ cooldown_until: datetime | None, last_error, reason:
"daily"|"transient"|None }`.
- **`daily`** exhaustion (from a `RateLimited` with a reset far out, or headers
  showing `remaining ≈ 0`): skip this rung until `cooldown_until` (the reset).
- **`transient`** failure (5xx/network): short cooldown (e.g. 30–60 s), not a
  full-day skip — the rung may recover soon.

State lives in a `LadderState` object (in-memory, guarded by an `asyncio.Lock`
since it's single-process). **Phase B:** swap this object's storage for Redis;
the router API doesn't change.

### 5.3 Selection algorithm (per request)

```
for rung in ladder[task]:
    if rung on cooldown (cooldown_until > now):  skip
    try:
        gen = await rung.backend.generate(..., model=rung.model)
        update RungState from response headers (proactive exhaustion)
        return RouteResult(gen, rung)
    except RateLimited as e:
        mark rung daily-exhausted until e.reset_at; continue
    except BackendUnavailable:
        mark rung transient-cooldown; continue
raise AllBackendsExhausted
```

- **Proactive check:** before returning, if the response headers show
  `remaining_requests == 0` or `remaining_tokens < max_tokens`, set
  `cooldown_until` from the reset header so the *next* call skips straight to
  the lower rung — no wasted 429.
- **Token bucket:** an in-process limiter per Groq model enforces Groq's org
  RPM/TPM so bursts don't trip 429s in the first place. (Phase A: in-memory;
  Phase B: Redis.)
- **Reset semantics differ per backend** — don't assume calendar midnight.
  Groq uses rolling reset windows (from headers); Gemini free resets daily
  (Pacific). Always store the concrete `cooldown_until` we're given rather than
  guessing.

### 5.4 What the router returns

`RouteResult`: `{ text, rung, model, tokens_in, tokens_out }`. Callers that only
want text read `.text` (a `route_text()` convenience wrapper keeps the common
call sites terse and mostly unchanged). The extra fields feed §7 (notifications)
and §8 (metering).

---

## 6. Backend-change detection & user notifications

**Decision (locked):** notifications live in the **handler, not the router** —
the router never sends Telegram messages, it only reports which rung served the
call; the handler decides per user whether to notify. This keeps the router pure
and lets the same code serve one user today and many later without rework.

**Separation of concerns:** the router never sends Telegram messages. It only
reports *which rung served this call*. Notification is decided in the handler,
**per user**, so it scales to multi-tenant unchanged.

- Store `last_backend_label` per user (Phase A: `context.user_data`; multi-user:
  a `User` column so it survives restarts).
- After each reply, compare `RouteResult.rung.label` to the stored value:
  - **Changed** → prepend/append the transition notice (wording in
    `FUTURE_WORK.md`), then update the stored label.
  - **Same** → say nothing (notify-on-change only; no clutter).
- **Recovery:** because selection always starts at the top of the ladder, once a
  higher rung's cooldown expires the next call naturally lands back on it → the
  change-detection fires the "⚡ Back on Groq's fast model" notice for free.
- **`/backend on`** (per-user toggle, stored like `corrections_on`): when on,
  append a small tag (e.g. `⚡ Groq 70B`) to *every* reply regardless of change.
  Default off; recommend **on** during the solo phase.

**Handler error mapping** (replaces today's `QuotaExceeded`→QUOTA_MSG):
- `AllBackendsExhausted` → "all free limits spent today, try later / `/status`"
  message.
- `BackendUnavailable` (only bubbles if the whole ladder is transiently down) →
  the existing generic `ERROR_MSG`.

---

## 7. `/status` command

Router exposes `ladder_status(task=chat)` → for each rung:
`{ label, state: "ready"|"cooldown", available_at }`. Handler formats, e.g.:

`Aktuell: ⚡ Groq 70B. | Groq 8B: frei | Gemini: frei | Ollama: frei`
plus reset times for any rung on cooldown. This is read-only and cheap.

---

## 8. Usage metering hook

The router is the single point where `(model, tokens_in, tokens_out)` are known.

- `route()` gains an optional `user_id` (or returns usage in `RouteResult` and
  lets the handler persist — **preferred**, keeps the router free of DB deps).
- Handler writes one `usage_events` row per call
  (`user_id, model, tokens_in, tokens_out, task, ts`).
- This table powers: free-tier quota enforcement, real per-user cost/margin
  (see `FUTURE_WORK.md` cost model), and abuse detection.
- Tokens may be `None` for Ollama — record what we have.

---

## 9. Concurrency & state lifecycle

- **Phase A:** `LadderState` + token buckets are process-local, guarded by an
  `asyncio.Lock`. Fine for one instance.
- **Startup:** keep the existing `_post_init` Ollama `health_check()`; add an
  optional Groq reachability ping (non-fatal — a failed ping just starts that
  rung on a short transient cooldown, it self-heals on first success).
- **Phase B (multi-instance):** move `LadderState` + buckets into Redis so all
  workers share exhaustion/limit state. Router interface and handlers unchanged
  — only the state backend swaps.

---

## 10. Rollout / migration order

1. Land `llm/errors.py` + `Generation`; wrap existing Gemini/Ollama backends to
   the unified interface (behaviour identical). Ship, tests green.
2. Add `GroqBackend`. Unit-test in isolation with mocked HTTP.
3. Replace the router internals with the ladder; ladders collapse to
   `[Gemini, Ollama]` when `GROQ_API_KEY` is unset, so **this is safe to deploy
   before you have a Groq key**. Groq is coded and tested but dormant.

---

### ⛔ STOP — human step required before step 4: get a Groq API key

Steps 1–3 ship without a key and change nothing user-facing. Step 4 activates
Groq, and **it cannot proceed until you provide `GROQ_API_KEY`.** Pause the
build here.

**How to get it (free, ~2 minutes, no credit card):**
1. Go to **https://console.groq.com** and sign up (Google / GitHub / email).
2. Open **API Keys** in the left nav → **Create API Key** → name it (e.g.
   `karly`) → copy the value (starts with `gsk_...`). *You only see it once —
   copy it now.*
3. Add it to `.env` on whichever machine runs the bot:
   `GROQ_API_KEY=gsk_...` — then `make restart` (or `make deploy`).
4. That's it — the free tier is active automatically. Check current rate/daily
   limits under **Settings → Limits** in the console.

**When to do each part:**
- **The free key: now / whenever you're ready to try Groq.** No cost, no card.
  This alone is enough for the solo phase — the fallback ladder handles the free
  daily limits.
- **Paid billing: only later, when you outgrow the free tier** (roughly the
  "hundreds of users" beta). Add a card under **Settings → Billing** in the
  console to raise limits; nothing in the code changes — same key, higher caps.

**➡️ Resume at step 4 once `GROQ_API_KEY` is in `.env`.**

---

4. **(Gated on the key above.)** With `GROQ_API_KEY` set, Groq becomes primary.
   Add `/status`, `/backend`, and the change notifications.
5. Add the `usage_events` table + metering writes (prerequisite for the
   billing/quota work in `FUTURE_WORK.md`).

---

## 11. Testing plan (extends `tests/test_router.py`, `python -m unittest`)

Mock backends at the `Generation`/exception boundary:
- **Ladder order:** primary `RateLimited` → serves from rung 2; assert label.
- **Skip on cooldown:** exhausted rung is skipped until `cooldown_until` passes,
  then re-selected (fake the clock).
- **Proactive exhaustion:** headers with `remaining=0` mark the rung exhausted
  without a second failed call.
- **All down:** every rung `RateLimited` → `AllBackendsExhausted`.
- **Change detection:** simulate rung change across two calls → transition
  reported once, not repeated on a third same-rung call.
- **Groq-absent:** no key → ladder is `[Gemini, Ollama]` (regression guard for
  today's behaviour).
- **Usage passthrough:** `RouteResult` carries the mocked token counts.
- **json_output:** flag propagates to each backend's request shape.

---

## 12. Open questions / edge cases

- **Groq daily vs per-minute limits:** headers distinguish request vs token
  windows and short vs daily resets — the design stores whatever `reset_at`
  we're handed rather than assuming; confirm Groq's exact header semantics at
  build time (may have shifted since ~Aug 2025).
- **JSON reliability on lower rungs:** Ollama's JSON adherence is weaker;
  `structured.generate_json` already retries once — keep that, and prefer
  Gemini over Ollama for `analyze` tasks (reflected in that ladder).
- **Streaming:** out of scope here; a later latency win (`FUTURE_WORK.md`
  Phase B) that would change `RouteResult` into an async iterator.
- **Fairness at scale:** the per-user token bucket that stops one user starving
  the shared Groq org limit is a Phase B (Redis) concern — noted, not built for
  the beta.
