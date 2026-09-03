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

**Where to start:** German A2 only. One level, one language, all the way through. English
comes after, as a content-only addition.

**Pending work:** see [§3](#3-pending-tasks) — 6 stages, first two are content, not code.

---

## 1. What Test-English has that Karly doesn't

This is the whole reason for the phase.

| | Test-English | Karly today | Karly after this phase |
|---|---|---|---|
| A numbered list of topics per level | ✅ ~24 grammar points per level, in study order | ❌ nothing | ✅ same idea, in `curriculum/de/a2.yaml` |
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
| **Syllabus** | The topic list: name, level, order, explanation, examples, common mistakes | Once per level. LLM drafts it, you read it over | `curriculum/de/a2.yaml` — a normal file in the repo |
| **Exercise bank** | The actual questions and answers, ~15 per topic | Once per level, in a batch. Auto-checked, then you skim it | `curriculum/bank/de/a2.jsonl` — also a file in the repo |
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

## 3. Pending tasks

Six stages. Each one leaves the bot working, so they can be spread out.

| # | Task | Type | Status | What it gives you |
|---|---|---|---|---|
| **H0** | One unit written by hand as the reference — `de.a2.g07` "Perfekt vs. Präteritum", spine + 15 questions | content | ✅ **done** | Proves the format works. Already caught 5 problems (§4) |
| **H0b** | `make curriculum-lint` — checks syllabus and question files for errors | code | ⏳ **next** | Stops broken content reaching the bot |
| **H1** | Write the rest of German A2 — ~23 more topics. Script drafts them, you review | content | ⏳ | The actual syllabus |
| **H2** | Generate ~360 questions for those topics, auto-check them, skim and approve | content | ⏳ | The exercise bank |
| **H3** | `/course` — progress bar, lesson card, exercise runner, pass/fail, unlock next unit | code | ⏳ | **The feature.** A usable course |
| **H4** | Track mastery per topic; missed questions become flashcards; chat corrections get a "practise this unit" button | code | ⏳ | The thing Test-English can't do |
| **H5** | `/leveltest` (15 questions to clear a level) and `/browse` (jump to any unit) | code | ⏳ | Finishing a level means something |
| **H6** | Repeat H1+H2 for English B1 | content | ⏳ | Second language, **no code changes** — if any are needed, something's wrong |

Rough effort: H1 and H2 are an afternoon of generation plus an evening of reading, per
level, and cost $0 on the Groq free tier. H3 is the biggest code stage.

**After H6 — the other Test-English sections**, in value order:

| Task | Notes |
|---|---|
| Reading track | Generated texts + comprehension questions. Easiest of the three |
| Writing track | A task + LLM grading against a checklist. Reuses the corrections format |
| Listening track | Needs text-to-speech. Build together with the planned voice notes — same plumbing. Transcript revealed after you answer, like Test-English |
| Exam practice | Goethe / Cambridge papers. Deepest content work, least differentiated. Only worth it if you're actually sitting an exam |

---

## 4. What the reference unit already taught us

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

## 5. Decisions needed before H1

Recommendations given; these just need a yes.

| Question | Recommendation |
|---|---|
| Which level first? | German A2 alone, through H5 |
| Content in git or database? | Git — fits the existing deploy, reviewable in diffs |
| Pass mark for a unit? | 80%, retake any time |
| Locked units, or browse freely? | Soft: "Continue" follows the order, `/browse` opens anything at or below your level |
| Can a unit be passed before its questions are written? | Yes — don't punish the user for a content gap |
| Exam practice? | Defer. Revisit only if you're sitting a real exam |

---

## 6. Non-goals

- No website. Everything stays in Telegram.
- Not replacing conversation — the course is a second mode, and chat stays the main way
  material gets chosen.
- Not a content library. One current unit, one next unit.
- Nothing here depends on the multi-user work in [`FUTURE_WORK.md`](FUTURE_WORK.md), and
  nothing here blocks it.

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
