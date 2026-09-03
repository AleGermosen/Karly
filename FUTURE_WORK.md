# Karly — Roadmap & Future Work

Living plan for Karly's evolution. Updated 2026-09-03.

---

## TL;DR

**What's working today:** Dual-language tutor bot — German mode (native English speaker learning German, fully featured) and English mode (native Spanish speaker learning English, **now fully featured with all German-mode features**). Adaptive placement test, spaced-repetition flashcards (HLR scheduler, MCQ mode, deck picker, EN→ES/ES→EN flip), daily challenge, rapid quiz targeting weak skills, English roleplay scenes (6 scenarios), weekly progress report, PDF vocabulary extraction, social deduction game (The Impostor), open auth, BKT skill mastery, DKT LSTM (gated), systemd deploy on OptiPlex.

**What to build next (solo phase):**
1. **English-mode polish** — small remaining items listed below (help text updates, `/english` block, backend notice language)
2. Voice notes — speak German/English, get a text correction back
3. Assessment JSON hardening — retry/skip on bad output instead of raw dump
4. Manual grade override buttons on typed answers

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
