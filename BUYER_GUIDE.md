# Karly — Buyer's Guide: Costs, Revenue, and Path to Profit

*For prospective buyers evaluating Karly as a teachable, scalable language-learning business.*

---

## What you're buying

A fully working, self-hosted Telegram language-tutor bot. Not a prototype — it runs in production today. Two languages (German and English) are live, with a complete A1–C1 structured course for English (132 units, 1,848 banked questions), spaced-repetition flashcards, placement tests, roleplay scenes, classroom management, and a payment system already coded and waiting to be activated.

The only things left between "personal project" and "student-facing business" are:

1. Point it at a real server instead of a home desktop.
2. Activate the Stripe account and Telegram Stars payments.
3. Set your own price and open the door.

---

## Section 1 — What it costs to run

### 1.1 Infrastructure

| Component | What you pay | Realistic monthly cost |
|---|---|---|
| **VPS / cloud VM** | A $6–12/month VPS handles hundreds of students with no problem. The bot is async and lightweight — one Python process, one SQLite file. | **$6–12/month** |
| **Postgres (when you're ready to scale)** | Neon free tier covers the first ~3 GB. You won't need a paid plan until you're past a few hundred active students. | **$0–25/month** |
| **Domain + SSL** | Optional. The bot talks to Telegram's servers directly — no public web endpoint is required unless you switch to webhooks. | **$0–15/year** |
| **Backup storage** | The nightly backup script ships with Karly. An S3-compatible bucket (Backblaze B2, etc.) for offsite copies runs cents a month. | **$0–2/month** |

**Infrastructure floor: ~$6–12/month.** That's enough to serve your first 50–200 students.

---

### 1.2 AI / LLM costs

This is where most AI products bleed money. Karly is engineered to keep this cost low.

**How Karly minimises LLM spend:**

- **Structured exercises cost almost nothing.** The 1,848 banked course questions are stored on disk and checked locally — no LLM call when a student answers an MCQ or cloze question. A 14-question course unit makes only 2 LLM calls total, no matter how many students retake it.
- **The free tier of Groq covers a lot.** Karly's primary model is Groq (currently free). For a class of 20–50 students doing a mix of conversation and structured course work, you may stay entirely on free tiers for months.
- **Gemini is the fallback.** Also free tier. Karly only falls back when Groq is rate-limited.
- **Ollama (local model) is the last resort.** If you're running on a machine with a GPU, conversation traffic costs literally $0.

**When do you actually start paying for LLM?**

At ~100–200 active daily users doing heavy conversation, you'll begin hitting Groq's free-tier limits and need a paid plan. Groq's paid tier is consumption-based and very cheap per token. At that point you're already pulling in meaningful revenue (see Section 2) and LLM cost is a fraction of it.

**Conservative estimate at 100 active students (mixed conversation + course use):**

| Service | Estimated monthly cost |
|---|---|
| Groq (paid tier, primary LLM) | $5–20 |
| Gemini (fallback, minimal use) | $0–5 |
| Total LLM | **$5–25/month** |

---

### 1.3 Payment processing fees

Both payment methods are already coded in Karly.

| Method | Fee structure | What you keep on a $4.99 sale |
|---|---|---|
| **Stripe (card)** | 2.9% + $0.30 | **~$4.54** |
| **Telegram Stars (desktop)** | ~30% Telegram fee + exchange spread | **~$4.49** |
| **Telegram Stars (iOS/Android)** | Apple/Google 30% + Telegram + exchange | **~$3.12** |

Card payments via Stripe are the most efficient. Stars are the lowest friction for students who don't have a card handy. Karly already shows both options side-by-side and tells students which is the better deal.

---

### 1.4 Full cost summary

| Students | Infrastructure | LLM | Total monthly cost |
|---|---|---|---|
| 0–50 (launch) | $8 | $0 | **~$8/month** |
| 50–150 (growth) | $12 | $10 | **~$22/month** |
| 150–500 (scale) | $25 | $30 | **~$55/month** |
| 500–2000 | $60 | $80 | **~$140/month** |

At 500 students, $140/month in costs. At the pricing already set (see Section 2), that's covered by fewer than 30 subscribers.

---

## Section 2 — How to make money

The monetisation system is already built and waiting. There are three revenue streams.

---

### 2.1 Monthly subscriptions

**Price already set in the code:**

| Product | Card (Stripe) | Telegram Stars |
|---|---|---|
| Monthly subscription | **$4.99/month** | **250 ⭐ (~$6.50)** |

The Stars price is intentionally higher — it offsets the higher fee and signals that card is better value without being dishonest about it.

**What the free vs. paid tiers look like (already coded):**

| | Free | Subscriber |
|---|---|---|
| Messages per session (3 h window) | 10 | 40 |
| Messages per week | 40 | 200 |
| Full A1–C1 structured course | ✅ | ✅ |
| Flashcards, quiz, daily challenge | ✅ | ✅ |
| Conversation (beyond limits) | ❌ | ✅ |

Free students get enough to try the course and fall in love with the product. They hit the limit right when they're most engaged — exactly when they're most likely to subscribe.

---

### 2.2 Top-up credit packs

For free students who hit their limit and don't want to commit to a subscription yet. Also coded:

| Pack | Stripe | Telegram Stars |
|---|---|---|
| Small — 15 messages | $0.99 | 75 ⭐ |
| Medium — 40 messages | $1.99 | 150 ⭐ |
| Large — 100 messages | $3.99 | 300 ⭐ |

The buy button appears automatically when a student hits their limit. No extra marketing needed — the friction creates the conversion moment.

---

### 2.3 Teacher / classroom accounts

This is the highest-value revenue stream and is also already built. A teacher brings 10–30 students with them. Features they already have access to:

- Create and manage classes (`/newclass`, `/classes`, `/assign`)
- Set per-class correction strictness and conversation topics
- Set per-student daily message budgets
- Broadcast messages to the whole class
- View skill error rates and progress per student
- Assign specific course units as homework (`/assignunit`)
- Export student progress as CSV (`/export`)
- Run media comprehension tasks with LLM grading

**Pricing for teacher accounts is not yet set** — this is intentionally left to the buyer to calibrate for their market (solo tutors, language schools, corporate training). A reasonable starting point:

| Tier | Monthly price | Student seats |
|---|---|---|
| Solo teacher | $19/month | up to 15 students |
| Small school | $49/month | up to 50 students |
| School+ | $99/month | up to 150 students |

A single language school paying $49/month generates more revenue than ten individual subscribers and requires less support.

---

## Section 3 — Revenue projections

### Conservative: small tutor audience

| Metric | Value |
|---|---|
| Free students | 80 |
| Paid subscribers | 20 at $4.99 | 
| Top-up buyers | 5 at $1.99 avg |
| Monthly revenue | **$109.75** |
| Monthly costs | ~$22 |
| **Monthly profit** | **~$88** |

### Moderate: one teacher + their students

| Metric | Value |
|---|---|
| Teacher account | $49/month |
| Teacher's 25 students | 15 subscribe at $4.99 |
| Top-up revenue | $15 |
| Monthly revenue | **$138.75** |
| Monthly costs | ~$22 |
| **Monthly profit** | **~$117** |

### Growth: 3 teachers, own audience

| Metric | Value |
|---|---|
| 3 teacher accounts | 2 × $49 + 1 × $19 = $117 |
| 150 individual students (40% subscribe) | 60 × $4.99 = $299.40 |
| Top-up revenue | $40 |
| Monthly revenue | **$456.40** |
| Monthly costs | ~$55 |
| **Monthly profit** | **~$400** |

---

## Section 4 — What's still needed to open publicly

These are the only remaining steps. None require code changes — they are configuration and activation tasks.

| Step | Effort | Notes |
|---|---|---|
| Activate Stripe account | 15 minutes | ID + bank account; then paste the API key into BotFather |
| Activate Telegram Stars payments | 2 minutes | BotFather → Payments → select Stars |
| Move to a VPS | 1–2 hours | The deploy checklist (`deploy/DEPLOY_CHECKLIST.md`) walks through every step |
| Set teacher pricing and write the sales page | A few hours | The product sells itself once someone tries it |
| End-to-end payment smoke test | 30 minutes | Checklist is already written in `FUTURE_WORK.md §PAY` |

The payment code exists and the checklist is written. "Activating payments" is literally connecting accounts and running the test checklist.

---

## Section 5 — What comes next (upside)

These are planned features that would increase revenue without being required to launch:

| Feature | Revenue impact |
|---|---|
| **Voice input** (Phase 5 — code outline exists) | Higher perceived value, justifies a price increase |
| **German A1–C1 course** | Opens the German-learner market with the same course engine |
| **Reading / writing tracks** | Additional course sections per level — more content without new infrastructure |
| **Multiplayer games** (G-1 through G-8, fully specced in `GAMES_PLAN.md`) | Group play in classrooms — natural upsell for teacher accounts |
| **More language pairs** | The architecture is language-agnostic; adding Spanish→French or French→English is content work, not engineering |

---

## Section 6 — What you don't have to build

Everything below is already done and working in production:

- Dual-language tutor (German + English)
- A1–C1 structured English course (132 units, 1,848 questions)
- Spaced-repetition flashcard system (HLR scheduler + BKT mastery tracking)
- Adaptive placement test
- Daily challenges, rapid quiz, roleplay scenes
- Classroom management (teacher roles, class assignment, budgets, CSV export)
- Subscription + top-up payment system (code complete, needs activation)
- Rate limiting, concurrency queue, credit metering
- Nightly database backup
- Superuser + teacher approval flow
- Two-bot architecture (German bot + English bot from one codebase)
- Deployment scripts and systemd service files

The product is not a codebase to be finished. It is a running product to be launched.

---

## Section 7 — Risk factors (be honest with yourself)

| Risk | Reality |
|---|---|
| **LLM cost spike** | At scale, LLM is a real line item. Karly mitigates this with banked questions and a free-tier-first ladder, but you need to monitor it at 200+ students. |
| **Telegram dependency** | The entire product lives on Telegram. If Telegram changes its bot API or Stars terms, you adapt or migrate. The risk is real but Telegram's bot ecosystem is very stable. |
| **Stars payout complexity** | Stars → TON → Exchange → Bank is not a one-click bank transfer. It works, but it takes a few steps and involves crypto. Card payments via Stripe are simpler. |
| **Content gaps** | German course content does not exist yet — only conversation and flashcards. Building A1–C1 for German using the same pipeline would take several focused sessions. |
| **Solo founder bottleneck** | The codebase is well-structured but was built by one person. Onboarding a second developer would require time to understand the architecture. |

---

*Document generated 2026-09-09. All pricing, costs, and figures are estimates based on current free-tier limits and exchange rates, which change. Verify LLM pricing and Telegram Stars rates before setting your own prices.*
