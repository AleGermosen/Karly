# Karly — Roadmap & Status

*Last updated: 2026-09-04 (session 2)*

---

## TL;DR — What's pending right now

> Everything above the line is the working list. Scan this first every session.

### 🔴 Bugs — confirmed, not yet fixed

*None — all known bugs resolved.*

### 🟡 Features — planned, not started

| # | Item | Priority | Notes |
|---|------|----------|-------|
| **H7** | English B1 curriculum — ~28 units + ~392 questions | High | Content-only, no code. Next curriculum level after A2. See `CURRICULUM_PLAN.md` |
| **PAY** | Payment system end-to-end test + pricing decision | High | Code exists (F-15/F-16/F-21); needs live test + price calibration. See detail below. |
| **F-13** | Voice notes — speak German/English, get a text correction back | Medium | Groq Whisper → existing correction pipeline (Phase 5) |
| **F-14** | Assignments — teacher assigns a unit, student sees it as next `/course` task | Medium | Needs both curriculum (done) and classroom (done) — the join between them |

### ✅ Recently completed

| Fix | What changed |
|-----|-------------|
| **H2 English A1** | 20 units + 280 questions (`curriculum/en/a1.yaml` + `curriculum/bank/en/a1.jsonl`) |
| **H3 `/course`** | Progress bar, lesson card, exercise runner, pass/fail, `/stopcourse` |
| **H4 Flashcard creation** | Missed questions auto-added to personal flashcard deck after a unit |
| **H5 `/leveltest` + `/browse`** | 15-question level test, CEFR level cleared on pass, `/browse` unit picker |
| **H6 English A2** | 24 units + 336 questions (`curriculum/en/a2.yaml` + `curriculum/bank/en/a2.jsonl`) |
| **H0b Curriculum lint** | `make curriculum-lint` / `curriculum-rehash` — validates and rehashes content files |
| **F-13 Voice notes** | `/pronounce` — Gemini TTS pronunciation voice notes |
| **F-14 CSV export** | `/export` — teacher downloads student progress as CSV |
| **Multi-teacher architecture** | Superuser role, `/addteacher`, `/removeteacher`, `/teachers`, multi-step approval |
| **Class management** | `/newclass`, `/classes`, `/moveclass`, `/assign`, `/classtopic` |
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

## Master plan — order of work

> The whole roadmap in one sequence. Work through it phase by phase, a little at a time — each phase is independently shippable, and each item can be one session's worth of work. Check items off here as they land.

### Phase 0 — Quick wins & confirmed bugs *(one short session, do first)*

Small, low-risk items that clear the bug list and the trivial features in one pass.

- [x] **B-6** — update user's name in `get_or_create_user` if it changed in Telegram (`db/repo.py`)
- [x] **B-7** — `python-telegram-bot[job-queue]` in `requirements.txt`; verify running on OptiPlex
- [x] **F-1** — block `/english` in English mode, redirect to `/spanish` (`conversation.py`)
- [x] **F-2** — bilingual stale-correction message (`conversation.py`)
- [x] **F-3** — Spanish backend notices for English-mode students (`_BACKEND_NOTICES_EN` translated to Spanish)
- [x] **F-6** — `/classsetcorr CLASS LEVEL` — teacher sets class default correction level (`classroom.py`)

### Phase 1 — Monetisation core *(F-15 → F-16 → F-21, in that order)*

These three are one coherent system and must land in this order: limits first, then a way to pay, then top-ups.

- [x] **F-15** — two-layer rate limits (3-hour session cap + weekly cap, per-tier); DB columns `session_count`, `week_count`, timestamps, `subscribed` flag; friendly limit messages
- [x] **F-16** — Telegram Stars `/subscribe` flow (invoice → `PreCheckoutQuery` → `successful_payment`); BotFather Stars setup; 30-day expiry job; `payments` table
- [x] **F-21** — `/topup` credit packs + buy-button on the limit-hit message; `topup_credits` column; draw-down order session → weekly → top-ups

### Phase 2 — Classroom & student experience *(independent items, any order)*

- [x] **F-17** — `/addword <word>` personal vocabulary command (LLM lookup → card preview → HLR deck insert)
- [x] **F-18** — `/broadcast` teacher messages (confirmation step, flood-limit pacing, `broadcasts` log table)
- [x] **F-19** — placement assessment on first join (Start now / Later / Skip buttons, `placement_status` column)
- [x] **F-22** — media comprehension grading (`/setmedia`, `/task`, `/results`, `/clearmedia`; rubric-scored LLM grading; `media_tasks` + `media_submissions` tables)
- [x] **F-20** — Impostor inline keyboard hub

### Phase 3 — Engineering quality *(hardening before scale)*

- [x] Centralize credit metering — `metered()` decorator in `bot/credits.py`
- [x] Smoke-test script `scripts/smoke.py` — 13 checks, zero LLM calls
- [x] `TypedDict` for history/correction dicts — `bot/types.py`
- [x] Ladder health check in `/status` — poisoned rungs listed with reason

### Phase 4 — Curriculum phase 📚 *(in progress)*

Machinery is complete. Content is the remaining work — each level is a YAML + JSONL commit with no code changes.

- [x] Curriculum lint tool (`make curriculum-lint / curriculum-rehash`)
- [x] English A1 — 20 units, 280 questions
- [x] `/course` — lesson card, exercise runner, pass/fail, progress bar
- [x] `/leveltest` — 15-question level test, CEFR cleared on pass
- [x] `/browse` — jump to any unit at or below your level
- [x] Flashcard creation from missed questions (H4)
- [x] English A2 — 24 units, 336 questions
- [ ] **English B1** — ~28 units, ~392 questions ← **next content run**
- [ ] English B2 — ~30 units
- [ ] English C1 — ~30 units (needs own unit shape; see `CURRICULUM_PLAN.md §3`)
- [ ] German levels — personal track, on demand

### Phase 5 — Voice *(F-13 follow-on)*

- [ ] Voice-note input: Telegram voice → Groq Whisper → existing correction pipeline (`filters.VOICE` in `main.py`)
- [ ] Optional: TTS voice replies

### Phase 6 — Scale *(when opening to the public)*

In dependency order:

1. [ ] SQLite → Postgres (Neon free tier); fix sync SQLAlchemy in async handlers
2. [ ] Wire `LLMUsage` metering into entitlements
3. [ ] `subscriptions` table + free/paid gating (builds on Phase 1)
4. [ ] Long-polling → webhooks; Redis for cross-instance rate limits; cloud VM

### Phase 7 — Games 🎮 *(after everything above)*

> **Reminder:** once all the phases above are done, come back to `GAMES_PLAN.md` — eight games (G-1 Word Chain through G-8 Murder Mystery) are fully specced there and waiting. Start with the low-complexity ones (G-1 Word Chain, G-2 Story Relay, G-3 Telephone); they reuse the Impostor room/join/turn pattern.

- [ ] Revisit `GAMES_PLAN.md` and pick the first game to build

---

## What's working today

**Dual-language tutor:** German mode (English speaker learning German) and English mode (Spanish speaker learning English) — both fully featured.

**Core features:** adaptive placement test (A1 start, MCQ + fill-in-the-blank, auto-graded), spaced-repetition flashcards (HLR scheduler, MCQ/cloze/sentence modes, deck picker with per-deck fwd/rev direction), daily mini-challenge (shared per level, cached), rapid skill quiz, roleplay scenes (6 German + 6 English scenarios, corrections at right level), weekly progress report, PDF vocabulary extraction, The Impostor social deduction game, BKT skill mastery, DKT LSTM (gated, activates at 50+ reviews).

**English course (A1 + A2 live):** `/course` with lesson cards, exercise runner (MCQ/cloze/transform/produce), pass/fail per unit, progress bar, missed-question → flashcard pipeline. `/leveltest` clears a CEFR level and unlocks the next. `/browse` jumps to any unit. 44 units and 616 banked questions shipped; B1 is next.

**Classroom controls:** superuser + teacher roles, multi-step approval flow (approve → assign teacher → assign class), per-teacher class management (`/newclass`, `/classes`, `/moveclass`, `/assign`), drill topic per class, roster views, skill error rates dashboard, per-student daily credit cap, global ceiling with reserve pool, rate limiting, concurrency queue, streak bonus, low-balance nudge, `/mybudget` for students.

**Backend ladder:** Groq 120b → Groq 20b → Gemini 3.6-flash → Ollama (chat only). Per-rung cooldowns in-process.

---

## Planned feature detail

### PAY — Payment system verification + pricing

> The payment code (F-15 / F-16 / F-21) is already written. This item is the end-to-end live test, the pricing decision, and understanding what you actually receive.

---

#### Step 1 — Enable Stars in BotFather (one-time, 2 minutes)

1. Open `@BotFather` → `/mybots` → select Karly → **Payments**.
2. Choose **Telegram Stars** — free, no paperwork, no external processor.
3. Done. The bot can now send invoices in Stars (`currency="XTR"`).

#### Step 2 — End-to-end smoke test

Send yourself a test invoice before charging real students:

```python
# Run once in a throwaway script or your own chat
await bot.send_invoice(
    chat_id=YOUR_TELEGRAM_ID,
    title="Karly — test subscription",
    description="This is a test. The Stars will be refunded.",
    payload="test_subscribe",
    currency="XTR",
    prices=[LabeledPrice("1 month", 100)],  # 100 Stars
)
```

Checklist:
- [ ] Invoice appears in your chat
- [ ] Checkout screen shows correct amount
- [ ] `pre_checkout_handler` fires (check logs)
- [ ] `successful_payment` fires and `users.subscribed` flips to `True` in the DB
- [ ] Expiry timestamp is written correctly (30 days from now)
- [ ] Bot sends you a confirmation message

Repeat for `/topup` packs. Then test the limit-hit flow: exhaust your session credits, confirm the "buy more" button appears, buy the small pack, and confirm `topup_credits` increments.

---

#### Step 3 — Pricing

Stars are priced by Telegram — **you set the number of Stars, not the dollar amount.** The dollar equivalent fluctuates slightly but is roughly **$0.013–0.020 per Star** depending on platform (iOS is more expensive because Apple takes a cut before the user even sees the price).

**Recommended starting prices (tune after first month):**

| Product | Stars | Approx. user cost | What you actually receive |
|---------|-------|-------------------|--------------------------|
| Monthly subscription | 200 ⭐ | ~$3.00–4.00 | ~$1.80–2.80 after fees |
| Small top-up (10 msgs) | 30 ⭐ | ~$0.45–0.60 | ~$0.27–0.42 after fees |
| Medium top-up (30 msgs) | 75 ⭐ | ~$1.10–1.50 | ~$0.66–1.05 after fees |
| Large top-up (75 msgs) | 150 ⭐ | ~$2.25–3.00 | ~$1.35–2.10 after fees |

These are starting points — Telegram Stars is a new market and users have limited price reference. Start slightly lower than you think is right; you can raise prices after you see what converts.

> **Note:** the minimum invoice amount is 1 XTR. Telegram may impose a minimum higher than this in practice — test with 1 XTR to confirm.

---

#### Step 4 — How you get paid (the full chain)

Stars do not deposit to a bank account directly. The path is:

```
Stars in Karly → Fragment.com → TON (cryptocurrency) → Exchange → USD/EUR → Bank
```

**Step by step:**

1. **Accumulate Stars.** They sit in your bot's Stars balance, visible at `@BotFather` → Payments, or via the Telegram API.
2. **Withdraw to TON via Fragment.** Go to [fragment.com](https://fragment.com) and connect your Telegram account. Convert your Stars balance to TON (Toncoin) — this is where Telegram takes its cut.
3. **Sell TON for fiat.** Use any crypto exchange that lists TON: Binance, OKX, or Kraken. Withdraw USD/EUR to your bank.
4. **Bank transfer.** Standard wire or SEPA, depending on your exchange and country.

Timeline: Fragment withdrawal is near-instant; exchange → bank is 1–3 business days.

---

#### Step 5 — How much you lose (the fee breakdown)

This is the honest math. Three layers of fees eat into your revenue:

| Layer | Who takes it | Rate | Notes |
|-------|-------------|------|-------|
| **Platform cut** | Apple (iOS) or Google (Android) | ~30% | Taken when the *user* buys Stars, before you ever see them. Desktop/web purchases avoid this — the same 100 Stars costs less to produce. You can't control this. |
| **Telegram commission** | Telegram (via Fragment) | ~30% | Taken when you convert your Stars to TON. This is Telegram's revenue. |
| **Exchange + withdrawal** | Crypto exchange + bank | ~1–3% | Varies by exchange and withdrawal method. |

**Effective take rate — what lands in your bank per 100 Stars charged:**

| User buys on | Stars charged | Platform cut | Telegram cut (30% of remainder) | Exchange fees | You receive |
|---|---|---|---|---|---|
| iOS / Android | 100 ⭐ | ~30 ⭐ | ~21 ⭐ (30% of 70) | ~1 ⭐ | **~48 ⭐ worth (~48%)** |
| Desktop / web | 100 ⭐ | 0 ⭐ | ~30 ⭐ | ~1 ⭐ | **~69 ⭐ worth (~69%)** |

In dollar terms, if you charge 200 Stars (~$3.00 user cost on iOS):
- iOS user: you receive roughly **$1.44** (~48%)
- Desktop user: you receive roughly **$2.07** (~69%)

Most of your students will be on mobile, so **budget on ~50% effective rate** — for every $3 a student pays, about $1.50 reaches your bank.

**This is not unusual.** The App Store / Play Store 30% cut applies to all digital subscriptions sold through apps (Spotify, Duolingo, every language app). Telegram's additional 30% is higher than typical payment processors (~3%) but buys you the frictionless in-app checkout — no credit card, no signup, no failed payments.

---

#### Step 6 — What to decide before going live

| Question | Recommendation |
|---|---|
| What price for the subscription? | Start at 200 ⭐/month (~$3 for the student, ~$1.50 to you). Raise to 300 ⭐ if conversion is strong. |
| What price for top-ups? | Small 30 ⭐, Medium 75 ⭐, Large 150 ⭐. Middle pack is best value — most buyers will pick it. |
| Free tier limit? | 10 messages/session, 40/week. Enough to try the bot seriously; not enough for daily study. |
| Currency? | `XTR` (Stars) — hardcoded by Telegram for the Stars system. You cannot use USD or EUR. |
| Refund policy? | You cannot refund Stars yourself — Telegram handles disputes. State this clearly in `/subscribe`. |
| Minimum viable test? | One paying subscriber (yourself) completing the full flow before showing it to students. |

---

### F-15 — Subscription tier with two-layer rate limits

**Goal:** mirror Claude's dual-limit model — a short-window burst cap that resets every few hours, and a longer weekly cap. Subscribed users get higher limits than free users.

**Recommended window:** 3 hours (not 5). Claude's 5-hour window works for a general-purpose assistant used sporadically. Karly sessions are tighter — a student does a lesson, puts the phone down, and comes back later. 3 hours matches that rhythm and feels more generous without being exploitable.

**Proposed tiers (starting point, tune after launch):**

| Tier | Session cap (resets every 3 h) | Weekly cap | Cost |
|------|-------------------------------|-----------|------|
| Free | 10 messages | 40 messages | $0 |
| Subscriber | 40 messages | 200 messages | TBD (Telegram Stars) |
| Teacher / Superuser | Unlimited | Unlimited | — |

**How it works:**
- Two counters per user: `session_count` (expires after 3 h from first message in window) and `week_count` (expires at Monday 00:00 UTC).
- Both counters live in the DB alongside `last_session_start` and `week_start` timestamps.
- On every metered handler: check session cap → check weekly cap → proceed or reply with a friendly limit message that tells the user when the window resets.
- Subscribed flag: `users.subscribed` bool column; set `True` on `successful_payment`, cleared if subscription lapses.
- The existing credit system (daily cap, pool) becomes a teacher-level tool for classroom budgets. The subscription caps are a separate public-facing control.
- When a cap is hit, the limit message includes a button to buy extra messages (see F-21 — top-ups). Draw-down order: session allowance → weekly allowance → top-up credits.

**Message copy (limit hit):**
- Session: *"You've reached today's session limit. I'll be ready again at [time]. Subscribe for more practice time!"*
- Weekly: *"You've used your week's messages. Your limit resets on Monday. Subscribe to keep going!"*

---

### F-16 — Telegram Stars payment flow

**Overview:** Telegram's native payment system using Telegram Stars (XTR) — no external payment processor, no credit card required from the user. Stars are bought inside the Telegram app itself.

**Flow:**
1. User sends `/subscribe`.
2. Bot sends an invoice (`bot.send_invoice`) with title, description, payload, provider token `""` (Stars use an empty token), currency `"XTR"`, and prices list.
3. Telegram shows a native Stars checkout screen.
4. On completion, Telegram delivers a `PreCheckoutQuery` — bot must answer it within 10 seconds (`answer_pre_checkout_query(ok=True)`).
5. Telegram then delivers a `Message` with `successful_payment`. Bot sets `users.subscribed = True` and notes the expiry (e.g., 30 days from now).

**Handlers needed:**
- `CommandHandler("subscribe", subscribe_handler)` — sends invoice
- `PreCheckoutQueryHandler(pre_checkout_handler)` — always answers ok (validation happens here if needed)
- `MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_confirmed_handler)` — flips the flag, DMs the user a confirmation

**What you need to test this:**
1. Your bot must be registered with BotFather → `/mybots` → Payments → connect to "Telegram Stars" (this is free, no external provider needed).
2. Stars payments work in **any** Telegram client (desktop, mobile) — no special sandbox, but you can use a test environment via BotFather's `/newbot` test instance on `@BotFather` with the `test` server flag.
3. In production you cannot refund Stars yourself — Telegram handles disputes. Document this in your `/subscribe` message.
4. Minimum price is 1 XTR. Suggested starting price: 100 XTR/month (~$1.99 at current exchange; price is set in Stars, not dollars).
5. After wiring the handlers, send `/subscribe` in your own chat with the bot and complete the checkout. Check that `users.subscribed` flips to `True` in the DB.

**Expiry / renewal:** Telegram Stars has no native recurring billing. Two options:
- **Simple:** set a 30-day expiry timestamp; a daily job checks and clears `subscribed` on lapse. User must re-subscribe manually.
- **Future:** remind the user 3 days before expiry with a `/subscribe` nudge.

---

### F-17 — `/addword <word>` personal vocabulary command

**Goal:** a student types `/addword Schadenfreude` and the bot fetches a definition + example sentence, confirms, and inserts a flashcard into their personal deck.

**Flow:**
1. Parse the word from the command argument; reject if empty.
2. LLM call (`Task.lookup`): return JSON `{word, definition, example_sentence, part_of_speech}` in the student's target language pair.
3. Bot replies with a formatted card preview:
   > **Schadenfreude** *(noun)*
   > pleasure derived from another's misfortune
   > *"Er konnte seine Schadenfreude kaum verbergen."*
   > Added to your vocabulary deck ✓
4. Insert a `Flashcard` row with `deck="personal"`, front = word, back = definition + example.
5. The card enters the normal HLR scheduler — appears in `/review` like any other card.

**Edge cases to handle:**
- Word already in the student's deck → reply "Already in your deck — good to review it!" and skip insert.
- Unknown word / LLM returns empty → reply with an error message.
- `/addword` with no argument → reply with usage hint.

**Teacher extension (future):** `/addword` by a teacher in a class context could add the word to all students' decks in that class.

---

### F-18 — Teacher broadcast messages

**Goal:** let a teacher send a message to all their students, or to students in a specific class, without leaving Telegram.

**Commands:**
- `/broadcast <message>` — sends to all of the teacher's students across all classes.
- `/broadcast <class_name> <message>` — sends only to students in that class.
- Superuser: `/broadcast all <message>` — sends to every user in the system.

**Flow:**
1. Teacher sends the command.
2. Bot shows a confirmation: *"Send this to 14 students in German A2? [Send] [Cancel]"* (inline buttons).
3. On confirm, bot iterates student `telegram_id`s and calls `bot.send_message` for each.
4. Bot replies to the teacher with a delivery summary: *"Sent to 14/14 students."* (or notes any blocked/deactivated accounts).

**Safety guards:**
- Rate-limit the sends (e.g., 1 message per 50 ms) to stay inside Telegram's flood limits (30 messages/second global, 1 message/second per user).
- Log broadcasts in a new `broadcasts` table: `id, teacher_id, class_id (nullable), message_text, sent_at, recipient_count`.
- Students cannot reply to a broadcast — or if they do, it goes to their normal teacher DM.

**Superuser note:** the superuser `/broadcast all` should have a second confirmation step given the blast radius.

---

### F-19 — Placement assessment on first join

**Goal:** every new student gets a placement test shortly after approval instead of starting cold at A1.

**Flow:**
1. Approval flow already sends a welcome message. Immediately after that, bot sends: *"Before we start, I'd like to give you a quick placement quiz (about 5 minutes). This helps me set the right level for you."* with buttons: **[Start now]** **[Do it later]** **[Skip — I know my level]**.
2. **Start now:** launches a condensed version of the existing `/test` placement flow (A1 → A2 → B1 sequence, cut to ~10 questions).
3. **Do it later:** sets a reminder for the next time the student sends any message — bot re-prompts once before dropping the offer.
4. **Skip — I know my level:** bot sends a level picker (A1 / A2 / B1 / B2 / C1) as inline buttons; student taps one; level is set.

**Result handling:** same as `/test` — CEFR level written to the user row, correction level auto-set to match (F-5 logic), student gets a summary.

**Data model:** add `placement_status` enum column to `users`: `pending | completed | skipped`. Guards in the test flow prevent double-running.

**Teacher visibility:** `/roster` could show a small icon next to students who haven't completed placement, so the teacher can nudge them.

---

### F-20 — Impostor game inline keyboard hub

**Goal:** `/impostor` alone (no subcommand) shows a rich inline keyboard so the game is fully discoverable and button-driven, not command-driven.

**Hub layout (first screen):**

```
🕵️ The Impostor
[▶ Start new game]   [📋 Rules]
[📊 My stats]        [🏆 Leaderboard]
[🔄 Resume game]     [❓ Help]
```

**In-game buttons (during an active round):**

```
[🗳 Submit answer]   [👥 Vote]
[💬 My clue was…]    [🏳 Quit round]
```

**Rules screen:** inline message (no new screen) with a Back button.

**Stats screen:** shows wins / rounds played / times caught as impostor — sourced from a `impostor_stats` table or the existing game log.

**Leaderboard screen:** top 5 players (scoped to the teacher's class if the student is enrolled, global otherwise).

**Design principle:** every action a user can do in the game should be reachable from a button. Only the initial `/impostor` command needs to be typed. All subsequent interaction is inline buttons — friendlier on mobile.

**State management note:** the existing game state dict in memory will need a `message_id` field so the bot can edit the hub message in-place (rather than sending new messages) when a button is pressed.

---

### F-21 — Credit top-ups (buy extra messages when allowance runs out)

**Goal:** when a user hits their session or weekly cap, they can buy a pack of extra messages with Telegram Stars instead of waiting for the reset. This is separate from the subscription — it's a one-time purchase, not a recurring plan.

**Analogy:** Claude's "buy more compute" button that appears when you hit your usage limit.

**How it surfaces:**
- When the bot sends the limit-hit message (F-15), it appends a button: **[Buy 20 extra messages — 50 ⭐]**
- User can also reach it anytime via `/topup`.

**Credit pack options (starting point):**

| Pack | Extra messages | Stars price | Notes |
|------|---------------|-------------|-------|
| Small | 10 | 25 ⭐ | ~$0.50 — impulse buy |
| Medium | 30 | 60 ⭐ | ~$1.20 — best value per message |
| Large | 75 | 120 ⭐ | ~$2.40 — power users |

Prices and sizes should be tuned after launch based on usage patterns.

**Flow:**
1. User taps the top-up button or sends `/topup`.
2. Bot replies with the three pack options as inline buttons.
3. User taps a pack → bot sends a Stars invoice for that pack (same `send_invoice` + `PreCheckoutQueryHandler` flow as F-16).
4. On `successful_payment`: add the purchased message count to a `topup_credits` int column on the user row.
5. Bot confirms: *"20 extra messages added to your account. They don't expire."*

**Credit draw-down order:**
When a user sends a message, check allowance first; only draw from `topup_credits` after the session and weekly allowance are exhausted. This way top-up credits feel like a safety net, not the primary path — which nudges users toward the subscription for heavy use.

**No expiry on top-up credits:** unlike the timed allowance windows, purchased credits should never expire. The user paid for them.

**Data model additions:**
- `users.topup_credits` — int, default 0; incremented on purchase, decremented per metered message after allowance is exhausted.
- Log each top-up in the `payments` table (same table as subscriptions from F-16, with a `kind` column: `subscription | topup`).

**Interaction with subscription (F-15):**
- Subscribers still get their higher session/weekly caps first; top-up credits only kick in when those are spent too.
- Free users hitting their 10-message session cap see the top-up offer immediately — this is the main monetisation touchpoint for non-subscribers.

---

### F-22 — Media comprehension grading

**Goal:** the teacher shares a short film, audio clip, or song with their class and posts a reference summary. Each student writes their own summary in the target language. The bot grades it automatically — checking comprehension, vocabulary, and grammar — and gives the student a score with feedback.

**Teacher side — `/setmedia`:**
1. Teacher sends `/setmedia` in their DM with the bot.
2. Bot asks for (a) a title/description of the media (e.g., "German short film: *Die Brücke*, 4 min"), (b) an optional URL or note telling students where to find it, and (c) the reference summary the teacher wrote (the "answer key" the bot will grade against).
3. Teacher optionally scopes it to one class or all classes.
4. Bot confirms: *"Media task saved for German A2 — 12 students will see it when they send `/task`."*

**Student side — `/task`:**
1. Student sends `/task`.
2. Bot shows the active media task: title, where to find it, and the prompt — e.g., *"Watch the clip, then send me a summary in German (4–6 sentences)."*
3. Student watches/listens and replies with their summary (plain text, not a command).
4. Bot grades the submission against the teacher's reference summary using an LLM rubric (see below) and replies with:
   - A score (e.g., 8/10)
   - Comprehension feedback: *"You caught the main event but missed the reason the character left."*
   - Language feedback: key grammar or vocabulary corrections (same pipeline as existing corrections, scoped to the student's correction level)
5. The result is logged so the teacher can see it in a future `/results` view.

**Grading rubric (LLM prompt):**
The bot sends the student summary + teacher reference to the LLM with a structured prompt asking it to score on three axes:
- **Comprehension (0–4):** how much of the key content was captured
- **Accuracy (0–3):** no invented details that weren't in the media
- **Language (0–3):** grammar, vocabulary, and fluency in the target language

Total: 10 points. The LLM returns JSON `{comprehension, accuracy, language, total, feedback_comprehension, feedback_language}`.

**Commands summary:**
- `/setmedia` — teacher creates or updates the active media task for a class
- `/task` — student retrieves the current task and submits their summary
- `/results` — teacher views all student submissions + scores for the active task (table: student name, score, submitted at)
- `/clearmedia` — teacher closes the task (no more submissions accepted)

**Data model additions:**
- `media_tasks` table: `id, teacher_id, class_id (nullable), title, media_url, reference_summary, created_at, closed_at`
- `media_submissions` table: `id, task_id, student_id, submission_text, score_comprehension, score_accuracy, score_language, score_total, feedback, submitted_at`

**Edge cases:**
- Student submits before watching → grading will reflect it; no way to enforce viewing, but score speaks for itself.
- Student submits multiple times → only the latest submission counts (teacher sees revision history).
- No active task → `/task` replies: *"No media task right now — check back later."*
- Task closed → bot tells the student submissions are no longer accepted.

**Language note:** feedback is delivered in the student's interface language (English for German learners, Spanish for English learners), matching the existing correction pipeline behavior.

---

## Future directions

### Interactive multiplayer games (brainstorm)

All of these are group activities like The Impostor — they work best when several students from the same class are online at the same time. A host (student or teacher) creates a room, shares a code, and others join.

---

**Word Duel** — two players, one word
One player picks a word; both independently write a sentence using it in the target language; the rest of the group votes for the more natural sentence. The loser gets a correction from the bot on why theirs fell short. Fast, low-stakes, works with 3+ players.

---

**Alibi** — story under interrogation
One player is accused of something harmless (e.g., "you ate the last piece of cake at 8pm"). They have 90 seconds to whisper an alibi to one partner. The rest of the group then interrogates each suspect separately — in the target language — looking for contradictions. Great for practising past tense and spoken-style fluency. Works with 4–8 players.

---

**Word Chain (Wortkettel)** — last letter, next word
Classic chain game: the last letter of each word must start the next. Played in the target language; the bot validates that the word is real and disqualifies repeats. Timed turns (30 seconds). A player is eliminated when they can't produce a valid word. Works with 2+ players; bot acts as referee.

---

**Hot Take** — argue a position in L2
Bot generates a mild controversial prompt ("Homework should be banned"). Each player writes 1–2 sentences defending a randomly assigned side — in the target language. The group votes on who argued most convincingly. Bot gives grammar feedback to everyone after the vote. Good for B1+ students; no minimum player count (works solo as a writing drill too).

---

**20 Questions (in the target language)**
One player thinks of a person, place, or thing. Others take turns asking yes/no questions — only in the target language. The bot enforces language (rejects questions in the wrong language) and tracks the count. First correct guess wins. Works with 2+ players; bot acts as moderator.

---

**Story Relay** — collaborative sentence chain
Each player adds one sentence to a growing story in the target language. The bot corrects each sentence silently (stores errors) and, when the story ends (by vote or after N turns), posts a full story recap with all corrections highlighted. Minimum 2 players; no max.

---

**Taboo** — describe the word without using it
Bot assigns a secret word + 3 forbidden helper words. The describer has 60 seconds to get their team to guess — in the target language only. Bot acts as buzzer: if the describer uses a forbidden word or switches language, the team loses a point. Works with 4+ players split into two teams.

---

**Notes on feasibility:**
- All of these share the same hosting pattern as Impostor (room code, join flow, turn management in a dict).
- The bot-as-referee role (validating words, enforcing language, tracking turns) is the part that needs the most careful prompt design.
- Games with a voting mechanic are the most engaging but require all players to be active at the same time — best suited for scheduled class sessions.
- Word Chain and 20 Questions are the easiest to implement first (minimal LLM involvement, clear win/loss states).

---

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
