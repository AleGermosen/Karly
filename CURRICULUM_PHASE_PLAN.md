# Phase plan — Curriculum mode (a Test-English–style syllabus inside Karly)

Planning document. Written 2026-09-03. **No code in this phase — this is the design.**

Companion to [`FUTURE_WORK.md`](FUTURE_WORK.md), which stays the general roadmap.
This document covers one thing: giving Karly a structured, level-mapped course
the way [test-english.com](https://test-english.com) has one.

---

## 1. What Test-English actually is, structurally

Stripped of its website-ness, Test-English is four ideas stacked on top of each other:

| Idea | How it shows up on the site |
|---|---|
| **A named, ordered syllabus per CEFR level** | `A1 / A2 / B1 / B1+ / B2`, each with a *Table of grammar contents* — a fixed list of grammar points in a recommended study order (A1: `to be` → present simple → present continuous → `have got` → past simple → `will` → `be going to` → `can` → imperative → articles → possessives …). Every point has a stable identity and a place in a sequence. |
| **A lesson is explanation + several exercises + per-item feedback** | Each grammar point page = a clear explanation (plus a grammar chart) and *three or more* exercise sets, with feedback on **every single question** — not just a final score. |
| **Parallel skill tracks, all level-tagged** | Separate sections for **Grammar**, **Vocabulary** (keywords, definitions, pictures, quiz), **Listening** (short videos; transcript revealed *after* you submit), **Reading** (texts + comprehension), **Writing** (structuring, connectors, grammar, vocabulary). Each is indexed by A1/A2/B1/B1+/B2. |
| **Checkpoints** | A no-time-limit **Level Test** (grammar + vocabulary) that estimates your level, plus per-level **grammar tests** of 15 multiple-choice items drawn from that level's lessons. Above those sit **exam practice** sets that mirror real exam papers (Cambridge A2 Key / B1 Preliminary / B2 First, split into Listening / Reading & Use of English / Writing parts). |

The through-line: **content has an identity and an order, and progress is measured
against that order.** You always know which unit you are on, what comes next, and
whether you've cleared the level.

> Note on sourcing: `test-english.com` is blocked by this environment's egress
> proxy, so the model above was reconstructed from search results across the
> site's own section pages (`/grammar-points/`, `/grammar-points/a1/contents-a1/`,
> `/vocabulary/`, `/listening/a2/`, `/writing/`, `/level-test/`, `/exams/…`). It's
> accurate about structure; before authoring content it's worth one manual pass
> over a real A2 unit page to copy the *lesson shape* exactly.

---

## 2. Where Karly stands against that

Karly is strong exactly where Test-English is empty, and empty exactly where it is strong.

| | Test-English | Karly today |
|---|---|---|
| Conversation with a tutor | ✗ none | ✅ core feature, with graded corrections |
| Adaptive placement | partial (static level test) | ✅ `/test`, adapts difficulty live, per-skill CEFR verdict |
| Spaced repetition | ✗ none | ✅ HLR scheduler, 4 practice modes, deck picker |
| Mastery modelling | ✗ none | ✅ BKT per skill (+ DKT LSTM, gated) |
| Roleplay / production practice | ✗ none | ✅ 6 scenarios per language |
| Personal content (your own PDFs) | ✗ none | ✅ vocabulary extraction + `/learn` |
| **Named, ordered syllabus** | ✅ per level, per point | ❌ **nothing** |
| **Teaching before drilling** | ✅ explanation + chart per point | ❌ drills only; the bot corrects but never *teaches a topic* |
| **"Where am I / what's next"** | ✅ unit list, level progress | ❌ no notion of progress through material |
| **Reading / Listening / Writing tracks** | ✅ level-indexed test series | ❌ none (reading and listening don't exist at all) |
| **Level checkpoints** | ✅ 15-item test per level | ❌ `/test` is a one-off placement, not a gate |
| **Exam preparation** | ✅ Cambridge papers by part | ❌ none |

**The gap in one sentence:** Karly is a very good tutor with no curriculum. Every
piece of content it produces is ephemeral — generated, shown once, and forgotten.
Nothing has an ID, so nothing can be sequenced, revisited, or completed.

**The opportunity in one sentence:** Test-English can never do what Karly does next
— it has no conversation, so it can never say *"you got the perfect vs. simple past
wrong three times while chatting this week; here's that unit."* Closing the curriculum
gap doesn't make Karly a Test-English clone; it makes Karly the thing Test-English
structurally can't be.

---

## 3. What to adopt, adapt, and reject

Telegram is not a website. Deciding this up front prevents a lot of wasted work.

**Adopt as-is**
- The ordered per-level syllabus of named grammar points, with a recommended order.
- Lesson shape: short explanation → several exercise sets → feedback on *every* item.
- Level-tagged parallel tracks: grammar / vocabulary / reading / listening / writing.
- The 15-item per-level checkpoint test.
- Listening's best trick: **transcript revealed only after you answer**.

**Adapt**
- *Browsing* becomes a small inline-keyboard picker, not a nav menu. The default
  path is "▶️ Continue" — one tap, next unit. Browsing is the escape hatch, not the UI.
- *Grammar charts* become 6-bullet explanation cards. A screenful of table doesn't
  survive a phone chat window; if a chart is genuinely needed, render it as a
  monospace block or an image.
- *Pictures* in vocabulary lessons — skip images initially; Telegram supports them,
  but sourcing/licensing them is a project of its own. Text + example sentence first.

**Reject**
- Being a content library. Karly is single-path and personal: one current unit,
  driven by what you actually get wrong.
- Static, identical-for-everyone tests. Karly already has adaptivity — the syllabus
  gives it somewhere to point.
- Building a web front-end. Everything stays in Telegram.

---

## 4. The design

### 4.1 Content model — the one decision that matters

Three options for where units come from:

| Option | Pros | Cons |
|---|---|---|
| **A. Hand-authored** syllabus + exercises committed to the repo | Deterministic, free at runtime, exact CEFR control | Weeks of authoring per level per language |
| **B. Fully LLM-generated** on demand, every time | Zero authoring | Nondeterministic, no stable IDs → **can't track mastery per topic**, can't cache, pays tokens on every view, quality varies per call |
| **C. Hybrid — authored skeleton, generated item bank, cached** ← **recommended** | Stable IDs and ordering, one-time generation cost, deterministic grading, near-zero runtime LLM cost, quality reviewable before it ships | Needs a build step and a review pass |

**Recommendation: C.** The syllabus (unit IDs, titles, CEFR level, order,
prerequisites, explanation, examples, pitfalls) is generated *once* by a batch
script, reviewed by a human, and committed as data. Individual exercise items are
generated in batches into a shared item bank and cached in the DB. The runtime path
touches the LLM only for open-ended production and writing grading.

This is what makes per-topic mastery possible at all: BKT and HLR need a stable
key. `de.a2.g07` is that key. An LLM-improvised question about the perfect tense is not.

### 4.2 Syllabus file format

```
curriculum/
  de/  a1.yaml  a2.yaml  b1.yaml  b2.yaml
  en/  a1.yaml  a2.yaml  b1.yaml  b2.yaml
```

```yaml
- id: de.a2.g07                  # stable forever; never renumber
  kind: grammar                  # grammar | vocab | reading | listening | writing
  level: A2
  order: 7
  title_target: "Perfekt vs. Präteritum"
  title_l1: "Perfect vs. simple past"      # English in DE mode, Spanish in EN mode
  can_do: "I can tell someone what I did at the weekend."
  prereqs: [de.a2.g03]
  skill: grammar                 # maps onto the existing BKT skill names
  explain:                       # 4–8 bullets, shown as the lesson card
    - "..."
  examples:                      # 3 model sentences with an L1 gloss
    - {target: "...", gloss: "..."}
  pitfalls:                      # L1-interference notes — the highest-value field
    - "..."
  exercises:
    - {type: mcq,       n: 5}
    - {type: cloze,     n: 5}
    - {type: transform, n: 3}
    - {type: produce,   n: 2}
```

Notes:
- `skill` keeps every unit compatible with the existing six-skill BKT vocabulary
  (`grammar / reading / comprehension / production / functional / vocab`), so
  `/profile` and `/quiz` keep working unchanged.
- `pitfalls` is where Karly beats a generic course: an English speaker's German
  mistakes and a Spanish speaker's English mistakes are different and predictable.
- Files are the source of truth. No DB table for units, no FK — progress rows just
  carry the `unit_id` string. Simpler, diffable, reviewable in a PR.

### 4.3 Database additions

Three new tables in `db/models.py`, one enum value:

| Table | Columns (sketch) | Purpose |
|---|---|---|
| `unit_progress` | `user_id, unit_id, state, attempts, best_score, p_mastery, first_seen_at, passed_at` | Where each user stands on each unit. `state`: `locked / available / in_progress / passed`. `p_mastery` uses the existing BKT update from `srs/bkt.py`, keyed per unit instead of per skill. |
| `exercise_items` | `unit_id, lang, level, type, payload_json, answer_json, content_hash, created_at` | The shared item bank. Not per-user — items are reusable content, which is what makes warm units cost nothing. |
| `item_attempts` | `user_id, item_id, correct, answer_text, created_at` | Per-item outcomes. Feeds unit mastery, `/weekly`, and DKT's sequence data. |

Also: add `curriculum` to the `VocabSource` enum so vocabulary units seed
`VocabItem` rows that flow straight into the existing HLR scheduler.

Nothing existing changes shape. `ReviewLog`, `ConceptMastery`, `VocabItem` and the
whole SRS layer stay as they are.

### 4.4 Commands and flows

| Command | What it does |
|---|---|
| `/course` | The hub, and the only command most sessions need. Shows current level, a progress bar (`A2 ███████░░░ 7/24`), and the current unit. Buttons: **▶️ Continue · 📚 Browse · 🎯 Level test**. |
| `/browse` | Level picker (A1 / A2 / B1 / B1+ / B2) → paginated unit list with ✅ passed / 🔓 available / 🔒 locked. Selecting a unit opens it. |
| `/leveltest` | The 15-item checkpoint for the current level, drawn from that level's item bank. Pass → level badge + next level unlocks. Fail → the three weakest units come back as a study plan with a "practise these" button. |
| `/reading` | Reading track for the current level (§4.5). |
| `/listening` | Listening track (§4.5) — ships in a later stage, needs audio. |
| `/writing` | Writing track (§4.5). |

**The unit flow** — one screen at a time, matching how `/quiz` and `/daily` already work:

1. **Lesson card** — title, can-do line, ≤6 explanation bullets, 3 examples with
   gloss, 1–2 pitfalls. One message. Button: **▶️ Exercises** (and **⏭ Skip to test**
   for people who already know it).
2. **Exercise run** — items one per message. MCQ via inline buttons; cloze,
   transform, and produce via typed answers. Every item gets feedback immediately:
   ✅/❌, the right answer, one line of *why*, and a **📖 Explain** button that reuses
   the existing `CORRECTION_EXPLAIN` / `ENGLISH_CORRECTION_EXPLAIN` prompt.
3. **Result card** — score, pass/fail against the threshold, updated unit mastery bar.
   On pass: unit marked `passed`, the next unit unlocks. Either way, **every missed
   item becomes a flashcard** via the existing `add_vocab_items` path, so failures
   feed the SRS loop automatically.
4. Back to `/course`, with the next unit queued.

`/stop` and `/cancel` must work at every step, like the other conversation handlers.

### 4.5 Skill tracks

- **Vocabulary units** — a thematic deck per level (food, travel, work, health…):
  term, translation, definition, one example sentence. Seeds `VocabItem` rows with
  `source=curriculum`, then the existing HLR scheduler owns them. Cheapest track to
  build — it's mostly content plus a new deck in the `/practice` picker.
- **Reading** — a level-appropriate text (150–300 words) plus 5 comprehension
  questions (MCQ + true/false/not-given). Generated once per unit and cached like any
  other item. Text first as one message, then questions one at a time.
- **Writing** — a task prompt with a criteria checklist (task achievement,
  structure, connectors, grammar, vocabulary). Graded by an LLM rubric returning a
  per-criterion JSON band plus three concrete fixes; the inline error marks reuse the
  existing corrections pipeline and its `❌ wrong → ✅ right — why` format. This is the
  one track where an LLM call at runtime is unavoidable and worth it.
- **Listening** — needs text-to-speech (note: *not* the speech-to-text of the
  planned voice-notes feature, but the same audio plumbing). Generate a short dialogue
  script → TTS → send as a Telegram voice message → comprehension questions → **reveal
  the transcript only after the answers are submitted**, exactly as Test-English does.
  Candidates: Gemini TTS, gTTS, or Piper locally on the OptiPlex (free, no quota,
  and German/Spanish/English voices are all available). Build this and voice notes
  together; they share the audio send/receive layer.

### 4.6 How this connects to what already exists

This is the part that makes the phase worth doing — the curriculum is not a
side-car, it wires into everything Karly already has:

- **`/test` becomes the course entry point.** The placement verdict picks the start
  level: units at or below it are unlocked as "review available", the first unit at
  level becomes current. Today the verdict is shown once and then does nothing.
- **`/quiz` retargets.** Instead of the three weakest of six coarse skills, it pulls
  from the weakest *units* — a question about `Perfekt vs. Präteritum`, not "grammar".
- **`/daily` gains a curriculum item** as a fourth task, drawn from the current unit.
- **Corrections become a route into the syllabus.** When a conversation correction
  maps to a known unit (matched by the LLM tagging the correction with a `unit_id`,
  or a keyword map as a cheap first version), the correction card gains a
  **"🎯 Practise this unit"** button — and repeated instances surface as
  *"three times this week → open `Perfekt vs. Präteritum`"*. **This is the feature no
  static course site can copy**, and it should be treated as the phase's headline,
  not an afterthought.
- **`/profile` and `/weekly`** gain course progress: units passed this week, current
  level completion, and the per-unit mastery bars beside the existing BKT skill bars.

### 4.7 Cost, latency, and the LLM ladder

The hybrid model was chosen mostly for this:

- **Authoring is a batch job, not a runtime cost.** A level ≈ 24 units × ~15 items
  ≈ 360 items, generated offline by a script (`make curriculum-build`), reviewed, and
  committed / loaded into `exercise_items` once.
- **A warm unit makes zero LLM calls.** Lesson text is data; MCQ, cloze, and
  transform items are graded locally by string comparison. Only `produce` items and
  the writing track need a call — and those go through the existing router.
- **Latency improves rather than degrades.** Today `/quiz` and `/daily` wait on a
  structured-task call before showing the first question. A cached unit shows it instantly.
- **Ollama's JSON weakness stops mattering** for this path — generation happens
  offline where a fallback to Gemini is fine and nobody is waiting.

---

## 5. Staged plan

Each stage is independently shippable and leaves the bot working.

### C0 — Syllabus spike
*No bot changes.* Define the YAML schema (§4.2). Write the generation script that
produces a level's units from a prompt + the CEFR contents list, and run it for **one
level in one language** (suggest German A2 — it's the level with the most real usage
so far). Human pass over all 24 units.
**Exit:** `curriculum/de/a2.yaml` exists, validates against the schema, and reads like
something you'd actually study.

### C1 — Course spine
Three new tables. `/course` hub with progress bar and Continue. Lesson card rendering.
Unlock/prereq logic. Exercises temporarily stubbed to the existing quiz generator.
**Exit:** you can walk German A2 units 1→3 end to end, and `/course` remembers where you are.

### C2 — Exercise engine + item bank
The four item types (mcq / cloze / transform / produce). Offline batch generator +
`exercise_items` cache. Local grading for the closed types. Per-unit mastery via the
BKT update. Missed items auto-added to flashcards. Pass threshold enforced.
**Exit:** a unit can be passed or failed on merit, and a warm unit makes zero LLM calls.

### C3 — Checkpoints and browsing
`/leveltest` (15 items, level promotion, weak-unit study plan on failure). `/browse`
level and unit picker. Course progress in `/profile`. `/test` wired to set the start level.
**Exit:** a full level can be completed and cleared, and you can jump to any unlocked unit.

### C4 — Reading and Writing tracks
Reading generation + cache + comprehension flow. Writing task + rubric grading +
inline corrections. Both indexed by level alongside grammar units.
**Exit:** `/reading` and `/writing` work at the current level in both languages.

### C5 — Listening track
TTS pipeline, voice-message delivery, questions, post-submission transcript reveal.
Build alongside the planned voice-notes feature — shared audio layer.
**Exit:** `/listening` plays a dialogue and reveals its transcript after you answer.

### C6 — Exam preparation *(defer; decide after C3)*
Mirror real paper structures: Goethe A1–B2 / telc / ÖSD for German, Cambridge A2 Key /
B1 Preliminary / B2 First for English — each split into its real parts with real timings.
The deepest content lift and the least differentiated from what already exists, so it
should wait until the course loop has proven itself. Worth revisiting immediately if
the target user is actually sitting an exam.

**English mode runs one level behind German throughout** — same code path, second
syllabus. `curriculum/en/b1.yaml` after German A2 proves the loop.

---

## 6. Open decisions

These change the shape of the work and are worth settling before C0 starts:

1. **First level and language.** Recommend German A2 alone for C0–C2, English B1 added at C3.
2. **Authoring mode.** Recommend LLM-generated then human-reviewed, rather than
   hand-written (weeks) or generated-live (no stable IDs).
3. **Pass threshold.** Recommend 80% to pass a unit, with a unit re-openable any time.
4. **Strict prerequisites or open browsing?** Recommend soft locks: the recommended
   order drives "Continue", but `/browse` lets you open anything at or below your level.
5. **Does listening need real audio, or is a text-dialogue "listening" acceptable
   for v1?** Real audio is the whole point of the track, which is why it's staged last.
6. **Keep the six-skill BKT alongside per-unit mastery?** Recommend yes — coarse
   bars for `/profile`, fine-grained units for targeting.

---

## 7. Non-goals

- No website, no web front-end. Everything stays inside Telegram.
- Not replacing conversation. The course is a second mode, and corrections remain the
  primary way material is chosen.
- Not a content library. One current unit, one next unit, driven by what you get wrong.
- Not multi-tenant work. Everything here is per-`user_id` already and stays compatible
  with the scale phase in `FUTURE_WORK.md`, but none of it depends on that phase.
