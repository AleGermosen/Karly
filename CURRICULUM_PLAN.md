# Karly — Curriculum phase

Plan for the next phase. Updated 2026-09-03. Planning only — no code written yet.

---

## TL;DR

**The idea:** give Karly a course. Today Karly is a good tutor with nothing to study —
every question it asks is invented on the spot and thrown away. [test-english.com](https://test-english.com)
is the opposite: a fixed list of topics per level, each with a short explanation and a
set of exercises. This phase gives Karly that list, without giving up anything it
already does.

**How:** write the syllabus once as files in the repo (topic names, order, explanations),
generate the exercises once in a batch and save them too, then the bot just reads them.
No inventing questions live, so units are fast, repeatable, and can be marked passed.

**Scope:** **English is the priority** — it's for your students, and it runs the whole
ladder, A1 to C1 (§3). German stays your personal track and gets levels when you want them.

**Where to start:** build the machinery once against **English A1**, then add one level at
a time. Each new level after the first is content only — no code.

**Pending work:** see [§4](#4-pending-tasks).

---

## 1. What Test-English has that Karly doesn't

This is the whole reason for the phase.

| | Test-English | Karly today | Karly after this phase |
|---|---|---|---|
| A numbered list of topics per level | ✅ ~24 grammar points per level, in study order | ❌ nothing | ✅ same idea, in `curriculum/en/a1.yaml` |
| Explanation before the exercises | ✅ short lesson + examples | ❌ drills only, never teaches a topic | ✅ lesson card, then exercises |
| Several exercises per topic | ✅ 3+ sets per point | ❌ random questions | ✅ 15 items per unit |
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
| **Exercise bank** | The actual questions and answers, ~15 per topic | Once per level, in a batch. Auto-checked, then you skim it | `curriculum/bank/en/a1.jsonl` — also a file in the repo |
| **The bot** | Reads those files, tracks who passed what | Every session | SQLite, 3 new tables |

**Why generate the exercises up front instead of live?**

- Questions get a permanent name (`de.a2.g07`), so Karly can track "you're at 70% on the
  perfect tense" — impossible if every question is a one-off invention.
- A unit costs almost nothing to run: multiple-choice and fill-in-the-blank are checked
  by simple string comparison, no LLM call. A 15-question unit makes **2 LLM calls** (the
  two write-your-own-sentence questions), versus 4–6 *every single time* if generated live.
- You can retake a unit and get different questions, because extra ones were generated.
- Bad questions get fixed once and stay fixed.

**Why files in the repo rather than the database?** Deploying is already `git pull` +
restart. Content ships the same way, you review it in a normal diff, and a bad question
gets reverted like any other commit. Whole level ≈ 180 KB.

**If a topic has no exercises yet**, the bot falls back to generating them live, like
today. Nothing is ever blocked waiting for content — that's what makes stage H3
shippable before H2 covers every unit.

---

## 3. The English ladder — A1 to C1

Five levels. Roughly 130 topics end to end, but **you never build more than one level at
a time**, and every level after the first is a content-only commit.

| Level | Topics | What it covers | Notes |
|---|---|---|---|
| **A1** | ~20 | to be, present simple, articles, plurals, can, past simple of common verbs | Where a true beginner starts |
| **A2** | ~24 | present perfect, past continuous, comparatives, going to, must/should | |
| **B1** | ~28 | all narrative tenses, conditionals 1–2, passive, reported speech, relative clauses | The biggest single jump — see below |
| **B2** | ~30 | perfect modals, mixed conditionals, advanced passive, participle clauses, inversion basics | |
| **C1** | ~30 | register, hedging, emphasis and cleft sentences, nominalisation, collocation, discourse markers | **Not a grammar list** — see below |

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

**Which level first?** A1, if your students are genuine beginners. If they're not, build
the level they're actually at — the placement test (`/test`) already sorts students by
level, so the bot routes them correctly as soon as their level exists.

**Effort per level:** roughly an afternoon of generation (unattended) plus an evening of
reading it over. $0 on the Groq free tier.

---

## 4. Pending tasks

**Build the machinery once (H0–H5), then add levels (H6+).** Each stage leaves the bot
working, so they can be spread out.

| # | Task | Type | Status | What it gives you |
|---|---|---|---|---|
| **H0** | One unit written by hand as the reference — German `de.a2.g07`, lesson + 15 questions | content | ✅ **done** | Proves the format works. Already caught 5 problems (§5) |
| **H0b** | `make curriculum-lint` — checks the content files for errors | code | ⏳ **next** | Stops broken content reaching the bot |
| **H1** | One **English** reference unit, with Spanish explanations | content | ⏳ | The German unit proved the format; this proves the English/Spanish wording before generating hundreds |
| **H2** | English A1 — ~20 topics + ~300 questions, generated and reviewed | content | ⏳ | The first real level |
| **H3** | `/course` — progress bar, lesson card, exercise runner, pass/fail, unlock next | code | ⏳ | **The feature.** A usable course |
| **H4** | Mastery per topic; missed questions become flashcards; chat corrections get a "practise this unit" button | code | ⏳ | The thing Test-English can't do |
| **H5** | `/leveltest` (clear a level) and `/browse` (jump to any unit) | code | ⏳ | Finishing a level means something |
| **H6** | English A2 | content | ⏳ | ↓ each of these is a content-only commit — |
| **H7** | English B1 | content | ⏳ | no code changes at all. If any are needed, |
| **H8** | English B2 | content | ⏳ | the design leaked and that's the bug to fix |
| **H9** | English C1 — needs its own unit shape first (§3) | content + design | ⏳ | Tops out the ladder |
| **H10** | German levels, on demand | content | ⏳ | Your own track, whenever you want it |

H3 is the biggest code stage. H6–H8 are repeatable content runs. **You can put the bot in
front of students after H5 with only A1 built** — students above A1 keep using
conversation, flashcards and quiz exactly as they do today, and their level lights up when
you build it.

**After H6 — the other Test-English sections**, in value order:

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

## 6. Decisions needed before H1

Recommendations given; these just need a yes.

| Question | Recommendation |
|---|---|
| Which level first? | English A1, unless your students are past it — then build the level they're at |
| Content in git or database? | Git — fits the existing deploy, reviewable in diffs |
| Pass mark for a unit? | 80%, retake any time |
| Locked units, or browse freely? | Soft: "Continue" follows the order, `/browse` opens anything at or below your level |
| Can a unit be passed before its questions are written? | Yes — don't punish the user for a content gap |
| Exam practice? | Defer. Revisit if students are sitting Cambridge or similar |
| B1+ bridge level? | Skip it; add only if students stall between B1 and B2 |

---

## 7. How this fits with the classroom plan

The two plans are separate documents but they are **not independent**, and the order
matters:

- **Classroom controls come first.** [`FUTURE_WORK.md`](FUTURE_WORK.md) →
  Classroom phase, Steps 0–3. Students can use conversation, flashcards, `/quiz` and
  `/daily` **today** — none of that waits on the course. What it does wait on is knowing
  who they are and letting them in. Build the gate before the classroom, not after.
- **The course makes the teacher view worth reading.** `/student` showing "units passed"
  and `/class` showing what the group is stuck on only mean something once units exist.
- **Assignments** (Classroom Step 6) are the join between the two: you assign a unit, it
  becomes the student's next `/course` task, and `/class` shows who's done it. That's
  the one item that genuinely needs both plans finished.

**Two smaller couplings worth remembering when you build:**

- **`l1_support` applies to lesson cards too.** The planned Spanish-support setting
  (FUTURE_WORK → "English mode should be in English") governs how much Spanish a student
  sees. Unit explanations and glosses have to respect it, or an A1 student gets an
  English-only grammar explanation they can't read.
- **Correction strictness stops at the exercise boundary.** The 0–5 strictness dial
  (FUTURE_WORK → "Correction strictness") governs *conversation* only. Inside a unit an
  answer is right or wrong and is marked as such at every level, including 0 — that's
  what the student asked for by starting an exercise. Keep the gentleness in the wording,
  not in the grading.

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

Only needed when you start H1. Both files already exist for the reference unit.

**`curriculum/de/a2.yaml`** — one entry per topic:

```yaml
- id: de.a2.g07                # permanent name; never renumbered
  level: A2
  order: 7
  title_target: "Perfekt vs. Präteritum"
  title_l1: "Perfect vs. simple past"
  can_do: "I can tell someone what I did at the weekend."
  skill: grammar               # one of the six BKT skills already in srs/bkt.py
  explain: [...]               # 4–8 bullets, max 140 chars each — it's a phone screen
  examples: [...]              # exactly 3, with translations
  pitfalls: [...]              # what an English speaker gets wrong. Most valuable field
  exercises: [{type: mcq, n: 5}, {type: cloze, n: 5},
              {type: transform, n: 3}, {type: produce, n: 2}]
```

**`curriculum/bank/de/a2.jsonl`** — one question per line, four types:

| Type | What it is | How it's marked |
|---|---|---|
| `mcq` | Multiple choice | Locally, no LLM |
| `cloze` | Fill in the blank | Locally, against a list of accepted answers |
| `transform` | Rewrite the sentence | Locally; if it doesn't match, **one** LLM call decides — and a correct answer that wasn't on the list gets added to it, so the bank improves as it's used |
| `produce` | Write your own sentence | LLM, against a short checklist |

**Three new database tables:** who's passed what (`unit_progress`), a copy of the
questions for speed (`exercise_items`), and every answer given (`item_attempts`). Nothing
existing changes.
