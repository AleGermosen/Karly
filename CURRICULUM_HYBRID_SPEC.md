# Curriculum — hybrid content model, build spec

Planning document. Written 2026-09-03. **No code — this is the "how" for the
hybrid option chosen in [`CURRICULUM_PHASE_PLAN.md`](CURRICULUM_PHASE_PLAN.md) §4.1.**

The phase plan says *what* to build and *why*. This document specifies the content
machinery: what is authored, what is generated, what is cached, who validates it,
what it costs, and what happens when a piece is missing.

---

## 0. The rule the whole design follows

> **Authored spine · generated flesh · cached forever · live only where it must be.**

Three layers, and the boundary between them never moves:

| Layer | What it holds | Who makes it | Where it lives | When | Runtime LLM cost |
|---|---|---|---|---|---|
| **1. Spine** | Unit identity, order, prerequisites, explanation, examples, pitfalls | LLM-drafted, **human-reviewed**, committed | `curriculum/<lang>/<level>.yaml` (git) | Once per level | **0** |
| **2. Bank** | Exercise items + answer keys + accept-lists | LLM-generated in batch, gate-checked, human-approved, committed | `curriculum/bank/<lang>/<level>.jsonl` (git) → loaded to DB on boot | Once per level, regenerated on spine change | **0** |
| **3. Runtime** | Per-user progress, attempts, mastery | The bot, per user | SQLite (`unit_progress`, `item_attempts`) | Continuously | **0**, except the two cases in §4.3 |

Everything else in this document is a consequence of that table.

**Why the spine must be authored and stable:** a unit ID is the key that BKT and HLR
hang mastery on. `de.a2.g07` means "perfect vs. simple past" today, next month, and
after a regeneration. An LLM improvising a question about the perfect tense has no
key, so its outcome can't be accumulated into anything. Stable IDs are the entire
reason for the hybrid.

**Why the bank must be generated:** hand-writing 360 exercise items per level per
language is weeks of work that an LLM does in an afternoon at a quality that survives
review. Generation is not a compromise here — it's the right tool, moved off the
runtime path where its nondeterminism would be a defect.

---

## 1. Layer 1 — the spine

### 1.1 Layout

```
curriculum/
  de/  a1.yaml  a2.yaml  b1.yaml  b2.yaml
  en/  a1.yaml  a2.yaml  b1.yaml  b2.yaml
  bank/
    de/  a2.jsonl  …
    en/  b1.jsonl  …
```

### 1.2 Unit schema

```yaml
- id: de.a2.g07                  # REQUIRED. Immutable forever. See §1.3
  kind: grammar                  # grammar | vocab | reading | listening | writing
  level: A2                      # A1 | A2 | B1 | B1+ | B2
  order: 7                       # position within the level
  title_target: "Perfekt vs. Präteritum"
  title_l1: "Perfect vs. simple past"     # English in DE mode, Spanish in EN mode
  can_do: "I can tell someone what I did at the weekend."
  prereqs: [de.a2.g03]           # unit IDs; may be empty
  skill: grammar                 # one of srs/bkt.py SKILLS — keeps existing BKT working
  explain:                       # 4–8 bullets. Shown as the lesson card. ≤ 140 chars each
    - "Spoken German uses the Perfekt for almost all past events."
  examples:                      # exactly 3
    - {target: "Ich habe gestern gearbeitet.", gloss: "I worked yesterday."}
  pitfalls:                      # 1–3. L1-interference notes — the highest-value field
    - "English 'I worked' maps to Perfekt in speech, not Präteritum."
  exercises:                     # the bank's build order for this unit
    - {type: mcq,       n: 5}
    - {type: cloze,     n: 5}
    - {type: transform, n: 3}
    - {type: produce,   n: 2}
  spine_hash: "sha256:…"         # written by the build tool; see §1.4
```

### 1.3 ID rules

- Format `<lang>.<level>.<kind-letter><NN>` — `de.a2.g07`, `en.b1.v03`, `de.a2.r02`.
- **Immutable.** A unit's ID never changes, is never reused, and is never renumbered.
  `order` moves freely; the ID does not.
- Retiring a unit means setting `retired: true`, not deleting the entry — existing
  `unit_progress` rows would otherwise dangle.
- `order` gaps are legal and expected. Insert `order: 7.5` rather than renumbering.

### 1.4 Change control — `spine_hash`

`spine_hash` is a hash over the fields the bank depends on: `title_target`, `level`,
`skill`, and `exercises`. It deliberately **excludes** `explain`, `examples`,
`pitfalls`, `order`, and `can_do`.

| You change… | Bank impact |
|---|---|
| Explanation wording, examples, pitfalls, order, can-do | **None.** Fix typos freely; items stay valid. |
| `exercises` spec, `title_target` (i.e. the grammar scope), `level`, `skill` | `spine_hash` changes → the unit's bank items are marked `stale`, regenerated, and re-approved. Old items keep serving until the new ones are approved. |
| Anything at all | `unit_progress` is untouched — it keys on `unit_id` only. |

### 1.5 Validation — `make curriculum-lint`

Fails the build on:
- duplicate or malformed IDs; `order` collisions within a level
- `prereqs` pointing at a missing, retired, or higher-level unit
- prerequisite cycles
- `skill` not in `srs/bkt.py` `SKILLS`
- `explain` outside 4–8 bullets, or a bullet over 140 chars (it won't read on a phone)
- `examples` ≠ 3, missing `gloss`
- `exercises` totalling < 10 or > 20 items
- a `spine_hash` that doesn't match its content (i.e. someone edited by hand without rebuilding)

Lint runs in `make test`. A red lint is a broken build, not a warning.

---

## 2. Layer 2 — the item bank

### 2.1 Item types and payloads

One JSONL line per item. `id` is derived and stable: `<unit_id>.<type>.<NN>`.

```jsonc
// mcq — graded locally by index comparison
{"id":"de.a2.g07.mcq.03","unit":"de.a2.g07","type":"mcq","level":"A2","status":"approved",
 "prompt":"Gestern ___ ich ins Kino gegangen.",
 "options":["bin","habe","war","werde"], "answer":0,
 "why":"gehen is a verb of motion — it takes sein in the Perfekt.",
 "spine_hash":"sha256:…"}

// cloze — graded locally against an accept-list
{"id":"de.a2.g07.cloze.01","unit":"de.a2.g07","type":"cloze","level":"A2","status":"approved",
 "prompt":"Ich ___ (arbeiten) gestern den ganzen Tag.",
 "accept":["habe … gearbeitet","habe gearbeitet"], "answer":"habe gearbeitet",
 "why":"…", "spine_hash":"sha256:…"}

// transform — graded locally against an accept-list, LLM escape hatch on miss (§4.3)
{"id":"de.a2.g07.transform.02","unit":"de.a2.g07","type":"transform","level":"A2","status":"approved",
 "prompt":"Put into the Perfekt: „Ich arbeitete den ganzen Tag.\"",
 "accept":["ich habe den ganzen tag gearbeitet"], "answer":"Ich habe den ganzen Tag gearbeitet.",
 "why":"…", "spine_hash":"sha256:…"}

// produce — LLM-graded against a rubric (the only runtime call in a unit)
{"id":"de.a2.g07.produce.01","unit":"de.a2.g07","type":"produce","level":"A2","status":"approved",
 "prompt":"Write one sentence about what you did last weekend, in the Perfekt.",
 "rubric":["uses Perfekt","correct auxiliary","participle formed correctly"],
 "model_answer":"Ich bin am Samstag ins Kino gegangen.",
 "spine_hash":"sha256:…"}
```

`status` ∈ `draft` · `approved` · `rejected` · `stale` · `flagged`.
**Only `approved` items are ever served.**

### 2.2 Generation pipeline — `make curriculum-build LANG=de LEVEL=a2`

Seven gates, run offline on the dev machine, never on the bot's request path. Uses the existing
`llm/structured.py` `generate_json` with `Task.generate` — the ladder's Gemini rung is
perfectly fine here because nobody is waiting.

1. **Draft.** For each unit, one call per item type, asking for **1.6× the target
   count** (so 8 MCQs are drafted where 5 are needed). Overgeneration is what makes a
   retake different from the first attempt — see §4.2.
2. **Schema gate.** Reject anything that doesn't parse or fails the payload shape.
3. **Answer-key gate.** Re-ask a *fresh* call to solve each drafted item cold, with no
   answer key. Disagreement between the generator's key and the solver's answer ⇒
   `rejected` and logged. This catches most ambiguous-distractor bugs, which are the
   dominant failure mode.
4. **Distractor gate** (mcq only). Reject if any two options are equivalent, if the
   correct option is the longest by more than 40%, or if options differ only in
   punctuation. **Auxiliary rule** (from H0, §10): in a past-tense gap, `hatte`/`war`
   distractors form a valid Plusquamperfekt and must never be offered against a
   Perfekt answer — the item would have two correct answers.
5. **Dedupe.** Reject items whose normalized prompt matches an existing item in the
   same unit.
6. **Level gate.** Reject items whose vocabulary sits above the unit's CEFR level
   (checked against the level's own vocabulary units plus a frequency list).
7. **Ambiguous-subject gate** (from H0, §10). Reject German items whose subject is a
   bare `Sie`/`sie` where the required verb form depends on reading it as *she* vs.
   *they* vs. formal *you*. Same for Spanish `usted`/`él` collisions in English mode.
7. **Stage.** Survivors are written as `status: draft` to the level's JSONL.

Every rejection is written to `curriculum/bank/<lang>/<level>.rejects.jsonl` with its
reason. That file is the quality signal for the generation prompts — if gate 3 rejects
40% of MCQs, the prompt needs work, not the pipeline.

### 2.3 Human review — the PR diff *is* the review queue

The bank is committed to git, so review happens where review already happens.
`make curriculum-review` flips `draft` → `approved` in bulk after you've read the diff.

**Tiered review, because 576 items per level is too many to eyeball honestly:**

| Type | Review depth | Rationale |
|---|---|---|
| `produce` | **100%** | No mechanical key; a bad prompt wastes an LLM call and confuses the user |
| `transform` | **100%** | Accept-lists are the top source of false negatives |
| `cloze` | **~25% spot check** | Short answers; gate 3 catches most errors |
| `mcq` | **~25% spot check** | Gates 3 and 4 are strong here |

Anything a gate rejected is *not* reviewed — it's already out. Review effort per level
is roughly 120 items read carefully plus 250 skimmed: an evening, not a week.

### 2.4 Why the bank lives in git rather than only in the DB

Deploy is already `git pull` + restart (`deploy/deploy.sh`). A git-resident bank means:

- review happens in a PR diff, with history and blame per item
- shipping content is a deploy, with no migration or seeding step
- the bank is reproducible and rebuildable from source
- a bad item is reverted like any other commit

Size is a non-issue: ~600 items × ~300 bytes ≈ **180 KB per level**, so all four levels
in both languages come to ~1.4 MB.

The DB copy (`exercise_items`) is a **load target, not the source of truth** — an
idempotent upsert keyed by item ID, run at boot. It exists so attempts can reference
items and so selection queries are fast. Dropping and rebuilding it must always be safe.

---

## 3. Layer 3 — data model

Three new tables in `db/models.py`, one new enum value. **Nothing existing changes shape.**

```
unit_progress
  user_id ─fk→ users.id     unit_id (str)     state           # locked|available|in_progress|passed
  attempts (int)            best_score (float)                 p_mastery (float)
  first_seen_at             passed_at (nullable)
  UNIQUE(user_id, unit_id)

exercise_items                                   # load target; rebuildable from git
  id (str, pk)              unit_id (str)       lang  level  type  status
  payload_json              spine_hash          loaded_at

item_attempts
  user_id ─fk→ users.id     item_id (str)       correct (bool)
  answer_text               graded_by           # local|llm
  created_at
```

Plus `VocabSource.curriculum`, so vocabulary units and missed-item flashcards seed
`VocabItem` rows that flow into the existing HLR scheduler untouched.

`p_mastery` uses `srs/bkt.py`'s `update()` unchanged — same maths as the six coarse
skills, just keyed per unit. The coarse `ConceptMastery` state keeps updating in
parallel via the existing `update_bkt_state(user_id, skill, correct, level)`, so
`/profile` and `/quiz` keep working with no changes at all.

---

## 4. Layer 3 — runtime behaviour

### 4.1 The read path, step by step

What happens when the user taps **▶️ Continue**:

| Step | Reads | LLM calls |
|---|---|---|
| Resolve current unit | `unit_progress` + spine files (in memory) | 0 |
| Render lesson card | spine `explain` / `examples` / `pitfalls` | 0 |
| Select items | `exercise_items` + `item_attempts` (§4.2) | 0 |
| Serve + grade mcq / cloze / transform | local comparison (§4.3) | 0 |
| Serve + grade `produce` | rubric call, `Task.check` | **1 per produce item** |
| "📖 Explain" tap | existing `CORRECTION_EXPLAIN` prompt | **1 per tap** |
| Result card, mastery, unlock | local | 0 |

**A full 15-item unit costs 2 LLM calls** — the two `produce` items — versus one call
today for a `/quiz` that produces nothing reusable. The lesson and all 13 closed items
are free and instant. That is the whole point of the hybrid, and it's the number to
verify at H3.

### 4.2 Item selection

Items carry an implicit slot order from the spine's `exercises` list: MCQ set → cloze
set → transform → produce. Within a set:

- **First attempt:** the lowest-numbered approved items, in order. Deterministic, so a
  unit is reproducible when debugging.
- **Retake:** unseen items first (this is what the 1.6× overgeneration buys — a retake
  is a genuinely different test), then least-recently-attempted.
- Never the same item twice within one run.
- If a set has fewer approved items than the spine asks for, serve what exists and log
  a bank shortfall. Do not block the unit.

### 4.3 Grading rules

| Type | Rule | Calls |
|---|---|---|
| `mcq` | Index comparison. | 0 |
| `cloze` | Normalize (lowercase, collapse whitespace, strip terminal punctuation, fold umlauts/accents, **collapse `/` and `,` separators to a single space**) and match against `accept`. | 0 |
| `transform` | Same normalization and match. **On a miss, one `Task.check` call** decides whether the answer is a legitimate alternative. | 0 or 1 |
| `produce` | `Task.check` against the item's `rubric`; returns `{correct, feedback, corrected}`. | 1 |

**The escape hatch matters more than it looks.** Marking a correct answer wrong is the
worst thing a drill can do to a learner's trust, and hand-written accept-lists always
miss valid variants. So: when an answer misses the accept-list but the LLM judges it
correct, the user is told they're right **and the answer is logged to
`curriculum/bank/<lang>/<level>.accepts.jsonl`**. `make curriculum-review` folds those
into the item's `accept` list on the next pass.

**The bank therefore improves with use.** Every false negative is caught once, costs
one call, and is free forever after. This closes the main quality gap between generated
and hand-authored content.

Users also get a **⚠️ Report** button on every item's feedback. It sets the item's
status to `flagged`, takes it out of rotation immediately, and surfaces it in the next
review pass. One tap, no dialogue.

### 4.4 Unit completion

- Score = correct ÷ served. **Pass ≥ 80%.**
- On pass: `state = passed`, `passed_at` set, units whose prereqs are now satisfied
  become `available`.
- On fail: `state` stays `in_progress`, `attempts` increments, the unit can be retaken
  immediately with different items (§4.2).
- **Either way:** every missed item's target form becomes a flashcard via the existing
  `add_vocab_items` path with `source=curriculum`. A failed unit is never a dead end —
  it feeds the SRS loop that already works.
- Both mastery models update per item: `unit_progress.p_mastery` (fine, for targeting)
  and the coarse skill via `update_bkt_state` (for `/profile`).

### 4.5 The cold path — graceful degradation to live generation

A unit with fewer than 5 approved items is **cold**. Cold units still work: the runtime
falls back to live generation using the existing `QUIZ_ITEMS` / `ENGLISH_QUIZ_ITEMS`
prompt seeded with the unit's `title_target` and `explain` bullets. Those items are
ephemeral — served, graded, and discarded, never written to the bank without review.

Consequences, stated deliberately:
- **The bot is never blocked on content.** A syllabus can ship before its bank does,
  which is exactly what makes stage H3 shippable before H2 is finished for every unit.
- A cold unit **can** be passed. The alternative — locking units until content exists —
  punishes the user for a build-pipeline gap they can't see.
- Cold runs are logged per unit, so the shortfall report ranks which units to build next
  by actual demand rather than by syllabus order.

The hybrid degrades to pure live generation and never breaks. That's the safety
property that makes it worth choosing.

---

## 5. Build commands

All added to the existing `Makefile`, all local-only:

| Target | Does |
|---|---|
| `make curriculum-lint` | Validates every spine file and bank file (§1.5). Wired into `make test`. |
| `make curriculum-spine LANG=de LEVEL=a2` | Drafts unit stubs from a CEFR contents list into `curriculum/de/a2.yaml`. Human edits after. |
| `make curriculum-build LANG=de LEVEL=a2` | Runs the item pipeline (§2.2) → `draft` items + a rejects file. |
| `make curriculum-review LANG=de LEVEL=a2` | Flips `draft` → `approved`, folds in logged accept-list additions, drops `flagged` items into a review list. |
| `make curriculum-status` | Per unit: approved item count by type, cold/warm, flagged count, cold-run demand ranking. |

Scripts live in `tools/curriculum/`. **They are dev tooling, not part of the bot** —
`bot/main.py` never imports them, and the bot only ever reads the committed files.

---

## 6. Cost and effort, concretely

**Build cost, per level per language:**

| Item | Number |
|---|---|
| Grammar units | ~24 |
| Items drafted per unit (1.6× of 15) | 24 |
| Items drafted per level | ~576 |
| Generation calls (batched ~8 items/call, plus answer-key solve pass) | ~150 |
| Spine drafting calls | ~24 |
| **Total calls to build a level** | **~175** |
| Wall-clock | one afternoon, mostly unattended |
| Money on Groq free tier | **$0** |
| Human review | ~120 items read closely + ~250 skimmed ≈ one evening |

**Runtime cost, per user:**

| Activity | Calls |
|---|---|
| Lesson card | 0 |
| 13 closed items | 0 |
| 2 produce items | 2 |
| Occasional "📖 Explain" / transform escape hatch | ~1–2 |
| **A complete unit** | **~3–4** |

Compare with a pure live-generation design, where the same unit costs 4–6 calls
*every time it is opened*, produces different questions each run, and can't be
retaken, cached, or measured.

---

## 7. Stages

Restructured around the three layers. Each stage ships independently and leaves the
bot working. These replace §5 of the phase plan for the content-model work; the
skill-track stages (reading / writing / listening / exams) follow unchanged after H6.

### H0 — Schema and golden unit ✅ content done, tooling pending
Write the spine and bank JSON schemas and `make curriculum-lint`. **Hand-write one
complete unit** (`de.a2.g07`, spine + 15 items) as the golden reference every generator
prompt is measured against. No bot changes.
**Exit:** lint passes on the golden unit; the golden unit reads like something you'd study.

**Status:** the golden unit is written and verified against every rule in §1.5 and
§2.2 — see §8 for the five spec defects it caught. What remains is turning that
verification into the committed `make curriculum-lint` target.

### H1 — Spine generator
`make curriculum-spine`, run for German A2. Human pass over all ~24 units: ordering,
prerequisites, and especially `pitfalls` (the field an LLM writes most generically and
a human improves most).
**Exit:** `curriculum/de/a2.yaml` lints clean, 24 units, prereq graph acyclic and sane.

### H2 — Bank generator and gates
`make curriculum-build` with all six gates, the rejects file, and `make
curriculum-review`. Run for German A2.
**Exit:** ≥ 15 approved items per unit across all 24 units; gate-3 rejection rate
below 25% (above that, fix the prompts before moving on).

### H3 — Loader and runtime read path
The three tables, idempotent boot-time load from git, `/course` hub, lesson card,
exercise runner with local grading, result card, unlock logic, cold-path fallback.
**Exit:** German A2 units 1→24 walk end to end; **a warm 15-item unit measurably makes
exactly 2 LLM calls**; a cold unit still runs via fallback.

### H4 — Mastery and the feedback loop
Per-unit BKT; missed items → flashcards; accept-list expansion from the escape hatch;
⚠️ Report button; `/quiz` retargeted to weakest *units*; conversation corrections tagged
with a `unit_id` and given a **🎯 Practise this unit** button.
**Exit:** a mistake made in chat leads, in one tap, to the unit that fixes it.

### H5 — Checkpoints and browsing
`/leveltest` — 15 items drawn from the approved bank, no new generation — plus level
promotion, weak-unit study plan on failure, `/browse`, and course progress in
`/profile` and `/weekly`. `/test`'s verdict wired to set the starting level.
**Exit:** a level can be completed and cleared; any unlocked unit is reachable in two taps.

### H6 — Second language, zero new code
Run H1 and H2 for English B1. **No handler changes should be needed.** If any are, the
layer boundary leaked and that's the bug to fix before adding tracks.
**Exit:** English B1 ships as a content-only commit.

---

## 8. What H0 already found

The golden unit (`curriculum/de/a2.yaml` + `curriculum/bank/de/a2.jsonl`,
`de.a2.g07` "Perfekt vs. Präteritum", 15 items) is written and passes every gate
above. Writing it by hand surfaced five defects in this spec — the whole reason the
stage exists, and all five are folded in above:

1. **Plusquamperfekt distractors are valid German.** The first draft of an MCQ offered
   `hatten` against `haben ... gelernt`, and another offered `war` against
   `ist aufgestanden`. Both are correct German (`wir hatten gelernt`,
   `er war aufgestanden`) — two right answers on a four-option item. This is the exact
   failure gate 3's cold solver exists to catch, and it appeared on the *first* unit,
   which suggests it will be common. Gate 4 now rules it out structurally.
2. **`Sie` is three words at once.** A cloze reading `Sie ___ das Buch schon ___`
   accepts both `hat gelesen` and `haben gelesen` depending on whether the subject is
   *she*, *they*, or formal *you*. Now a gate; the item was rewritten to `Er`.
3. **Two-gap cloze needs separator variants.** A learner types `habe gearbeitet`,
   `habe / gearbeitet`, or `habe, gearbeitet` interchangeably. Normalization now
   collapses separators, so accept-lists don't have to enumerate them.
4. **Word-order alternatives belong in the accept-list from the start.**
   `Den ganzen Tag habe ich gearbeitet.` is as correct as
   `Ich habe den ganzen Tag gearbeitet.` Relying on the §4.3 escape hatch to discover
   this would burn a call and a moment of doubt for the first user to hit it. Every
   `transform` item now ships with its fronted-adverbial variant pre-listed.
5. **`spine_hash` was underspecified.** "A hash over the fields the bank depends on"
   doesn't pin down serialization. Now fixed: sha256, first 16 hex chars, over compact
   JSON with sorted keys of `{title_target, level, skill, exercises}`. The golden unit
   carries a real, verifiable hash rather than a placeholder.

Findings 1 and 2 are both *ambiguity* bugs, and both would have shipped as
"the app marked my right answer wrong." That's the failure mode to design against
hardest, and it argues for keeping the cold-solver gate even when it feels redundant.

---

## 9. Risks specific to this model

| Risk | Mitigation |
|---|---|
| **Generated items are subtly wrong** (two valid options, ambiguous stem) | Gates 3 and 4; 100% review of `produce`/`transform`; in-field ⚠️ Report pulls an item instantly |
| **Accept-lists too narrow → correct answers marked wrong** | The single worst UX failure, so it gets the escape hatch (§4.3): LLM adjudication on a miss, plus permanent accept-list growth |
| **Review fatigue → rubber-stamped approvals** | Tiered review (§2.3) with explicit numbers; gates remove the bulk before a human sees anything |
| **Bank drifts from spine after an edit** | `spine_hash` on every item; mismatches go `stale`, old items serve until replacements are approved |
| **A level's syllabus is wrong in ordering or scope** | H1's human pass is the checkpoint, and it's cheap — 24 units is an evening. Ordering mistakes are far costlier after users have progress rows |
| **Cold units make the course feel thin at launch** | Cold path is explicitly supported (§4.5), and demand-ranked shortfall reporting builds the units people actually reach |
| **The build tooling rots into the bot** | `tools/curriculum/` is never imported by `bot/`; enforced by a lint check |

---

## 10. Open decisions

Carried from the phase plan, plus the ones this spec introduces. Recommendations given —
these need your call before H0:

1. **Bank in git (JSONL) or DB-only?** → *Recommend git* (§2.4): fits the existing
   `git pull` deploy, reviewable in PRs, reproducible.
2. **First level and language.** → *Recommend German A2 alone* through H5; English B1 at H6.
3. **Overgeneration factor.** → *Recommend 1.6×*: enough for one genuinely different
   retake without doubling review load.
4. **Pass threshold.** → *Recommend 80%*, unit re-openable any time.
5. **Can a cold unit be marked passed?** → *Recommend yes* (§4.5); users shouldn't pay
   for a build-pipeline gap.
6. **Review depth for mcq/cloze.** → *Recommend 25% spot check*, revisited if the
   ⚠️ Report rate exceeds ~2% of served items.
7. **Hard or soft prerequisites?** → *Recommend soft*: order drives "Continue",
   `/browse` opens anything at or below your level.
8. **Keep the six-skill BKT alongside per-unit mastery?** → *Recommend yes*: coarse bars
   for `/profile`, per-unit for targeting.
