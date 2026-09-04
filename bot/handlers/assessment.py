"""/assess — adaptive placement interview ending in a JSON verdict.

Implemented as a ConversationHandler. Works in both German mode and English mode.
German mode: tests German grammar/reading/production for an English speaker.
English mode: tests English grammar/reading/production for a Spanish speaker;
              all instructions to the user are in Spanish.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot import credits as credit_mod
from bot.middleware import require_auth
from db.repo import get_user_by_telegram_id, save_assessment, update_bkt_state
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task
from llm.structured import generate_json

logger = logging.getLogger(__name__)

ASSESSING = 1
MIN_EXCHANGES = 8
MAX_EXCHANGES = 12

CEFR_LADDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
START_LEVEL = "A2"

OPEN_BATCH_SIZE = 5

SKILL_QUOTA = {
    "grammar": 2,
    "reading": 2,
    "comprehension": 2,
    "production": 2,
    "functional": 2,
    "vocab": 2,
}

# ── mode helpers ───────────────────────────────────────────────────────────────

def _is_english(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.user_data.get("assess_mode") == "english"


def _interview_prompt(context: ContextTypes.DEFAULT_TYPE) -> str:
    return prompts.ENGLISH_ASSESS_INTERVIEW if _is_english(context) else prompts.ASSESS_INTERVIEW


def _verdict_prompt(context: ContextTypes.DEFAULT_TYPE) -> str:
    return prompts.ENGLISH_ASSESS_VERDICT if _is_english(context) else prompts.ASSESS_VERDICT


def _grade_prompt(context: ContextTypes.DEFAULT_TYPE) -> str:
    return prompts.ENGLISH_ASSESS_GRADE_OPEN_BATCH if _is_english(context) else prompts.ASSESS_GRADE_OPEN_BATCH


# ── shared helpers ─────────────────────────────────────────────────────────────

def _step_level(level: str, delta: int) -> str:
    try:
        i = CEFR_LADDER.index(level)
    except ValueError:
        i = CEFR_LADDER.index(START_LEVEL)
    return CEFR_LADDER[max(0, min(len(CEFR_LADDER) - 1, i + delta))]


def _skills_needed(results: list[dict]) -> list[str]:
    served: dict[str, int] = {}
    for r in results:
        skill = r.get("skill")
        if skill:
            served[skill] = served.get(skill, 0) + 1
    remaining = {
        skill: quota - served.get(skill, 0) for skill, quota in SKILL_QUOTA.items()
    }
    needed = [s for s, left in remaining.items() if left > 0]
    needed.sort(key=lambda s: remaining[s], reverse=True)
    return needed


def _transcript_text(transcript: list[dict]) -> str:
    lines = []
    for t in transcript:
        who = "KARLY" if t["role"] == "assistant" else "USER"
        lines.append(f"{who}: {t['text']}")
    return "\n".join(lines)


def _item_text(item: dict) -> str:
    parts = []
    passage = (item.get("passage") or "").strip()
    if passage:
        parts.append(passage + "\n")
    parts.append(item.get("prompt", ""))
    if item.get("type") == "mcq" and item.get("options"):
        parts.append("")
        for i, opt in enumerate(item["options"]):
            parts.append(f"{i + 1}. {opt}")
    return "\n".join(parts)


def _mcq_keyboard(item_no: int, options: list) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(str(i + 1), callback_data=f"assess:{item_no}:{i}")
        for i in range(len(options))
    ]
    return InlineKeyboardMarkup([row])


# ── LLM calls ─────────────────────────────────────────────────────────────────

def _is_valid_item(parsed: object) -> bool:
    return isinstance(parsed, dict) and bool((parsed.get("prompt") or "").strip())


async def _next_item(
    transcript: list[dict], needed_skills: list[str], target_level: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> dict | None:
    """Return the next assessment item dict, or None if both attempts fail."""
    skill = needed_skills[0] if needed_skills else "grammar"
    prompt = (
        "Interview transcript so far:\n"
        + (_transcript_text(transcript) or "(none yet — this is the first item)")
        + f"\n\nTarget difficulty for this item: CEFR {target_level}."
        + "\n\nChoose the item's skill from these still-needed skills (pick the "
        "first that fits naturally): "
        + (", ".join(needed_skills) if needed_skills else "(any skill)")
        + "\n\nGive the next interview item as JSON."
    )
    parsed, _ = await generate_json(
        Task.assess, prompt, system=_interview_prompt(context)
    )
    if _is_valid_item(parsed):
        return parsed

    # Retry with a minimal prompt to recover from formatting errors.
    logger.warning("Assessment item was not valid JSON; retrying with simplified prompt.")
    simple_prompt = (
        f"Give ONE {skill} interview item at CEFR {target_level}. "
        "Use type 'mcq' with 4 options. Return ONLY the JSON object, nothing else."
    )
    parsed, _ = await generate_json(
        Task.assess, simple_prompt, system=_interview_prompt(context)
    )
    if _is_valid_item(parsed):
        return parsed

    logger.warning("Assessment item retry also failed; skipping item.")
    return None


async def _grade_open_batch(
    pending: list[dict], context: ContextTypes.DEFAULT_TYPE,
) -> dict[int, tuple[bool, str | None]]:
    if not pending:
        return {}
    if _is_english(context):
        blocks = [
            f"[{p['q_no']}] Question: {p['question']}\nAnswer: {p['answer']}"
            for p in pending
        ]
    else:
        blocks = [
            f"[{p['q_no']}] Frage: {p['question']}\nAntwort: {p['answer']}"
            for p in pending
        ]
    prompt = "Grade each numbered answer.\n\n" + "\n\n".join(blocks)
    try:
        parsed, _ = await generate_json(
            Task.assess, prompt, system=_grade_prompt(context)
        )
    except (QuotaExceeded, LLMUnavailable):
        return {}
    if not isinstance(parsed, list):
        return {}
    graded: dict[int, tuple[bool, str | None]] = {}
    for obj in parsed:
        if isinstance(obj, dict) and "n" in obj and "correct" in obj:
            try:
                graded[int(obj["n"])] = (bool(obj["correct"]), obj.get("feedback"))
            except (ValueError, TypeError):
                continue
    return graded


# ── handlers ───────────────────────────────────────────────────────────────────

@require_auth
async def assess_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user_by_telegram_id(update.effective_user.id)
    mode = getattr(user, "learning_mode", "german") if user else "german"
    en = mode == "english"

    context.user_data["assess_transcript"] = []
    context.user_data["assess_results"] = []
    context.user_data["assess_count"] = 0
    context.user_data["assess_item_no"] = 0
    context.user_data["assess_level"] = START_LEVEL
    context.user_data["assess_open_no"] = 0
    context.user_data["assess_pending_open"] = []
    context.user_data["assess_user_id"] = user.id if user else None
    context.user_data["assess_mode"] = mode

    if en:
        await update.effective_message.reply_text(
            "¡Vamos! Prueba de nivel corta (~8-12 preguntas): gramática, lectura "
            "y escritura libre. Toca un botón para preguntas de opción múltiple, "
            "o escribe tu respuesta para las preguntas abiertas.\n"
            "/cancel para cancelar."
        )
    else:
        await update.effective_message.reply_text(
            "Los geht's — kurze Einstufung (~8-12 Fragen), gemischt: Grammatik, "
            "Lesen, freies Schreiben. Bei Auswahlfragen tippe auf einen Button. "
            "/cancel bricht ab.\n(Starting your placement — tap a button for "
            "multiple-choice, or type your answer for open questions.)"
        )
    return await _serve_next(update, context)


async def _serve_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    transcript: list[dict] = context.user_data["assess_transcript"]
    results: list[dict] = context.user_data["assess_results"]
    count = context.user_data["assess_count"]
    en = _is_english(context)

    if count >= MAX_EXCHANGES:
        return await _finish(update, context, transcript)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )
    needed = _skills_needed(results)
    target_level = context.user_data.get("assess_level", START_LEVEL)
    try:
        item = await _next_item(transcript, needed, target_level, context)
    except QuotaExceeded:
        await context.bot.send_message(
            update.effective_chat.id,
            credit_mod.capacity_exhausted_text(en),
            reply_markup=credit_mod.capacity_exhausted_keyboard(en),
        )
        return ConversationHandler.END
    except LLMUnavailable:
        msg = "Algo falló. Inténtalo más tarde con /test." if en else "Da ging etwas schief bei der Einstufung. Versuch es später mit /test."
        await context.bot.send_message(update.effective_chat.id, msg)
        return ConversationHandler.END

    if item is None:
        # Both attempts produced unusable JSON — skip this slot.
        skips = context.user_data.get("assess_skips", 0) + 1
        context.user_data["assess_skips"] = skips
        context.user_data["assess_count"] += 1
        if skips >= 3:
            # Too many consecutive failures — wrap up with what we have.
            logger.error("3 consecutive assessment item failures; ending early.")
            return await _finish(update, context, transcript)
        return await _serve_next(update, context)

    context.user_data["assess_skips"] = 0  # reset on success

    item_no = context.user_data["assess_item_no"] + 1
    context.user_data["assess_item_no"] = item_no
    context.user_data["assess_item"] = item
    transcript.append({"role": "assistant", "text": _item_text(item)})

    text = _item_text(item)
    keyboard = None
    if item.get("type") == "mcq" and item.get("options"):
        keyboard = _mcq_keyboard(item_no, item["options"])
    else:
        q_no = context.user_data.get("assess_open_no", 0) + 1
        context.user_data["assess_open_no"] = q_no
        item["_q_no"] = q_no
        label = f"✍️ Pregunta abierta {q_no}:" if en else f"✍️ Offene Frage {q_no}:"
        text = f"{label}\n{text}"

    if count >= MIN_EXCHANGES:
        hint = "(¡Casi listo! Sigue respondiendo o usa /done para ver tu resultado.)" if en else "(Fast fertig — antworte weiter, oder /done für die Auswertung.)"
        await context.bot.send_message(update.effective_chat.id, hint)
    await context.bot.send_message(
        update.effective_chat.id, text, reply_markup=keyboard
    )
    return ASSESSING


@require_auth
async def assess_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, raw_no, raw_idx = query.data.split(":")
    item_no, choice = int(raw_no), int(raw_idx)
    en = _is_english(context)

    if item_no != context.user_data.get("assess_item_no"):
        return ASSESSING
    item = context.user_data.get("assess_item")
    if not item or item.get("type") != "mcq":
        return ASSESSING

    options = item.get("options") or []
    answer_index = item.get("answer_index")
    chosen = options[choice] if 0 <= choice < len(options) else "?"
    correct = choice == answer_index

    context.user_data["assess_results"].append(
        {"skill": item.get("skill"), "level": item.get("level"), "correct": correct}
    )
    context.user_data["assess_transcript"].append(
        {"role": "user", "text": f"Chose: {chosen} ({'correct' if correct else 'wrong'})"}
    )
    context.user_data["assess_count"] += 1

    skill = item.get("skill")
    user_id = context.user_data.get("assess_user_id")
    if skill and user_id:
        update_bkt_state(user_id, skill, correct, level=item.get("level"))

    context.user_data["assess_level"] = _step_level(
        context.user_data.get("assess_level", START_LEVEL), 1 if correct else -1
    )

    if en:
        mark = "✅ ¡Correcto!" if correct else "❌ Incorrecto."
        if not correct and isinstance(answer_index, int) and 0 <= answer_index < len(options):
            mark += f" Respuesta correcta: {options[answer_index]}"
    else:
        mark = "✅ Richtig!" if correct else "❌ Leider falsch."
        if not correct and isinstance(answer_index, int) and 0 <= answer_index < len(options):
            mark += f" Richtige Antwort: {options[answer_index]}"

    await query.edit_message_text(_item_text(item) + f"\n\n{mark}")
    return await _serve_next(update, context)


async def _flush_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = context.user_data.get("assess_pending_open") or []
    if not pending:
        return
    en = _is_english(context)
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )
    graded = await _grade_open_batch(pending, context)
    results = context.user_data["assess_results"]
    transcript = context.user_data["assess_transcript"]

    net = 0
    lines = []
    user_id = context.user_data.get("assess_user_id")
    for p in pending:
        g = graded.get(p["q_no"])
        if g is None:
            continue
        correct, feedback = g
        results[p["result_idx"]]["correct"] = correct
        transcript[p["transcript_idx"]]["text"] += (
            f" ({'correct' if correct else 'wrong'})"
        )
        net += 1 if correct else -1
        mark = "✅" if correct else "❌"
        label = f"Pregunta {p['q_no']}" if en else f"Frage {p['q_no']}"
        lines.append(f"{label}: {mark}" + (f" {feedback}" if feedback else ""))

        result_entry = results[p["result_idx"]]
        skill = result_entry.get("skill")
        if skill and user_id:
            update_bkt_state(user_id, skill, correct, level=result_entry.get("level"))

    if net:
        context.user_data["assess_level"] = _step_level(
            context.user_data.get("assess_level", START_LEVEL), 1 if net > 0 else -1
        )
    context.user_data["assess_pending_open"] = []
    if lines:
        await context.bot.send_message(update.effective_chat.id, "\n".join(lines))


@require_auth
async def assess_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item = context.user_data.get("assess_item") or {}
    answer = (update.effective_message.text or "").strip()

    transcript = context.user_data["assess_transcript"]
    transcript.append({"role": "user", "text": answer})
    results = context.user_data["assess_results"]
    results.append(
        {"skill": item.get("skill"), "level": item.get("level"), "correct": None}
    )
    context.user_data.setdefault("assess_pending_open", []).append(
        {
            "q_no": item.get("_q_no", context.user_data["assess_count"] + 1),
            "question": _item_text(item),
            "answer": answer,
            "result_idx": len(results) - 1,
            "transcript_idx": len(transcript) - 1,
        }
    )
    context.user_data["assess_count"] += 1

    if len(context.user_data["assess_pending_open"]) >= OPEN_BATCH_SIZE:
        await _flush_open(update, context)
    return await _serve_next(update, context)


@require_auth
async def assess_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    en = _is_english(context)
    transcript: list[dict] = context.user_data.get("assess_transcript", [])
    if context.user_data.get("assess_count", 0) < 3:
        msg = "Por favor responde unas preguntas más primero." if en else "Beantworte bitte noch ein paar Fragen zuerst. (A few more first.)"
        await update.effective_message.reply_text(msg)
        return ASSESSING
    return await _finish(update, context, transcript)


async def _finish(
    update: Update, context: ContextTypes.DEFAULT_TYPE, transcript: list[dict]
) -> int:
    en = _is_english(context)
    msg = "¡Gracias! Evaluando tus respuestas…" if en else "Danke! Ich werte deine Antworten aus… (Scoring your answers…)"
    await update.effective_message.reply_text(msg)
    await _flush_open(update, context)
    prompt = (
        "Full interview transcript:\n"
        + _transcript_text(transcript)
        + "\n\nPer-item results summary:\n"
        + _results_summary(context.user_data.get("assess_results", []))
        + "\n\nProduce the verdict JSON."
    )
    try:
        verdict, raw = await generate_json(
            Task.assess, prompt, system=_verdict_prompt(context)
        )
    except QuotaExceeded:
        msg = "Límite alcanzado — inténtalo más tarde. 🙏" if en else "Tageslimit erreicht — versuch es später. 🙏"
        await update.effective_message.reply_text(msg)
        return ConversationHandler.END
    except LLMUnavailable:
        msg = "Algo falló. Inténtalo más tarde." if en else "Da ging etwas schief bei der Einstufung. Versuch es später mit /test."
        await update.effective_message.reply_text(msg)
        return ConversationHandler.END

    if not isinstance(verdict, dict) or not verdict.get("overall"):
        logger.warning("Verdict was not valid JSON; retrying with explicit JSON hint.")
        retry_prompt = prompt + "\n\nIMPORTANT: Return ONLY a valid JSON object. No prose, no markdown, no code fences."
        try:
            verdict, raw = await generate_json(
                Task.assess, retry_prompt, system=_verdict_prompt(context)
            )
        except (QuotaExceeded, LLMUnavailable):
            verdict = None

    user = get_user_by_telegram_id(update.effective_user.id)
    if not isinstance(verdict, dict) or not verdict.get("overall"):
        logger.error("Verdict retry also failed; showing graceful error.")
        if user:
            save_assessment(user.id, {"overall": None, "gaps": []}, transcript)
        msg = (
            "Pude evaluar tus respuestas pero no formatear el resultado. "
            "Tu progreso fue guardado. Intenta /profile más tarde."
            if en else
            "Ich konnte deine Antworten auswerten, aber das Ergebnis nicht formatieren. "
            "Dein Fortschritt wurde gespeichert. Schau später in /profile nach."
        )
        await update.effective_message.reply_text(msg)
        _clear(context)
        return ConversationHandler.END

    results = context.user_data.get("assess_results", [])
    scores = _scored_counts(results)
    if scores:
        verdict["auto_scores"] = scores
    if user:
        save_assessment(user.id, verdict, transcript)

    message = _format_verdict(verdict, en)
    breakdown = _scored_breakdown(scores, en)
    if breakdown:
        label = "\nTus preguntas de opción múltiple (auto-calificadas):\n" if en else "\nDeine Auswahlfragen (auto-scored):\n"
        message += label + breakdown
    await update.effective_message.reply_text(message)
    _clear(context)
    return ConversationHandler.END


def _format_verdict(v: dict, en: bool) -> str:
    skills = v.get("skills") or {}
    skill_lines = "\n".join(
        f"  • {k.capitalize()}: {val}" for k, val in skills.items()
    )
    gaps = v.get("gaps") or []
    gap_lines = "\n".join(f"  • {g}" for g in gaps)
    if en:
        parts = [f"📊 *¡Prueba completada!*\n\nNivel general: *{v.get('overall', '?')}*"]
        if skill_lines:
            parts.append("\nPor habilidad:\n" + skill_lines)
        if gap_lines:
            parts.append("\nÁreas a mejorar:\n" + gap_lines)
        if v.get("summary"):
            parts.append("\n" + v["summary"])
        parts.append("\nRevisa /profile. ¡Ahora practica escribiendo en inglés!")
    else:
        parts = [f"📊 *Einstufung fertig!*\n\nOverall: *{v.get('overall', '?')}*"]
        if skill_lines:
            parts.append("\nPer skill:\n" + skill_lines)
        if gap_lines:
            parts.append("\nGaps to work on:\n" + gap_lines)
        if v.get("summary"):
            parts.append("\n" + v["summary"])
        parts.append("\nSieh dir /profile an. Jetzt einfach drauflos schreiben!")
    return "\n".join(parts)


def _scored_counts(results: list[dict]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for r in results:
        if r.get("correct") is None:
            continue
        skill = r.get("skill") or "unknown"
        c = counts.setdefault(skill, {"correct": 0, "total": 0})
        c["total"] += 1
        c["correct"] += 1 if r["correct"] else 0
    return counts


def _scored_breakdown(scores: dict[str, dict[str, int]], en: bool = False) -> str:
    return "\n".join(
        f"  • {skill.capitalize()}: {c['correct']}/{c['total']}"
        for skill, c in scores.items()
    )


def _results_summary(results: list[dict]) -> str:
    if not results:
        return "(no auto-scored items)"
    scores = _scored_counts(results)
    lines = [
        f"- {skill}: {c['correct']}/{c['total']} correct"
        for skill, c in scores.items()
    ]
    ungraded = sum(1 for r in results if r.get("correct") is None)
    if ungraded:
        lines.append(f"- ungraded written responses: {ungraded} (judge from transcript)")
    return "\n".join(lines) or "(no auto-scored items)"


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "assess_transcript", "assess_results", "assess_count",
        "assess_item_no", "assess_item", "assess_level",
        "assess_open_no", "assess_pending_open", "assess_user_id", "assess_mode",
        "assess_skips",
    ):
        context.user_data.pop(key, None)


@require_auth
async def assess_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    en = _is_english(context)
    _clear(context)
    msg = "Prueba cancelada." if en else "Einstufung abgebrochen. (Assessment cancelled.)"
    await update.effective_message.reply_text(msg)
    return ConversationHandler.END


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler(["test", "assess"], assess_start)],
        states={
            ASSESSING: [
                CommandHandler("done", assess_done),
                CommandHandler("cancel", assess_cancel),
                CallbackQueryHandler(assess_choice, pattern=r"^assess:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, assess_answer),
            ]
        },
        fallbacks=[CommandHandler("cancel", assess_cancel)],
        name="assessment",
    )
