# Karly — Curriculum phase

*Last updated: 2026-09-09*

---

## TL;DR — Where we are and what's next

```
✅ A1 done  ✅ A2 done  ✅ B1 done  ✅ B2 done  ⬜ C1
```

**What's built and live:**
- `curriculum/en/a1.yaml` — 20 units, all hashes computed
- `curriculum/bank/en/a1.jsonl` — 280 questions (14 per unit)
- `curriculum/en/a2.yaml` — 24 units, all hashes computed
- `curriculum/bank/en/a2.jsonl` — 336 questions (14 per unit)
- `curriculum/en/b1.yaml` — 28 units, all hashes computed
- `curriculum/bank/en/b1.jsonl` — 392 questions (14 per unit)
- `curriculum/en/b2.yaml` — 30 units, all hashes computed
- `curriculum/bank/en/b2.jsonl` — 420 questions (14 per unit)
- `curriculum/loader.py` — loads all YAML/JSONL at import time
- `scripts/curriculum_lint.py` — validates and rehashes content (`make curriculum-lint / curriculum-rehash`)
- `bot/handlers/course.py` — `/course`, lesson cards, exercise runner, pass/fail, flashcard creation from missed items
- `bot/handlers/leveltest.py` — `/leveltest` (15-question level test, clears level and offers next) and `/browse` (unit picker)
- DB tables: `unit_progress`, `item_attempts`

**What's missing / next:**
- **H9 English C1** — needs its own unit shape first (not a grammar list — see §3)
- **H10 German levels** — personal track, whenever wanted
- **Reading track** — generated texts + comprehension questions
- **Writing track** — task + LLM grading against checklist
- **Listening track** — needs TTS; build with voice notes phase

**No code needed** for H7–H9. Each is a YAML file + JSONL bank, then `make curriculum-rehash`, smoke test, commit.

---

## 1. What Test-English has that Karly doesn't

This is the whole reason for the phase.

| | Test-English | Karly today | Karly after this phase |
|---|---|---|---|
| A numbered list of topics per level | ✅ ~24 grammar points per level, in study order | ❌ nothing | ✅ same idea, in `curriculum/en/a1.yaml` |
| Explanation before the exercises | ✅ short lesson + examples | ❌ drills only, never teaches a topic | ✅ lesson card, then exercises |
| Several exercises per topic | ✅ 3+ sets per point | ❌ random questions | ✅ 14 items per unit |
| Feedback on every question | ✅ | ✅ already does this well | ✅ unchanged |
| "Where am I / what's next" | ✅ unit list, progress per level | ❌ no notion of progress | ✅ `/course` with a progress bar |
| A test to clear a level | ✅ 15 questions per level | ❌ `/test` is a one-off placement | ✅ `/leveltest` |
| Reading / listening / writing sections | ✅ per level | ❌ none | ✅ later stages |
| Exam practice (Cambridge, Goethe) | ✅ | ❌ | ⏳ deferred, see §5 |
| **Conversation with a tutor** | ❌ none | ✅ Karly's core | ✅ **plus** it now points at units |
| **Spaced repetition** | ❌ none | ✅ HLR flashcards | ✅ **plus** missed items become flashcards |

The last two rows are the point. Copying the course structure doesn't make Karly a
Test-English clone — it makes Karly the thing Test-English can't be. Test-English has no
conversation, so it can never tell you *"you got the perfect tense wrong three times
while chatting this week — here's that unit."* Karly will.

---

## 2. How it works, in plain terms

Three pieces. The split between them is the only real design decision.

| Piece | What it is | Made when | Lives in |
|---|---|---|---|
| **Syllabus** | The topic list: name, level, order, explanation, examples, common mistakes | Once per level. LLM drafts it, you read it over | `curriculum/en/a1.yaml` — a normal file in the repo |
| **Exercise bank** | The actual questions and answers, 14 per topic | Once per level, in a batch. Auto-checked, then you skim it | `curriculum/bank/en/a1.jsonl` — also a file in the repo |
| **The bot** | Reads those files, tracks who passed what | Every session | SQLite, 3 new tables |

**Why generate the exercises up front instead of live?**

- Questions get a permanent name (`en.a1.g07`), so Karly can track "you're at 70% on the
  perfect tense" — impossible if every question is a one-off invention.
- A unit costs almost nothing to run: multiple-choice and fill-in-the-blank are checked
  by simple string comparison, no LLM call. A 14-question unit makes **2 LLM calls** (the
  two produce questions), versus 4–6 *every single time* if generated live.
- You can retake a unit and get different questions, because extra ones were generated.
- Bad questions get fixed once and stay fixed.

**Why files in the repo rather than the database?** Deploying is already `git pull` +
restart. Content ships the same way, you review it in a normal diff, and a bad question
gets reverted like any other commit. Whole level ≈ 200–400 KB.

**If a topic has no exercises yet**, the bot falls back to generating them live, like
today. Nothing is ever blocked waiting for content — that's what makes H3
shippable before H2 covers every unit.

---

## 3. The English ladder — A1 to C1

Five levels. Roughly 130 topics end to end, but **you never build more than one level at
a time**, and every level after the first is a content-only commit.

| Level | Topics | What it covers | Status |
|---|---|---|---|
| **A1** | 20 | to be, present simple, articles, plurals, can, past simple, basic questions | ✅ **Done — 280 questions** |
| **A2** | 24 | past continuous, present perfect, going to/will, comparatives/superlatives, must/should/have to, used to, passive, conditionals 1, reported speech | ✅ **Done — 336 questions** |
| **B1** | 28 | all narrative tenses, conditionals 1–2, passive (all tenses), reported speech (extended), relative clauses, gerunds vs infinitives, modals of deduction | ✅ **Done — 392 questions** |
| **B2** | 30 | mixed conditionals, inversion, advanced passive, subjunctive, cleft sentences, discourse markers, hedging, nominalisation, participle clauses, advanced register | ✅ **Done — 420 questions** |
| **C1** | ~30 | register, hedging, emphasis and cleft sentences, nominalisation, collocation, discourse markers | ⬜ needs own unit shape — see below |

**Two things worth knowing before you start:**

- **Test-English stops at B2.** There is no model to copy for C1, so that level's topic
  list has to come from CEFR C1 descriptors and Cambridge C1 Advanced scope instead.
- **C1 isn't more grammar.** By C1 the grammar is essentially done; what's left is
  *usage* — choosing the right register, hedging an opinion, fronting for emphasis,
  turning verbs into nouns, and collocation. If C1 is generated as "another grammar list"
  it will come out thin and repetitive. Its units need a different shape, and that's a
  real piece of design work when you get there, not a content run.
- **B1+ is optional.** Test-English splits B1 and B2 with a B1+ level because the gap is
  wide. Skip it initially; add it later if students stall between B1 and B2.

---

## 4. Pending tasks

**Build the machinery once (H0–H5), then add levels (H6+).** Each stage leaves the bot
working, so they can be spread out.

| # | Task | Type | Status | What it gives you |
|---|---|---|---|---|
| **H0** | One unit written by hand as the reference — German `de.a2.g07`, lesson + 15 questions | content | ✅ **done** | Proves the format works |
| **H0b** | `make curriculum-lint` — checks the content files for errors | code | ✅ **done** | Stops broken content reaching the bot |
| **H1** | One **English** reference unit, with Spanish explanations | content | ✅ **done** | Proves the English/Spanish wording |
| **H2** | English A1 — 20 topics + 280 questions | content | ✅ **done** | The first real level |
| **H3** | `/course` — progress bar, lesson card, exercise runner, pass/fail, unlock next | code | ✅ **done** | A usable course |
| **H4** | Mastery per topic; missed questions become flashcards | code | ✅ **done** | The thing Test-English can't do |
| **H5** | `/leveltest` (clear a level) and `/browse` (jump to any unit) | code | ✅ **done** | Finishing a level means something |
| **H6** | English A2 — 24 topics + 336 questions | content | ✅ **done** | Second level available to students |
| **H7** | English B1 — 28 topics + 392 questions | content | ✅ **done** | Serves intermediate students |
| **H8** | English B2 — 30 topics + 420 questions | content | ✅ **done** | Upper-intermediate level available |
| **H9** | English C1 — needs its own unit shape first (§3) | content + design | ⬜ **next** | Tops out the ladder |
| **H10** | German levels, on demand | content | ⬜ | Your own track, whenever you want it |

H7–H9 are repeatable content runs with zero code changes. **Students can use the bot now
with A1 and A2 built** — students above A2 keep using conversation, flashcards and quiz
exactly as they do today, and their level lights up when you build it.

**After H7 — the other Test-English sections**, in value order:

| Task | Notes |
|---|---|
| Reading track | Generated texts + comprehension questions. Easiest of the three |
| Writing track | A task + LLM grading against a checklist. Reuses the corrections format |
| Listening track | Needs text-to-speech. Build together with the planned voice notes — same plumbing. Transcript revealed after you answer, like Test-English |
| Exam practice | Goethe / Cambridge papers. Deepest content work, least differentiated. Only worth it if you're actually sitting an exam |

---

## 5. What the reference unit already taught us

H0 was one hand-written unit, and it caught five problems that would otherwise have
shipped. Two mattered:

- **Some wrong answers weren't wrong.** An early question offered `hatten` as a wrong
  option — but `wir hatten gelernt` is perfectly good German. Two correct answers on a
  four-option question.
- **`Sie` means three things.** *She*, *they*, and formal *you*, each taking a different
  verb form. A fill-in-the-blank starting with `Sie` has two right answers.

Both would have reached the user as *"the app marked my right answer wrong"* — the worst
thing a drill can do. Both are now automatic checks in the generation pipeline.

The other three were smaller: how learners type two-blank answers, alternative word
orders needing to be accepted up front, and pinning down how the change-detection hash
is computed.

**Takeaway:** the auto-checking step earns its keep, and shouldn't be trimmed later when
it starts to feel redundant.

---

## 6. Decisions already made

| Question | Decision |
|---|---|
| Which level first? | English A1 ✅, A2 ✅, B1 ✅, B2 ✅ — now C1 |
| Content in git or database? | Git — fits the existing deploy, reviewable in diffs ✅ |
| Pass mark for a unit? | 80%, retake any time ✅ |
| Locked units, or browse freely? | Soft: "Continue" follows the order, `/browse` opens anything at or below your level ✅ |
| Can a unit be passed before its questions are written? | Yes — don't punish the user for a content gap ✅ |
| Exam practice? | Deferred. Revisit if students sit Cambridge or similar |
| B1+ bridge level? | Skip it; add only if students stall between B1 and B2 |

---

## 7. How this fits with the classroom plan

The two plans are separate documents but they are **not independent**, and the order
matters:

- **Classroom controls came first.** Students can use conversation, flashcards, `/quiz` and
  `/daily` today — none of that waited on the course.
- **The course makes the teacher view worth reading.** `/student` showing "units passed"
  and `/class` showing what the group is stuck on only mean something once units exist.
- **Assignments** are the join between the two: you assign a unit, it becomes the student's
  next `/course` task, and `/class` shows who's done it. That's the one item that genuinely
  needs both plans finished.

**Two smaller couplings worth remembering when you build:**

- **`l1_support` applies to lesson cards too.** The Spanish-support setting governs how
  much Spanish a student sees. Unit explanations and glosses have to respect it, or an A1
  student gets an English-only grammar explanation they can't read.
- **Correction strictness stops at the exercise boundary.** The 0–5 strictness dial
  governs *conversation* only. Inside a unit an answer is right or wrong and is marked as
  such at every level, including 0 — that's what the student asked for by starting an
  exercise. Keep the gentleness in the wording, not in the grading.

---

## 8. Non-goals

- No website. Everything stays in Telegram.
- Not replacing conversation — the course is a second mode, and chat stays the main way
  material gets chosen.
- Not a content library. One current unit, one next unit.
- Nothing here depends on the public multi-user work (payments, entitlements) in
  [`FUTURE_WORK.md`](FUTURE_WORK.md), and nothing here blocks it.

---

## Appendix — file formats

**`curriculum/en/a2.yaml`** — one entry per topic:

```yaml
- id: en.a2.g01                # permanent name; never renumbered
  kind: grammar
  level: A2
  order: 1
  title_target: "Past continuous"
  title_l1: "Pasado continuo"
  can_do: "I can describe what was happening at a particular time in the past."
  prereqs: [en.a1.g06, en.a1.g16]
  skill: grammar                # one of the six BKT skills already in srs/bkt.py
  explain: [...]                # 4–8 bullets, max 140 chars each — it's a phone screen
  examples: [...]               # exactly 3, with gloss (Spanish translation)
  pitfalls: [...]               # what a Spanish speaker gets wrong. Most valuable field
  exercises: [{type: mcq, n: 5}, {type: cloze, n: 5},
              {type: transform, n: 2}, {type: produce, n: 2}]
  spine_hash: sha256:...        # computed by `make curriculum-rehash`
```

**`curriculum/bank/en/a2.jsonl`** — one question per line, four types:

| Type | Fields | How it's marked |
|---|---|---|
| `mcq` | `prompt`, `options[]`, `answer` (index), `why` | Locally, no LLM |
| `cloze` | `prompt`, `answer` (primary), `accept[]`, `why` | Locally, against accept list |
| `transform` | `prompt`, `answer` (primary), `accept[]`, `why` | Locally; unrecognised correct answers added to accept list |
| `produce` | `prompt`, `rubric[]`, `model_answer`, `why` | LLM, against rubric checklist |

All bank entries also carry: `lang`, `level`, `status` (`approved`), `spine_hash` (`sha256:pending` until rehashed).

**Three database tables:**
- `unit_progress` — who's passed what (user_id, unit_id, passed, best_score, attempts)
- `item_attempts` — every answer given (user_id, unit_id, item_id, correct, flashcard_created)
- No `exercise_items` table — questions live in the JSONL files, loaded at startup
