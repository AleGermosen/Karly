# Karly — Interactive Games Roadmap

*Last updated: 2026-09-04*

These are multiplayer and solo games planned for Karly, separate from the core tutoring features. All share the same basic hosting pattern: a host creates a room, shares a code, others join. The bot acts as referee, timer, and grammar coach.

---

## TL;DR — Games at a glance

| # | Game | Players | Solo vs bot? | Best level | Complexity to build |
|---|------|---------|-------------|-----------|---------------------|
| G-1 | Word Chain — Last One Standing | 2+ | No | A2+ | Low |
| G-2 | Story Relay | 2+ | No | A2+ | Low |
| G-3 | Telephone / Stille Post | 3+ | No | B1+ | Low |
| G-4 | Sentence Auction | 2+ | No | B1+ | Medium |
| G-5 | Taboo | 4+ (2 teams) | No | B1+ | Medium |
| G-6 | Alibi | 4–8 | No | B1+ | Medium |
| G-7 | Describe It | 1 | Yes | B1+ | Medium |
| G-8 | Murder Mystery | 4+ | No | B2+ | High |

---

## Game detail

---

### G-1 — Word Chain: Last One Standing

**Concept:** classic chain game where the last letter of each word must be the first letter of the next — played in the target language. Elimination-style with escalating topic constraints per round.

**Round structure:**
- Round 1: any valid word in the target language
- Round 2: only nouns
- Round 3: only words within a declared topic (e.g., "things in a kitchen", "weather", "travel")
- Topic for Round 3+ is announced at the start of that round; can be teacher-set or bot-generated

**Elimination:** each player has a configurable time limit per turn (default 30 seconds). Miss the timer or produce an invalid/repeated word → eliminated. Last player standing wins.

**Bot role:** referee only — validates that the word is real, checks it starts with the right letter, tracks used words, enforces the topic constraint via an LLM check, manages the timer.

**User's note:** add a topic option and time limit (these are the user's specific additions to the classic formula).

**Language practice value:** vocabulary breadth and recall under pressure.

---

### G-2 — Story Relay

**Concept:** each player adds one sentence to a growing shared story in the target language. The bot collects all sentences, corrects them silently, and at the end posts a full story recap with errors highlighted inline.

**Flow:**
1. Host starts: `/story new` — bot posts an opening sentence to kick things off.
2. Each player adds a sentence in turn (order is fixed at join time, loops around).
3. After N turns (configurable, default: 2 full loops) or when host calls `/story end`, bot posts:
   - The complete story as written
   - A corrected version with changes marked
   - Per-player error summary
4. Group votes on their favourite sentence (optional fun ending).

**Bot role:** turn management, silent correction accumulation, final report generation.

**Language practice value:** creative writing, coherence, past/present tense flow.

---

### G-3 — Telephone / Stille Post

**Concept:** a sentence passes player to player; each player paraphrases it (rewrites in their own words — no copying). At the end the bot posts the original and the final version side by side and shows how meaning drifted across the chain.

**Flow:**
1. Player 1 writes an opening sentence in the target language — only the bot and Player 1 see it.
2. Player 2 receives Player 1's sentence privately (via bot DM), rewrites it in their own words, and submits.
3. Each player only ever sees the previous player's version — not the original.
4. At the end, bot posts the full chain (all versions) in order and gives grammar feedback on each link.

**Bot role:** private message relay (bot DMs each player their "input"), chain tracking, final reveal, grammar feedback per link.

**Key constraint:** bot must DM each player privately so the chain stays secret — requires all players to have started a DM with the bot at least once (standard Telegram limitation).

**Language practice value:** paraphrasing, synonym use, sentence restructuring — good for B1+ students.

**Tone:** no winner, no loser — the fun is seeing how the sentence mutates. Works well as a class warm-up.

---

### G-4 — Sentence Auction

**Concept:** bot posts a fill-in-the-blank prompt. Players each submit their own completion in the target language. The group votes blind (names hidden during voting). Winner gets bragging rights or a small credit bonus.

**Flow:**
1. Bot posts a prompt, e.g.: *"Even though it was raining, she decided to ___."*
2. Players have 90 seconds to submit a completion via DM to the bot.
3. Bot collects all completions, shuffles them, posts them numbered — no names attached.
4. Players vote for their favourite (cannot vote for their own).
5. Bot reveals which player wrote which, announces winner, posts grammar notes on any errors.

**Prompt types:**
- Cloze completion (fill the blank mid-sentence)
- Sentence starter ("She opened the door and…")
- Reaction sentence ("Write one sentence about this image/emoji/scenario")

**Credit tie-in (optional):** winner earns 1 bonus credit toward their daily allowance. Keeps stakes low but meaningful.

**Bot role:** prompt generation, submission collection via DM, blind reveal, vote tallying, grammar feedback.

**Language practice value:** collocations, idioms, creative fluency — prompts can be tuned to drill specific grammar targets.

---

### G-5 — Taboo

**Concept:** bot assigns a secret word and 3 forbidden helper words. The describer has 60 seconds to get their team to guess the word — using only the target language. Bot acts as buzzer.

**Flow:**
1. Host starts: `/taboo new` — bot DMs the describer their word + forbidden words.
2. Describer talks (types) in the group chat. Teammates guess in the group chat.
3. Bot monitors for forbidden words and language violations:
   - Forbidden word used → team loses a point, next word
   - Wrong language used → warning, second offence → loses a point
4. After 60 seconds or a correct guess, bot reveals the word and moves to the next describer.

**Teams:** 2 teams, alternating turns. Bot tracks score.

**Bot role:** secret word assignment (via DM), real-time forbidden-word monitoring in group chat, timer, score tracking.

**Implementation note:** forbidden-word detection needs to handle inflected forms (e.g., if the forbidden word is "Haus", "Hauses" and "Häuser" should also trigger). A lemmatisation check or LLM call per message handles this — keep it lightweight (flag only if ≥80% confident).

**Language practice value:** vocabulary description, circumlocution — exactly the skill needed when you forget a word mid-conversation.

---

### G-6 — Alibi

**Concept:** one player is accused of something harmless (e.g., "you ate the last piece of cake at 8pm last night"). They have 90 seconds to whisper an alibi to one partner. The rest of the group then interrogates each suspect separately in the target language, looking for contradictions.

**Flow:**
1. Bot announces the "crime" and secretly DMs the two suspects: *"You were at the cinema watching a comedy. It started at 7:30. You had popcorn."* (bot generates the alibi — suspects must stick to it without having agreed in advance).
2. Each suspect is interrogated one at a time in the group chat. The other suspect is muted (can't see the interrogation — bot enforces via DM-only replies during this phase).
3. After both are interrogated, the group votes: innocent or guilty?
4. Bot reveals the "true" alibi details and highlights any contradictions found.

**Bot role:** crime generation, alibi generation (same alibi sent to both suspects), mute enforcement (interrogation happens via bot DM, not group chat), contradiction detection in the reveal.

**Language practice value:** past tense, temporal expressions, question formation — rich grammar targets baked into the game mechanics.

**Player count:** 4–8. Works best with 5–6 (2 suspects, 3–4 interrogators).

---

### G-7 — Describe It *(solo vs. the bot)*

**Concept:** the player thinks of a word and describes it to the bot using only sentences in the target language. The bot guesses after each clue. Player wins if the bot needs 4 or more guesses; bot wins in 3 or fewer.

**Rules:**
- No cognates (e.g., can't say "Telefon" when the word is "telephone")
- No spelling out the word, no translations, no pointing to the language ("it's a German word for…")
- Each clue must be a complete sentence in the target language

**Why it's fair:** the bot isn't pretending to be slow. It guesses from your clues exactly as a human would — precise, creative clues make it harder for the bot; vague or grammatically broken clues narrow the field quickly and make it easier. The player is rewarded for both fluency and lateral thinking.

**Scoring:**
- Bot guesses in 1–2: bot wins easily
- Bot guesses in 3: bot wins
- Bot guesses in 4–5: player wins
- Bot guesses in 6+: player wins with a bonus ("stumped the bot!")
- Bot can't guess after 8 clues: bot concedes, asks for the word, checks if the clues were fair

**Reverse mode (easier, optional):** bot describes a word, player guesses. Lower language production demand — good for A2 students who aren't ready for free description yet.

**Language practice value:** circumlocution, descriptive vocabulary, full-sentence production under a real communicative constraint. The best solo drill for genuine fluency.

---

### G-8 — Murder Mystery *(longer format)*

**Concept:** bot generates a scenario — a "crime," a cast of characters, and a set of facts each character knows. One player is the murderer (lied to), one is the detective, the rest are witnesses. The detective interrogates everyone in the target language; after N questions, they accuse someone.

**Flow:**
1. Host starts: `/mystery new` — bot generates the scenario (location, victim name, time, murder weapon) and assigns roles via DM.
   - Witnesses receive true facts about what they "saw."
   - Murderer receives a false alibi plus a few true facts to sound credible.
   - Detective receives only the crime summary — no witness facts.
2. Detective interrogates players one at a time in the group chat (or bot relays DM-style for privacy).
3. After the detective has questioned everyone, they submit an accusation: `/mystery accuse NAME`.
4. Bot reveals the full scenario, who knew what, and where the murderer's story didn't add up.
5. Optional: bot gives language feedback to the detective on their question formation and to all players on their answers.

**Scenario generation:** bot generates the scenario fresh each game from a template (location + motive + weapon + timeline). No pre-written scripts needed — the LLM handles it, making each game unique.

**Bot role:** scenario + role generation, DM relay for private interrogations, accusation resolution, reveal + feedback.

**Language practice value:** question formation, past tense narrative, listening/reading comprehension — the richest language workout of any game here. Best suited for B2+ students or a structured class session.

**Session length:** 20–40 minutes for a full round. Recommend teacher-hosted during class time rather than async play.

---

## Shared infrastructure notes

All games above rely on a common set of primitives that can be built once and reused:

| Primitive | Used by |
|-----------|---------|
| Room code + join flow | All |
| Turn order management | G-1, G-2, G-3, G-4, G-5, G-6 |
| Bot DM relay (private channel per player) | G-3, G-5, G-6, G-8 |
| Timer with auto-advance | G-1, G-4, G-5 |
| Blind reveal (hide names until voting closes) | G-4 |
| Grammar feedback batch (collect during game, deliver after) | G-2, G-3, G-6, G-7, G-8 |

**Recommended build order:** G-1 → G-2 → G-7 → G-3 → G-4 → G-5 → G-6 → G-8

- G-1 and G-2 share the room/turn infrastructure and have no DM relay requirement — build these first.
- G-7 is fully solo — no multiplayer infrastructure needed, can be built in parallel.
- G-3 introduces DM relay; G-5 and G-6 build on that pattern.
- G-8 is last: it needs everything plus scenario generation.
