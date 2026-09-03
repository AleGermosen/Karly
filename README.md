# Karly 🇩🇪

A personal German-tutor Telegram bot. You write in German, Karly corrects you, drills your vocabulary on a spaced-repetition schedule, runs placement tests, quizzes you on your weak spots, and plays roleplay scenes with you — all inside Telegram, no app install required.

Built for one user (me), deployed on a home OptiPlex server, free to run.

---

## What it does

| Feature | How it works |
|---|---|
| **Conversation + corrections** | Write anything in German. Karly replies at your level and marks every mistake `❌ wrong → ✅ right — why`. Three levels: strict / relaxed / off. |
| **Adaptive placement test** `/test` | 8–12 mixed items (MCQ + open), covering grammar, reading, comprehension, production, functional, and vocab. Difficulty adapts in real time. Per-skill CEFR verdict at the end. |
| **Flashcards** `/practice` | HLR-scheduled spaced repetition. Four modes: flashcard, cloze, MCQ, sentence-check. Deck picker (All / Chat / Docs / Test) and DE↔EN direction toggle with `/flip`. |
| **Daily challenge** `/daily` | One LLM call → 3 tasks: fill-the-blank, translate, reply to a real situation. Auto-checked locally. Feeds the practice streak. |
| **Rapid quiz** `/quiz` | 7 MCQ items targeting the 3 skills with lowest BKT mastery. Tap buttons, instant feedback, mastery updates live. |
| **Roleplay scenes** `/roleplay` | Six scenarios: supermarket, office standup, doctor, restaurant, job interview, explaining a technical problem. Karly plays the character; `/done` gives an English debrief. |
| **Weekly report** `/weekly` | Sessions, card-review accuracy vs. prior week, top error patterns, BKT skill bars — plus an LLM paragraph synthesising everything. |
| **PDF vocabulary** | Send a German engineering PDF → Karly extracts terminology into flashcards and can run a lesson from it (`/learn`). |
| **Skill mastery (BKT)** | Bayesian Knowledge Tracing tracks mastery probability per skill at the CEFR level it was tested at. Shown in `/profile` as `Grammar (A2): ███████░░░ 70%`. |
| **HLR scheduling** | Half-Life Regression replaces SM-2's fixed multiplier. Every review is logged; next review is scheduled when predicted recall hits 90%. |
| **DKT LSTM** | TensorFlow LSTM over full review history. Gated: activates automatically when ≥ 50 reviews are logged and TensorFlow is installed. |

---

## Commands

```
── Learning ──────────────────────────────────────────────────────────────
/practice      Flashcards — pick a deck and direction (also /flashcards)
/flip          Switch DE↔EN direction mid-session
/daily         3-task daily challenge (cloze + translate + reply)
/quiz          7-question MCQ targeting your weakest skills
/roleplay      Roleplay scene in German; /done for English debrief
/test          Adaptive placement test (~10 questions); /done to finish early

── Profile & Stats ───────────────────────────────────────────────────────
/profile       Level, skill mastery bars (BKT), due card count
/review        Streak, due count, hardest vocab by easiness factor
/weekly        Weekly report — accuracy trend, corrections, mastery
/summary       Review this session's mistakes and save them to flashcards

── Conversation Tools ────────────────────────────────────────────────────
/corrections   Set correction level: strict | relaxed | off
/topic         Steer the conversation to a topic (/topic clear to reset)
/english       Ask a meta-question about German in English
/remind        Daily reminder — /remind HH:MM to set, /remind off to clear

── Documents ─────────────────────────────────────────────────────────────
/docs          Your uploaded PDFs
/learn         Start a lesson from a document
/docfocus      Lock conversation to the latest document (on | off)
               Send any German PDF to extract vocabulary automatically.

── System ────────────────────────────────────────────────────────────────
/status        Backend ladder state + live Groq request quota
/backend       Show active model in every reply (on | off)
/cancel        Cancel an active session
/stop          End a running practice / quiz / daily / roleplay session
/help          Full command list
```

---

## Architecture

```
Telegram ──► python-telegram-bot 21 (async, long polling)
                │
                ├── ConversationHandlers
                │     assessment · practice · daily · quiz · roleplay
                │
                ├── LLM Router  (llm/router.py)
                │     ⚡ Groq openai/gpt-oss-120b   ← primary
                │     ⚡ Groq openai/gpt-oss-20b    ← fallback
                │     🤖 Gemini gemini-3.6-flash    ← structured tasks / fallback
                │     🐌 Ollama (local 3B)          ← chat only, last resort
                │
                ├── SRS  (srs/)
                │     hlr.py   Half-Life Regression scheduler
                │     bkt.py   Bayesian Knowledge Tracing (per skill + CEFR level)
                │     dkt.py   Deep Knowledge Tracing LSTM — TensorFlow, gated
                │     sm2.py   SM-2 (kept for stats compatibility)
                │
                └── SQLite via SQLAlchemy  (db/)
                      users · vocab_items · messages · assessments
                      review_logs · concept_mastery · practice_logs · documents
```

The router walks the ladder on every call and skips rungs on cooldown. Ollama is excluded from structured tasks — the 3B model can't reliably produce JSON.

---

## Setup

```bash
git clone https://github.com/AleGermosen/Karly.git
cd Karly
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and fill in:
#   TELEGRAM_BOT_TOKEN  — from @BotFather on Telegram
#   GEMINI_API_KEY      — from https://aistudio.google.com
#   GROQ_API_KEY        — from https://console.groq.com  (optional but strongly recommended)
#   ALLOWED_USER_ID     — your Telegram numeric user ID (locks the bot to you)
```

```bash
python -m bot.main
# The SQLite database (karly.db) is created automatically on first run.
```

---

## Deploy — home server (OptiPlex)

Karly runs as a systemd user service. Long polling means no public IP is needed.

```bash
# Add to ~/.bashrc on your dev machine (one-time):
export KARLY_REMOTE_DIR=PycharmProjects/Karly

# Daily workflow from dev machine:
make deploy    # git push → SSH pull → pip install → systemctl restart
make logs      # follow live logs
make status    # is the service running?
```

Full first-time and recurring instructions: [`deploy/DEPLOY_CHECKLIST.md`](deploy/DEPLOY_CHECKLIST.md).

---

## Cost

Everything runs on free tiers. With solo use (~1,500 LLM turns/month):

| Service | Cost |
|---|---|
| Groq (primary LLM) | $0 — free tier |
| Gemini (fallback) | $0 — free tier |
| Ollama (local) | $0 — runs on the server |
| SQLite | $0 |
| **Total** | **$0 / month** |

---

## Stack

- **Python 3.12**
- **python-telegram-bot 21** — async, ConversationHandler-based flows
- **SQLAlchemy** — ORM over SQLite
- **Groq** — primary LLM, OpenAI-compatible API
- **Google Gemini** — fallback and all structured JSON tasks
- **Ollama** — local last-resort model (no internet required)
- **numpy + tensorflow-cpu** — DKT LSTM (optional; bot works fine without them)
