# Karly — Roadmap & Future Work

Living plan for Karly's evolution. Updated 2026-09-03.

---

## TL;DR

**What's working today:** Dual-language tutor bot — German mode (native English speaker learning German, fully featured) and English mode (native Spanish speaker learning English, **now fully featured with all German-mode features**). Adaptive placement test, spaced-repetition flashcards (HLR scheduler, MCQ mode, deck picker, EN→ES/ES→EN flip), daily challenge, rapid quiz targeting weak skills, English roleplay scenes (6 scenarios), weekly progress report, PDF vocabulary extraction, social deduction game (The Impostor), open auth, BKT skill mastery, DKT LSTM (gated), systemd deploy on OptiPlex.

**What to build next (solo phase):**
1. **English mode should be in English** — the interface is currently Spanish; it should mirror German mode, with Spanish kept for explanations only
2. **Relaxed corrections should feel relaxed** — already the default, but it still corrects too much and tags slang. Nobody should feel judged for talking
3. **Games in `/help`** — The Impostor exists but is invisible
4. **English-mode polish** — small remaining items listed below (`/english` block, backend notice language)
5. Voice notes — speak German/English, get a text correction back
6. Assessment JSON hardening — retry/skip on bad output instead of raw dump
7. Manual grade override buttons on typed answers

**Next phase, planned:** give Karly a course — a topic list per CEFR level with a short
lesson and a set of exercises each, the way test-english.com is organised, written once
into the repo instead of invented live. **English runs the full ladder, A1 to C1**, built
one level at a time. Plan and pending tasks in [`CURRICULUM_PLAN.md`](CURRICULUM_PLAN.md).

**Also planned — classroom controls:** English mode is for your students, so the bot
needs a roster, an approve-before-joining gate, and a teacher view of who's using it and
how they're doing. See [Classroom phase](#classroom-phase--teacher-controls) below —
starting with Step 0, the blockers to clear before the first student joins.

**How many students fit for free?** Ungated: roughly **10–20**. **With the budget gates
planned in [Token budget](#token-budget--making-50-daily-students-fit) — 50 students all
using it daily**, which is the target. Enabling Groq's Developer tier is free and raises
that to 100+; beyond that it's about **$27/month**. Reasoning in
[Cost and capacity](#cost-and-capacity--how-many-students-fit-on-the-free-tier).

**When you're ready to open to the public:**
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

### Cost and capacity — how many students fit on the free tier

> ⚠️ **Verify these numbers before relying on them.** They're from public write-ups, not
> from your own dashboards, and providers change limits often. Check
> `console.groq.com` → Settings → Limits and `ai.google.dev` rate limits, and record what
> you actually see here.

**The free-tier limits that matter** (per organisation, not per key — extra API keys
don't help):

| Backend | Requests/day | Requests/min | Tokens/day |
|---|---|---|---|
| Groq `openai/gpt-oss-120b` (primary) | ~1,000 | ~30 | **~200K** ← the binding limit |
| Groq `openai/gpt-oss-20b` (fallback) | higher | ~30 | higher |
| Gemini Flash (fallback) | ~1,500 | **~10** ← the binding limit | effectively unlimited for us |
| Ollama, local | unlimited | unlimited | unlimited (but 3B, chat only) |

**The trap in that table:** Groq's 200K tokens/day sounds generous but a tutor turn is
~2,500 tokens, so the primary backend alone is **~80 conversation turns per day, for
everyone combined**. Gemini's 1,500 requests/day is the real workhorse, and its ceiling
is **10 requests per minute across all students at once**.

**Not all features cost the same** — this is the lever that decides your capacity:

| What a student does | LLM calls | Notes |
|---|---|---|
| `/practice` flashcard review | **0** | Pure local scheduling. Free forever |
| `/quiz`, `/course` exercises *after* the curriculum phase | **0** | Answers come from the committed bank |
| The Impostor game | **0** | No LLM in the game at all |
| `/course` unit, 15 questions | **2** | Only the write-your-own-sentence items |
| `/daily` | 1 | |
| One conversation message | 1 (~2,500 tokens) | **The expensive one** |
| `/test` placement | ~12 | One-off per student |

**So capacity depends on the activity mix, not the headcount:**

| Students | Mostly chatting | Mostly drilling (flashcards, course, games) |
|---|---|---|
| **10** | ✅ Comfortable | ✅ Effortless |
| **25** | ⚠️ Workable if spread through the day | ✅ Fine |
| **50** | ❌ Over the daily ceiling | ⚠️ Workable |
| **100** | ❌ No | ❌ No |

**Two things break before daily volume does:**

1. **Simultaneous use.** Thirty students opening the bot during the same lesson will hit
   30 requests/min instantly, whatever the daily budget says. **A whole class using it at
   once in a lesson is the hardest case, not the average day.**
2. **Falling off the bottom of the ladder.** When Groq and Gemini are both exhausted the
   only rung left is Ollama 3B, which can't produce reliable JSON — so `/test`, `/course`
   and `/quiz` **break rather than slow down**.

**Two moves, in order:**

- **Enable Groq's Developer tier — it's free.** You add a card and get roughly 10× the
  rate limits, still paying nothing until you actually spend. This is the single highest-
  leverage thing on this page and it takes five minutes. It moves 50 students from "no"
  to "comfortable".
- **Then pay, because it's cheap.** 100 students × ~15 turns/day ≈ 45,000 turns/month
  ≈ 90M input + 22.5M output tokens. At `gpt-oss-120b` rates ($0.15/M in, $0.60/M out)
  that's **roughly $27/month**. Infrastructure stays $0 while it runs on the OptiPlex.

**Honest summary:** *ungated*, the free tier comfortably covers **10–20 students**,
stretches to **~50** if they mostly drill rather than chat and don't all pile in at once,
and **will not** carry 100. The curriculum phase materially increases these numbers,
because banked exercises cost nothing to serve. Budget about **$27/month** for 100 active
students.

**With budget gates, 50 daily students is the design target and it fits** — see
[Token budget](#token-budget--making-50-daily-students-fit). Note that shortening the
conversation history and sharing one daily challenge per class are each worth more than
the gates themselves, because they raise the ceiling rather than dividing a fixed pie.

---

## Solo phase — what to build next

These are quality improvements that make sense before opening to other users.

---

### English-mode polish (remaining items)

Feature parity is **complete** as of 2026-09-03 — all five blocked handlers are unblocked, all UI strings have Spanish equivalents, all prompts are English-aware. What's left is cosmetic/minor:

| Item | File | What to do |
|---|---|---|
| Update `WELCOME_ENGLISH` | `bot/handlers/start.py` | Add `/practice`, `/daily`, `/quiz`, `/roleplay`, `/test`, `/weekly`, `/docs` to the welcome message — they now all work in English mode |
| Update `HELP_ENGLISH` | `bot/handlers/start.py` | Add all commands now available in English mode (same list as HELP_GERMAN but Spanish labels) |
| Block `/english` in English mode | `bot/handlers/conversation.py` | In `english()`: if user's `learning_mode == "english"`, reply "En modo inglés, usa /spanish para hacer preguntas en español." and return early |
| Spanish stale-correction message | `bot/handlers/conversation.py` | In `on_correction_action`, the "Diese Korrektur ist zu alt" line fires before mode is known — either look up the user there or keep it bilingual |
| Backend notices in Spanish | `bot/handlers/conversation.py` | `_BACKEND_NOTICES` and `_RECOVERED_NOTICE` are currently German+English; in English mode they should be Spanish+English. Low priority — backend transitions are rare. |

---

### English-mode feature parity (COMPLETE ✅)

English mode currently supports free conversation with corrections and `/spanish` meta-questions. Everything else — placement test, flashcards, daily challenge, quiz, roleplay, weekly report, PDF lessons — is either blocked or silently uses German prompts and German UI text. This section is the complete plan to reach parity.

**Context:** English mode = native Spanish speaker learning English. All UI text shown to the user should be in Spanish. Corrections are always explained in Spanish. The conversation itself is in English.

> **Superseded.** The Spanish-UI rule above was the wrong call — English mode should
> mirror German mode, with the interface in the language being learned and Spanish kept
> for explanations. The Spanish UI strings this phase produced get rewritten in English.
> See ["English mode should be in English"](#english-mode-should-be-in-english). The
> Spanish *teaching* content (correction reasons, debriefs, reports) built here stays.

---

#### Group 1 — New LLM prompts (all in `llm/prompts.py`)

These are the deepest change: every German-specific prompt needs an English counterpart. The model must understand it is teaching English to a Spanish speaker.

| Prompt constant | German original | English-mode equivalent needed |
|---|---|---|
| `TUTOR_PERSONA` | German tutor for AJ | Already done: `ENGLISH_TUTOR_PERSONA` ✅ |
| `CORRECTION_STRICT/RELAXED` | Corrections in English about German | Already done: `ENGLISH_CORRECTION_STRICT/RELAXED` ✅ |
| `ASSESS_INTERVIEW` | Adaptive German placement | `ENGLISH_ASSESS_INTERVIEW` — same structure (mcq/open, CEFR scale), but testing English grammar (articles, tenses, prepositions, phrasal verbs, word order). All prompts/options in English; instruction line in Spanish so the user understands what to do. |
| `ASSESS_VERDICT` | German CEFR verdict JSON | `ENGLISH_ASSESS_VERDICT` — identical JSON shape; skills renamed to English equivalents (grammar, reading, writing, vocabulary, listening-comprehension). Gaps should be English-specific issues, e.g. "phrasal verbs", "present perfect vs simple past". |
| `ASSESS_GRADE_OPEN_BATCH` | Grades open German answers | `ENGLISH_ASSESS_GRADE_OPEN_BATCH` — same JSON shape; judge whether the English answer is correct and grammatical; feedback line in Spanish. |
| `DAILY_CHALLENGE` | 3-item German challenge | `ENGLISH_DAILY_CHALLENGE` — same 3-item JSON structure (cloze / translate / reply), but: cloze sentence is in English with a Spanish gloss; translate = short Spanish sentence → user writes English; reply = a real-life English situation (email, voicemail, conversation). |
| `QUIZ_ITEMS` | German MCQ quiz | `ENGLISH_QUIZ_ITEMS` — same JSON shape; 4-option MCQ testing English skills (articles, tenses, prepositions, phrasal verbs, word order, vocabulary). Prompts in English with Spanish gloss; skill names adapted to English (grammar, vocab, reading, writing). |
| `ROLEPLAY_SCENE` | German roleplay | `ENGLISH_ROLEPLAY_SCENE` — same structure; character speaks English at the user's level; corrections on their own lines with Spanish explanations (❌ wrong → ✅ right — motivo en español); /done gives a Spanish debrief. |
| `SESSION_SUMMARY` | Analyses German mistakes | `ENGLISH_SESSION_SUMMARY` — same JSON shape; summary in Spanish; items list English corrections. Currently says "German sentences" and lists German grammar rules — must be replaced with English error patterns (tense mixing, missing articles, wrong prepositions, phrasal verb errors). |
| `WEEKLY_REPORT_SYNTHESIS` | German week summary in English | `ENGLISH_WEEKLY_REPORT_SYNTHESIS` — same structure; summary in Spanish; error patterns should be English-specific (not "dative after mit" but "confusion between present perfect and simple past"). |
| `CORRECTION_EXPLAIN` | Explains German grammar rule in English | `ENGLISH_CORRECTION_EXPLAIN` — explain the English grammar rule in Spanish (2-4 sentences per correction). |
| `CORRECTION_EXAMPLE` | German example sentence | `ENGLISH_CORRECTION_EXAMPLE` — give one new English example sentence using the corrected form, with a Spanish gloss. |
| `DOC_EXTRACT_TERMS` | German engineering terms | `ENGLISH_DOC_EXTRACT_TERMS` — extract useful English vocabulary (not necessarily engineering); still returns JSON with term/translation(Spanish)/context_sentence/importance. |
| `DOC_SUMMARY` | German document summary in English | `ENGLISH_DOC_SUMMARY` — summarise the English document in Spanish, 3-4 sentences. |
| `LEARN_LESSON` | German lesson from document | `ENGLISH_LEARN_LESSON` — same 3-part structure (dialogue / comprehension questions / cert-style tasks) but in English, with Spanish glosses, targeting the user's English CEFR level. |

---

#### Group 2 — Unblock and adapt the five blocked handlers

Each handler is currently blocked in English mode with a "solo para alemán" message. Here's what each needs:

**`/test` — assessment (`bot/handlers/assessment.py`)**
- Remove the block.
- The handler logic is fully language-agnostic (JSON shapes, state machine, BKT updates). Only the prompts and the intro/done text need to change.
- In `assess_start()`: check `learning_mode`; if `"english"`, use Spanish intro text and `ENGLISH_ASSESS_INTERVIEW` / `ENGLISH_ASSESS_VERDICT` / `ENGLISH_ASSESS_GRADE_OPEN_BATCH`.
- The BKT skill names (grammar, reading, comprehension, production, functional, vocab) map directly — no schema change needed.
- `_format_verdict()` output text is in German ("Dein Einstufungsergebnis" etc.) — needs a Spanish version.

**`/practice` and `/flashcards` — spaced repetition (`bot/handlers/practice.py`)**
- Remove the block.
- The SRS engine (HLR/SM-2/BKT) is entirely language-agnostic; vocab items are just `term` + `translation` strings.
- `_direction_label()` currently returns `"DE→EN 🇩🇪"` / `"EN→DE 🇬🇧"` — in English mode should return `"EN→ES 🇺🇸"` / `"ES→EN 🇪🇸"` (showing the user English and answering in Spanish, or vice versa).
- The deck picker text is all German ("Karteikarten", "Richtung", etc.) — needs a Spanish equivalent string, switching on `learning_mode`.
- `_pick_mode()` logic is fine as-is (it just determines flashcard vs cloze vs sentence vs MCQ).
- `practice_flip()` text is German — needs Spanish equivalent.
- `PRACTICE_SENTENCE_CHECK` prompt says `"German word/phrase"` — needs an `ENGLISH_PRACTICE_SENTENCE_CHECK` that checks whether the English term was used correctly in English, with feedback in Spanish.
- All in-session `reply_text` strings are German — switch on mode.

**`/daily` — daily challenge (`bot/handlers/daily.py`)**
- Remove the block.
- The handler logic (3-item JSON, state machine, scoring) is language-agnostic.
- Switch prompt: if `learning_mode == "english"`, use `ENGLISH_DAILY_CHALLENGE`.
- All user-facing strings ("Lückentext", "Übersetze", "Antworte", "Richtig! ✅", etc.) need Spanish equivalents.
- `_finish()` message is German — needs Spanish version.

**`/quiz` — rapid MCQ quiz (`bot/handlers/quiz.py`)**
- Remove the block.
- The quiz loop and BKT update are language-agnostic.
- Switch prompt to `ENGLISH_QUIZ_ITEMS` in English mode; skill names (grammar, vocab, etc.) already match.
- BKT skill names used in `_weakest_skills()` don't need to change — the skills (grammar, reading, comprehension, production, functional, vocab) are valid for English too.
- Intro text ("Fragen, fokussiert auf…"), per-question text, and finish text are German — needs Spanish versions.

**`/roleplay` — roleplay scene (`bot/handlers/roleplay.py`)**
- Remove the block.
- The scene list (`_SCENARIOS`) is German-specific (Bäckerei, Technik-Meeting, etc.) — English mode needs its own scene list (e.g., job interview, coffee shop, doctor's office, phone call, hotel check-in, grocery store).
- Easiest approach: define `_ENGLISH_SCENARIOS` dict alongside `_SCENARIOS`; in `roleplay_start()` pick which list to show based on mode.
- `_scenario_keyboard()` needs to be mode-aware.
- `_launch_scene()` switches prompt between `ROLEPLAY_SCENE` and `ENGLISH_ROLEPLAY_SCENE`.
- `scene_done()` debrief text is German — needs Spanish equivalent.

---

#### Group 3 — UI text / system messages that need Spanish versions

These are all the German-language strings shown to the user outside of LLM-generated content. Each needs a mode check and a Spanish alternative.

| Location | German string(s) | What to do |
|---|---|---|
| `conversation.py` | `QUOTA_MSG`, `ERROR_MSG` | Make both mode-aware constants, or pass mode into the function and pick the string |
| `conversation.py` | `_BACKEND_NOTICES`, `_RECOVERED_NOTICE` | Backend notices are currently bilingual German+English — in English mode, show Spanish+English instead |
| `conversation.py` | Correction action buttons: "📖 Warum?" / "➕ Beispiel" / "🎯 Üben" | In English mode: "📖 ¿Por qué?" / "➕ Ejemplo" / "🎯 Practicar" |
| `conversation.py` | `/corrections` command responses | All German — needs Spanish equivalents; switch on `learning_mode` |
| `conversation.py` | `/topic` command responses | German — needs Spanish equivalents |
| `conversation.py` | `/summary` output ("Auswertung", "Zu üben:", "zur Übung gespeichert") | German — needs Spanish |
| `start.py` | `/profile` output ("Dein Profil", "Noch kein Einstufungstest", "Gespeicherte Vokabeln", "Fällig zum Üben", "Skill mastery (BKT)") | Needs Spanish equivalents; switch on `learning_mode` |
| `report.py` | `/weekly` and `/review` output strings | German — needs Spanish equivalents |
| `practice.py` | All in-session strings | As noted in Group 2 |
| `documents.py` | `/docs`, `/learn`, `/docfocus` response text | German — needs Spanish equivalents; also prompts need to switch |

---

#### Group 4 — `/english` command behavior in English mode

Currently `/english` is available in English mode but makes no sense there (it asks the user to ask a meta-question "in English about German"). Options:
- Block `/english` in English mode and redirect to `/spanish` with a Spanish message.
- Or make `/english` silently redirect to `/spanish` behavior when in English mode.

Recommended: block it cleanly — "En modo inglés, usa /spanish para hacer preguntas en español."

---

#### Implementation order (completed 2026-09-03)

1. **Group 1** ✅ — all 14 English prompts written in `prompts.py`
2. **Group 2** ✅ — all five handlers unblocked and mode-aware: assessment, daily, quiz, roleplay, practice
3. **Group 3** ✅ — mode-aware UI strings across conversation.py, start.py, report.py, documents.py
4. **Group 4** ⏳ — `/english` block in English mode (see "English-mode polish" above)

---

### The Impostor — classroom social deduction game

A multi-device, classroom-friendly adaptation of Among Us. Karly acts as the silent game master: it assigns secret roles privately to each player's own phone, manages discussion rounds, collects votes, and announces results. Players are physically in the same room but each interact with the bot from their own device.

**Why it fits Karly:** the game is social deduction first — roles, discussion, voting. No tasks by default. The classroom setting is the context: students already have their phones and already know the bot.

---

#### Core concept

- **4–10 players**, each on their own phone, physically in the same room.
- One player (the host) creates a game and gets a short **game code** (e.g. `KARLY-4X7`). They share it verbally or show it to the group.
- Each other player opens their private chat with Karly and joins using that code.
- Roles are assigned and delivered **privately** to each player's own phone via DM from the bot. No spoiler tricks needed — only you see your phone.
- Players discuss the mystery **in person** (they're in the same room). The bot only handles role delivery and voting; it does not moderate the discussion.
- After discussion, each player votes privately through the bot. When all votes are in, the bot broadcasts the result to every player simultaneously.
- Game continues round by round until a win condition is met.

**Default mode is pure social deduction — no language tasks.** Tasks are an optional add-on (see "Task mode" below), not the default experience.

---

#### Win conditions

| Condition | Winner |
|---|---|
| All impostors are voted out | Crewmates win |
| Impostors equal or outnumber the remaining crewmates | Impostors win (crewmates can never form a majority to vote them out) |

---

#### The role card

When the game starts, the bot sends each player a private message with their role. This is the "text per user." It is simple by default:

> **You are a CREWMATE.** 👥
> There is 1 impostor among you. Find them.
> Game code: `KARLY-4X7` — Round 1

> **You are the IMPOSTOR.** 🔴
> Blend in. Don't get voted out.
> Your fellow impostor: _(none / Ana)_
> Game code: `KARLY-4X7` — Round 1

The role card can later be extended with LLM-generated flavour text (a character name, a backstory sentence) to make the social deduction richer, but that is a future enhancement, not the MVP.

---

#### Command set

| Command | Who | State | What it does |
|---|---|---|---|
| `/impostor new [impostors]` | Anyone | Any | Creates a new session. Generates a unique game code. Optional arg sets the number of impostors (default 1). Bot replies with the code to share. Clears any existing session from this chat. |
| `/impostor join <code> <name>` | Any online player | Lobby | Sent from each player's own chat. Registers them as an **online player** under that name. Bot confirms with a lobby list. Name must be unique within the session. |
| `/impostor add <name>` | Host only | Lobby | Registers an **offline player** by name — no phone, no Telegram account needed. Their role card will be shown on the host's phone during role reveal. Name must be unique. |
| `/impostor players` | Anyone | Any | Prints the current lobby list, indicating which players are online (📱) vs offline (👤). |
| `/impostor start` | Host only | Lobby | Closes the lobby (min 4 players total, online + offline). Shuffles and assigns roles. For online players: sends their role card privately via DM. For offline players: sends their role card to the host's chat, one per message, each wrapped in a spoiler tag with a "Show this to [Name] privately" label. |
| `/impostor vote <name>` | Any alive online player | Active | Records this player's vote for `<name>`. Bot confirms receipt privately. |
| `/impostor vote <voter> <target>` | Host only | Active | Proxy vote — host submits a vote on behalf of an offline player. Bot confirms. This is how offline players participate in voting: they tell the host who they want to eliminate, and the host enters it. |
| `/impostor skip [voter]` | Online player / Host | Active | Records an abstention. With no argument: the sender abstains. With a name argument (host only): proxy abstention for an offline player. |
| `/impostor status` | Anyone | Active | Shows the vote tally so far without revealing who voted for whom: e.g. `4/6 players have voted.` |
| `/impostor end` | Host only | Any | Aborts the game. Bot notifies all online players via DM. |

The host is the player whose chat started the session (ran `/impostor new`). Host-only commands check `game["host_chat_id"] == update.effective_chat.id`.

---

#### Full round flow

One round:

1. **Role phase (round 1 only):** bot sends each player their role card privately via DM.
2. **Discussion phase:** players talk in person. The bot is silent. No time limit imposed by the bot — the group decides when to vote.
3. **Vote phase:** each player sends `/impostor vote <name>` (or `/impostor skip`) to their own chat. Bot collects votes silently. Once every alive player has voted (or the host calls `/impostor start` as a vote-close shortcut — consider renaming to `/impostor close` post-start), bot tallies.
4. **Result broadcast:** bot sends a message to every player's chat simultaneously announcing: who was eliminated, how many votes they got, and whether they were crewmate or impostor. Example:
   > 🗳 Vote result — Round 1
   > **Ana** was eliminated (4 votes).
   > She was a **CREWMATE**. 🔵
   > Impostors survive. 5 players remain.
5. **Win check:** if a win condition is met, bot announces the winner to all players and the game ends. Otherwise, a new round begins — bot sends updated role cards (marked "Round 2") to all surviving players.

For subsequent rounds, crewmates only know that one player was eliminated and whether they were crewmate or impostor. Impostors still know each other. No new role card is needed unless a player wants to reconfirm — `/impostor role` can be used mid-game to re-display the player's current card.

---

#### State model

Stored in `context.bot_data["games"]` — a dict keyed by game code. This makes state global across all user connections, which is required since multiple users interact with the same session. No database table needed for MVP; state lives in memory (lost on bot restart, acceptable for a classroom game).

```python
context.bot_data["games"] = {
  "KARLY-4X7": {
    "host_chat_id": 123456789,
    "state": "lobby" | "active" | "ended",
    "impostor_count": 1,
    "round": 1,
    "players": {
      "Ana": {
        "chat_id": 111111111,  # None for offline players
        "online": True,        # False = added via /impostor add
        "role": "crewmate" | "impostor",
        "eliminated": False,
        "vote_this_round": None,   # target name or "skip"
      },
      "Carlos": {
        "chat_id": None,
        "online": False,       # offline player — no DMs, proxy voting
        "role": "impostor",
        "eliminated": False,
        "vote_this_round": None,
      },
    }
  }
}
```

**Online players** (`chat_id` is set): the bot DMs them directly for role cards and result broadcasts. `chat_id` is captured when they send `/impostor join`.

**Offline players** (`chat_id` is `None`): role cards are sent to the host's chat, wrapped in spoiler tags — `||YOUR ROLE: CREWMATE 👥||` — with a clear label: `📵 Show this to Carlos privately, then tap to hide again.` Offline players vote by telling the host verbally; the host submits the proxy vote. Offline players receive no broadcast DMs — the host reads results aloud or shows their phone.

For the broadcast `asyncio.gather(...)`, filter to online players only:
```python
await asyncio.gather(*[
    context.bot.send_message(chat_id=p["chat_id"], text=result_text)
    for p in game["players"].values()
    if p["online"] and not p["eliminated"]
])
```

---

#### Auth — open to all users

The bot is now open to any Telegram user — the single-user restriction is removed. This affects both the tutor and the game.

**Tutor (open to all):** remove the adoption logic from `bot/middleware.py`. The new rule is simple: any Telegram user who messages the bot gets a `User` row created automatically via `get_or_create_user`, and can use all tutor features with their own independent data. The `ALLOWED_USER_ID` env var stays as an optional hard restriction for private deployments, but it defaults to unset (open).

Changes needed in `bot/middleware.py`:
- `_is_authorized()` returns `True` for everyone when `ALLOWED_USER_ID` is not set
- Remove the `any_user_exists()` first-user-adoption check — it only made sense for a single-user bot
- `get_or_create_user()` already handles new users correctly; no change needed there

**Game commands specifically:** because the bot is now open, game commands don't need a special bypass at all — they can use `@require_auth` like everything else. The game code remains the practical access control (you need to know it to join a session), but auth is no longer a distinct problem to solve.

**Rate limiting / abuse:** the user has decided to defer caps and metering to later. This is acceptable for now — the bot runs on Groq's free tier, which self-limits via quota. Document this decision: metering is planned in the scale phase (see "Step 2 — Usage metering") and should be revisited before promoting the bot publicly.

> **Superseded for classroom use.** Open auth stays right for the game, but students need
> an approve-before-joining gate and per-student usage tracking. See
> [Classroom phase](#classroom-phase--teacher-controls) — it adds an access *mode* rather
> than reverting to single-user, so the game keeps working.

---

#### Broadcast implementation

When the vote closes, the bot must send a message to every player simultaneously. Python-telegram-bot's async model makes this straightforward:

```python
# pseudocode
await asyncio.gather(*[
    context.bot.send_message(chat_id=p["chat_id"], text=result_text)
    for p in game["players"].values()
    if not p["eliminated"]
])
```

This runs all DMs concurrently. Each player sees the result at essentially the same moment, which is important for the game's fairness.

---

#### Task mode (optional, not default)

In a future iteration, an optional `/impostor new --tasks` flag enables language tasks per round (one question per player before voting). This reuses the existing quiz/daily prompt infrastructure. The default game has no tasks.

This flag is not part of the MVP. It is noted here so the state model and command set are designed to accommodate it without a rewrite. When tasks are added, the round flow gains a "task phase" between role card and discussion, and the state model gains a `tasks_enabled` boolean and per-player task record.

---

#### File layout

- `bot/handlers/game.py` — all `/impostor` command handlers
- No new database models — state is in `context.bot_data`
- No new LLM prompts — MVP has no LLM calls during the game
- `bot/main.py` — register all `/impostor` subcommands as separate `CommandHandler("impostor_new")` etc., or handle subcommand routing inside a single `impostor` dispatcher function

**Note on command routing:** Telegram doesn't natively support subcommands (`/impostor new` vs `/impostor join`). The cleanest approach is a single `CommandHandler("impostor", impostor_dispatch)` that reads `context.args[0]` and routes to the right function. Alternatively, use separate commands (`/igame`, `/ijoin`, `/ivote`) — less readable but simpler to wire up.

---

#### Implementation order

1. **Open auth** — simplify `bot/middleware.py`: remove the first-user adoption check; `_is_authorized()` returns `True` when `ALLOWED_USER_ID` is unset. Test that a second Telegram account can access tutor commands independently.
2. Game code generator + session creation (`/impostor new`)
3. Online join flow + chat_id registration (`/impostor join`)
4. Offline player registration (`/impostor add`)
5. Lobby display with online/offline indicators (`/impostor players`)
6. Role assignment — DM to online players, spoiler cards on host's chat for offline players (`/impostor start`)
7. Vote collection — direct votes from online players, proxy votes from host for offline players (`/impostor vote`, `/impostor skip`, `/impostor status`)
8. Result broadcast to online players only; win check + game end (`/impostor end`)
9. Subcommand routing in `bot/main.py`

---

### English mode should be in English

**This reverses the principle the English-mode parity work was built on.** That work
stated: *"All UI text shown to the user should be in Spanish."* That's wrong for a
learner — it makes English mode feel like a Spanish app that occasionally speaks English,
when German mode feels like a German app. English mode should mirror German mode:
**the target language everywhere, the native language only where the user genuinely
needs it.**

The rule, stated once: **conversation and interface in the language being learned;
explanations and reports in the language they already speak.**

| Surface | German mode (the model to copy) | English mode today | Should be |
|---|---|---|---|
| The conversation itself | German | English ✅ | English ✅ |
| Menus, buttons, `/help`, `/profile`, `/review` | German | Spanish ❌ | **English** |
| Prompts inside `/practice`, `/daily`, `/quiz`, `/course` | German | Spanish ❌ | **English** |
| Error and quota messages | German | Spanish ❌ | **English** |
| The `— why` on a correction | English | Spanish ✅ | Spanish ✅ keep |
| Meta-questions (`/english` ↔ `/spanish`) | English | Spanish ✅ | Spanish ✅ keep |
| Roleplay debrief after `/done` | English | Spanish ✅ | Spanish ✅ keep |
| `/weekly`, `/summary`, document summaries | English | Spanish ✅ | Spanish ✅ keep |
| Vocabulary translations | English | Spanish ✅ | Spanish ✅ keep |

So the work is: **the Spanish UI strings written during the parity phase get rewritten in
English.** The Spanish *teaching* content — explanations, debriefs, reports — stays exactly
as it is. Roughly: `start.py`, `report.py`, `practice.py`, `quiz.py`, `daily.py`,
`roleplay.py`, `documents.py` UI strings switch; `llm/prompts.py` mostly doesn't.

**The A1 problem, and the fix.** An all-English interface is hostile to a true beginner —
and the plan is now to teach from A1 ([`CURRICULUM_PLAN.md`](CURRICULUM_PLAN.md)). So make
the amount of Spanish a setting rather than a constant:

| `l1_support` | Interface | Who |
|---|---|---|
| `full` | Spanish interface, Spanish explanations | A1–A2 |
| `minimal` | **English interface, Spanish explanations** ← the default | A2–B1 |
| `off` | Everything in English, including the `— why` lines | B2+ |

Default it from the placement test, let the user change it with `/language` or a similar
command, and nudge upward when they clear a level: *"Your English is good enough — want
me to switch the menus to English?"* That single question turns a settings toggle into a
small reward.

---

### Games should appear in `/help`

The Impostor exists (`bot/handlers/game.py`) but is invisible — it's in neither `/help`
nor the welcome message, so nobody who wasn't told about it will ever find it.

| Item | What to do |
|---|---|
| New `Games` section in `/help` | List `/impostor new`, `join`, `add`, `players`, `start`, `vote`, `skip`, `status`, `end` — grouped, not as nine flat lines |
| Same section in `/start` welcome | One line, not the full command list: *"🎭 /impostor — social deduction game for the class"* |
| Both language modes | German and English versions of the section |
| Make the structure extensible | Future activities land in the same section rather than each needing its own help edit |
| Consider `/games` | A short menu listing what's available, so `/help` doesn't grow forever. Worth it once there's a second game |

Small task, real payoff: a feature nobody can find has no users. Worth doing at the same
time as the `/help` and welcome-message updates already listed under English-mode polish
above — same files, same edit.

**Games sit outside the learning process, deliberately.** They're an add-on that makes
students want to open the bot, not a teaching tool. So:

| Rule | Why |
|---|---|
| **No corrections during a game** | Whatever the correction setting says. Being marked up mid-game kills it |
| **No mastery, BKT, or vocabulary capture from game messages** | Game chat is not evidence about their English. Letting it into the skill model would quietly poison `/profile` and `/quiz` targeting |
| **Doesn't count toward the practice streak** | The streak should mean study. Keep the reward honest |
| **Does count as activity** in `/students` and the class digest | You still want to know a quiet student is at least showing up |
| **Free to run** | The game makes no LLM calls, so it costs nothing against the quota — which makes it the right thing to point students at when capacity is tight (Step 0.6) |

Present them that way in `/help` too: a **Games** section clearly separate from the
learning commands, not mixed in among them.

---

### Relaxed corrections — the default, and genuinely relaxed

**Goal: nobody should feel judged for talking.** Students especially will go quiet if
every message comes back marked up. The bot should feel like a patient conversation
partner by default, and become a strict examiner only when asked.

**The rule in one line: relaxed mode cares about the important stuff and ignores the
rest — entirely.** Not "mentions it more gently", not "collects it for the end of the
message". Ignores it. A message with three small slips and clear meaning gets zero
corrections and a normal reply.

**Already done:** `correction_level` defaults to `"relaxed"` (`db/models.py`). No change
needed there — the default is right.

**What needs changing is what "relaxed" means.** Today's relaxed prompt still corrects
"wrong verb conjugation, badly wrong article gender", and slang always gets a 💬 tag even
though the prompt says slang isn't a mistake. Being tagged for saying something casually
is exactly the feeling to design out.

| Item | What to do |
|---|---|
| Loosen `CORRECTION_RELAXED` / `ENGLISH_CORRECTION_RELAXED` | Correct **only** what actually blocks understanding — a sentence a native speaker would misread. Not conjugation slips, not article gender, not prepositions, as long as the meaning lands. **Everything else is ignored completely** — not softened, not saved for later in the message, not mentioned |
| Say the quiet part in the prompt | The model should be told explicitly that **returning no corrections at all is the expected outcome for most messages**, not a failure to find any. Without that line an LLM will always find something |
| Hard cap | **At most one** correction per message, and none at all if the message is understandable. Today's "one or two" still reads as a licence to find something |
| Never flag | Typos, missing capitals or punctuation, contractions, casual register, incomplete sentences in a fast exchange |
| Slang | Silent in relaxed mode — drop the 💬 tag entirely. Keep it in strict, where the user has opted into being told. Slang is a sign of fluency, not an error |
| First messages | No corrections at all for a user's first few messages, or when returning after a break. Let them warm up |
| Tone rule in the persona | Explicitly: never comment on the *quality* of their language, never praise-then-correct ("Good try, but…"), never count mistakes |
| `/corrections` discoverability | Mention once, early, that corrections can be turned up: *"I'll mostly just chat. Want me to correct more? /corrections strict"* — then never mention it again |

**Nothing is lost by staying quiet.** Mistakes are still captured even when they aren't
shown: they feed `/summary`, the weekly report, the BKT skill model, flashcards, and — once
the classroom phase lands — your view of what the class is getting wrong. The learner
gets an uninterrupted conversation; you still get the data. That's the whole argument for
making relaxed the default, and it already works this way.

**Possible rename, worth considering:** `strict / relaxed / off` describes the machine's
behaviour, not the user's intent. Something like `exam / chat / off` — or letting the
student pick "correct me a lot / a little / not while we're talking" — reads better to a
nervous beginner. Cosmetic, but this is the setting most likely to be changed by someone
who is already feeling self-conscious.

---

### Voice notes (STT/TTS)

Let AJ speak a German or English sentence and receive a text correction back. Optionally have Karly read her reply aloud.

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

## Classroom phase — teacher controls

> **Why now:** English mode is for your students, not just you. The moment other people
> use the bot you need to know who they are, whether they're actually using it, and how
> they're doing. This phase is small and private — a handful of students you know, not a
> public launch. Everything in the Scale phase below stays deferred.

**This reverses one earlier decision.** The Impostor work opened the bot to everyone
(`_is_authorized()` returns `True` when `ALLOWED_USER_ID` is unset). For a class you want
the opposite: nobody gets in until you say so. The fix is a third mode rather than going
back to single-user — see "Access modes" below.

**Build this before the curriculum phase.** Students can already use conversation,
flashcards, `/quiz` and `/daily` — none of that waits on the course. What it does wait on
is knowing who they are and letting them in. See
[`CURRICULUM_PLAN.md`](CURRICULUM_PLAN.md) §7 for how the two plans meet.

---

### Step 0 — Blockers to clear before any student joins

Tasks, not observations. Found by reading both plans against the current code.

**Must be done before the first invite:**

| # | Task | Where | What to do |
|---|---|---|---|
| **0.1** | **Stop new students landing in German mode** | `db/models.py`, `bot/middleware.py`, approval flow | `learning_mode` defaults to `"german"`, so an approved Spanish-speaking student meets a German tutor and won't know `/language` exists. Set the language at approval time (you pick it when you tap Approve), or give each class a default language that new members inherit. **This is the one that breaks on day one** |
| **0.2** | **Define the first five minutes** | `bot/handlers/start.py` | Write the actual sequence a new student sees: welcome (in their language) → what this bot is → `/test` → their level → "here's what to do next". A class of beginners will not explore on their own. One screen, three taps, no jargon |
| **0.3** | **Measure real usage before inviting a class** | — | Run a week yourself and count turns. Compare against the free-tier ceilings in "Cost and capacity" above. Invite in waves — 5 students, then 15, then the rest — rather than 50 on day one |
| **0.4** | **Enable Groq's Developer tier** | Groq console | Free — add a card, get ~10× the rate limits, pay nothing until you spend. Five minutes, and it's the difference between 20 students and 50 |
| **0.5** | **Per-student daily cap** | `bot/middleware.py` | Designed in full in [Token budget](#token-budget--making-50-daily-students-fit), tasks T.1–T.5. Meters LLM calls rather than messages, so the free features stay unlimited |
| **0.6** | **Handle running out of quota gracefully** | `llm/router.py`, `bot/handlers/*` | When every rung is exhausted, `/test`, `/course` and `/quiz` break rather than degrade, because Ollama can't produce JSON. Detect it and say so — *"I'm out of capacity for today, try flashcards or a game"* — and steer to the zero-LLM features instead of erroring |

**Before the second week:**

| # | Task | Where | What to do |
|---|---|---|---|
| **0.7** | **Back up the database** | `deploy/` | `karly.db` will hold other people's work. A nightly copy off the OptiPlex, kept for a couple of weeks. Trivial to add, genuinely painful to skip |
| **0.8** | **Decide on consent** | — | If any student is a minor, storing their writing and reading a dashboard about them needs a decision made deliberately. One line in the welcome telling students what their teacher can see covers the ordinary case |

**Watch, don't build yet:**

| # | Item | Trigger to act |
|---|---|---|
| **0.9** | Reminder timezone — stored as `HH:MM` in *server* local time | Only matters if students aren't in your timezone |
| **0.10** | Sync SQLAlchemy in async handlers (Scale Step 1) | Symptom is *everything* slow at once, not one user failing. Fine at ~20 occasional users; revisit around 50 |

---

### Step 1 — Roster and roles

Every user gets a `role` and, if they're a student, a `class`.

| Item | What to do |
|---|---|
| `role` column on `users` | `teacher` / `student` / `guest`. You are the only teacher initially |
| `class` column (or a `classes` table if you teach more than one group) | Lets `/students` and the weekly digest be scoped to one group |
| `status` column | `pending` / `active` / `paused` / `removed`. Nothing is ever hard-deleted — a removed student's history stays for your records |
| `joined_at`, `approved_by` | Basic audit trail |

### Step 2 — Approval flow

What you asked for: a confirmation when someone wants to start using the bot.

1. A new person sends `/start`. They get a friendly "waiting for your teacher to let you
   in" message and can't use anything else.
2. **You get a DM:** `👤 Ana García (@ana_g) wants to join. [✅ Approve] [❌ Decline]`,
   with a **[Approve + assign to class]** option if you run more than one group.
3. You tap. The student is told immediately and lands in the onboarding sequence from
   Step 0.2 — **in the language you set for them when approving** (Step 0.1).
4. Declines are remembered, so a declined user re-sending `/start` doesn't spam you.

**Access modes** — one setting, three behaviours:

| Mode | Behaviour |
|---|---|
| `open` | Anyone can use it (today's behaviour) |
| `approval` | New users wait for your tap ← **the classroom default** |
| `code` | Students join with a class code you hand out in the lesson, and you confirm afterwards. Reuses the code mechanic already designed for The Impostor |

### Step 3 — What you can see

Three commands, teacher-only.

| Command | Shows |
|---|---|
| `/students` | The roster: name, level, last active, current streak, cards due, units passed. Sorted by "who needs attention" — least recently active first |
| `/student <name>` | One student in depth: CEFR per skill, units passed and failed, accuracy trend over recent weeks, weakest topics, error patterns, total messages and time on task |
| `/class` | Weekly digest for the whole group: who was active and who wasn't, average accuracy, units completed, and **the mistakes most students are making** — the most useful thing on this list for planning a lesson |

**Alerts, pushed to you rather than polled:**

| Trigger | Message |
|---|---|
| A student hasn't used the bot in N days (default 7) | `😴 Ana hasn't practised since Tuesday.` |
| A student fails the same unit 3 times | `⚠️ Marco has failed "Present perfect" 3 times — worth covering in class.` |
| A student finishes a level | `🎉 Sofía cleared A2.` |

Weekly digest arrives on a schedule you set, reusing the existing reminder job queue.

### Step 4 — What you deliberately don't see

Worth deciding now rather than after a student asks.

| Data | Default |
|---|---|
| Scores, streaks, units, error *patterns*, activity counts | **Visible to you.** This is ordinary gradebook information |
| Verbatim chat transcripts and their free writing | **Not visible by default.** Aggregates and error categories, yes; reading their conversations, no |
| Optional per-student opt-in to share writing samples | Worth adding if you want to mark their writing — but make it their choice, and tell them |

Students should be told, at `/start`, what their teacher can see. One short line in the
welcome message. This costs nothing and avoids the awkward conversation later.

### Step 5 — Usage tracking

**This is the "Usage metering" step from the Scale phase, pulled forward** — the same
table serves both purposes, so build it once here. It is also task **T.1** of
[Token budget](#token-budget--making-50-daily-students-fit) below, which is the
prerequisite for every gate in that section.

One row per LLM call: `user_id, model, tokens_in, tokens_out, task, ts`. The router
already returns `RouteResult` with token counts; the handlers just need to persist them.

| Gives you | How |
|---|---|
| Who's actually using the bot, and how much | Per-student call and message counts, by day and week |
| Which features get used | Grouped by task — conversation vs `/practice` vs `/course` |
| Cost per student | Tokens × rate, so a class stays inside the free tier knowingly rather than by luck |
| A per-student daily cap | One runaway user (or a stuck loop) can't burn the whole quota |

### Step 6 — Optional, once the course exists

Only worth building after the curriculum phase ([`CURRICULUM_PLAN.md`](CURRICULUM_PLAN.md)) lands.

| Item | What it does |
|---|---|
| Assignments | You assign a unit or level to the class; it becomes their next `/course` task, and `/class` shows who's done it |
| CSV export | Roster and scores out to a spreadsheet for your own gradebook |
| Multiple classes | Only if you teach more than one group — otherwise the `class` column is enough |

### Suggested order

0. Clear the day-one blockers (Step 0) — especially the German-mode default
1. Roster and roles (Step 1) — nothing works without it
2. Approval flow (Step 2) — the gate you asked for; makes it safe to hand out
3. Usage tracking (Step 5) — start collecting early, it's worthless retroactively
4. `/students` and `/student` (Step 3) — the day-to-day view
5. `/class` digest and alerts (Step 3) — the weekly rhythm
6. Assignments and export (Step 6) — after the course exists

Steps 0–3 are the minimum to put the bot in front of a class.

---

## Token budget — making 50 daily students fit

> **Goal:** 50 students, all able to use the bot every day, on or near the free tier.
> Interested, not obsessed. Nobody hits a wall that makes them stop coming back.

This is reachable, but only by metering the **right thing**.

---

### The budget, worked out

| | |
|---|---|
| Usable free capacity (mostly Gemini's ~1,500 req/day) | ~1,600 LLM calls/day |
| Run at 60% of the ceiling, not 100% | **~1,000 calls/day to spend** |
| Across 50 students | **~20 LLM calls per student per day** |

Twenty calls is a real day's use — roughly twenty back-and-forth messages, or a course
unit plus a chat plus the daily challenge. It's generous for "getting interested" and
tight enough that nobody can drain the class.

And in practice it's looser than it sounds: not every student shows up every day, so
unused allowance is headroom for the ones who do.

---

### Rule 1 — meter LLM calls, not messages

**Most of the bot already costs nothing.** Any gate that counts "messages" would punish
students for using the free features, which is exactly backwards.

| Always free, never limited | Metered |
|---|---|
| `/practice` flashcards (local scheduling) | Conversation messages |
| Banked `/course` and `/quiz` questions | Roleplay turns |
| The Impostor game | `/daily` |
| `/profile`, `/review`, `/students`, progress screens | `/test` placement |
| Course lesson cards (they're files) | "📖 Explain why" taps |
| Reading a transcript, retrying a wrong answer | Write-your-own-sentence grading, PDF analysis |

**Design rule: a student who runs out of budget can still learn.** Flashcards, their
course, and the game are all open. That is the whole reason the curriculum phase matters
for cost — banked exercises move the most valuable activity into the free column.

### Rule 2 — price actions by what they actually cost

One "credit" ≈ one LLM call. Students see a small number, not tokens.

| Action | Credits |
|---|---|
| Conversation message, roleplay turn, "explain why" tap | 1 |
| `/daily`, `/quiz` (before the bank exists) | 2 |
| PDF upload and analysis | 5 |
| `/test` placement | 10 — but once, and it should come out of a separate joining allowance so a new student isn't broke on day one |
| Everything in the free column above | 0 |

**Starting allowance: 20 credits/day per student**, resetting at midnight. Tunable per
class — it's one number, not a code change.

---

### Rule 3 — four gates, not one

Each catches something the others don't.

| # | Gate | Stops |
|---|---|---|
| **1** | **Per-student daily allowance** (20 credits) | One enthusiastic student eating the class's budget |
| **2** | **Global daily ceiling** across all students | 50 students each staying under their own cap but collectively exhausting the provider |
| **3** | **Per-student rate limit** (a few seconds between messages) | Spam, stuck loops, a phone sitting on a key |
| **4** | **Concurrency queue** | The lesson problem — 30 students at once against a 10–40 req/min ceiling. Queue with a "thinking…" indicator instead of failing |

**Plus a reserve.** Hold back ~25% of the global daily budget until mid-afternoon, so a
class at 3pm doesn't find that night owls spent everything at 1am. Simple rule, prevents
the most annoying possible failure.

### Rule 4 — running out is a redirect, never a wall

The moment a student is told "no", they stop coming back. So nobody is ever hard-stopped:

1. **Allowance spent →** *"That's today's chat with me. Your flashcards and course are
   still open, and the game's always free."* Offer the buttons, don't just say it.
2. **Still want to talk →** fall through to **Ollama, running locally**. Unlimited, free,
   lower quality, no structured tasks. The conversation continues; it just gets simpler.
   (Caveat: the OptiPlex handles a trickle, not a crowd — this is a graceful tail, not a
   second tier of capacity.)
3. **Global budget exhausted →** the whole class is told plainly, and pointed at the free
   activities. Never a silent failure or a raw error.

**Turn the limit into a motivator rather than a punishment:**

| Idea | Effect |
|---|---|
| Only show the counter when it's low ("5 left today") | Invisible until it matters; no anxiety |
| Streak bonus — a few extra credits for practising several days running | The limit becomes a reward to earn |
| Free-column activities top nothing up but cost nothing | Steers effort toward the things that actually teach |
| `/grant Ana 20` for the teacher | You can lift a cap for a student who's genuinely working |

---

### Rule 5 — make each call cheaper (as valuable as capping)

Halving what a call costs is the same as doubling the class size. Highest leverage first:

| # | Task | Saving |
|---|---|---|
| **B.1** | **Shorten conversation history.** `recent_history(limit=20)` sends 20 prior messages on every turn — most of the ~2,000 input tokens. Cut to 6–8 recent turns plus a rolling summary of older context | Potentially **~40–50% of all input tokens**, the single biggest win |
| **B.2** | **One daily challenge per level, shared by the class.** Generate `/daily` once per level per day and serve it to every student at that level. 50 calls become ~5 — and the whole class doing the same challenge is *better* teaching, not a compromise | ~90% of `/daily` cost |
| **B.3** | **Cap output length.** Set `max_tokens` per task so replies stay conversational instead of rambling | ~20–30% of output tokens |
| **B.4** | **Trim the system prompt.** Persona + correction block ride along on every single call | Small per call, large across 50 students |
| **B.5** | **Route cheap tasks to the cheap rung.** Lookups and short checks don't need the 120b model | Preserves 120b quota for conversation |
| **B.6** | **Cache identical requests.** Same "explain why" on the same correction, asked by twenty students, is one answer | Grows with class size |

**B.1 and B.2 together are probably worth more than the entire gating system.** Do them
first — they raise the ceiling for everyone instead of dividing a fixed pie.

---

### Rule 6 — you need to see it

| Command | Shows |
|---|---|
| `/budget` | Today's global usage, % of ceiling, projected exhaustion time, top consumers |
| Alert at 70% of the daily ceiling | Time to act before students notice anything |
| Per-student credits in `/student` | Who's actually engaged, and who needs a bigger allowance |

---

### Tasks, in order

| # | Task | Why this order |
|---|---|---|
| **T.1** | Usage tracking — one row per LLM call with tokens and task (Classroom Step 5) | You cannot budget what you don't measure. Everything below needs this table |
| **T.2** | B.1 — shorten conversation history | Biggest single saving, and it's independent of everything else |
| **T.3** | B.3 + B.4 — output cap and prompt trim | Quick, safe, compounding |
| **T.4** | Free vs metered classification | Decide once, in one place, which actions cost credits |
| **T.5** | Per-student daily allowance + the redirect message | The main gate. Useless before T.4 |
| **T.6** | Global ceiling + reserve pool | Protects the class from itself |
| **T.7** | Rate limit + concurrency queue | Fixes the whole-class-at-once lesson case |
| **T.8** | B.2 — shared daily challenge | Bigger win once there are actually 50 students |
| **T.9** | `/budget` and the 70% alert | Now you can tune the numbers with real data |
| **T.10** | Streak bonus, `/grant`, low-balance nudges | Polish — makes the limit feel like a game |

**T.1–T.5 are enough to safely invite 50 students.** The rest is tuning.

---

### Where this leaves the goal

| | 50 daily students |
|---|---|
| Today, no gates | ❌ Would exhaust the free tier and break `/test` and `/course` |
| With T.1–T.5 | ✅ Fits, at ~20 credits each |
| With T.1–T.8 | ✅ Comfortable, with room for heavier users |
| Plus Groq Developer tier (free) | ✅ Comfortable at **100+** |
| Plus ~$27/month | ✅ Stop thinking about it entirely |

**The honest summary: gating alone gets you to 50. Gating plus B.1 and B.2 gets you there
with room to spare. And if it ever becomes tight, the paid escape hatch is about the
price of a couple of coffees a month.**

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
