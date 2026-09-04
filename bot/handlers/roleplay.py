"""/roleplay — immersive language roleplay scenes.

German mode: AJ practises German with Karly playing a character.
English mode: Spanish-speaking user practises English with Karly playing a character.
              All UI strings for English mode are in Spanish.
"""
from __future__ import annotations

import json
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
from db.repo import get_user_by_telegram_id, record_practice
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task, route

logger = logging.getLogger(__name__)

PICKING = 1
IN_SCENE = 2

# ── German scenarios ──────────────────────────────────────────────────────────

SCENARIOS_DE: list[tuple[str, str, str]] = [
    (
        "supermarkt",
        "🛒 Im Supermarkt",
        "You are a friendly German supermarket cashier. AJ is shopping and "
        "needs help finding things and checking out. Keep it realistic and "
        "use everyday German shopping vocabulary.",
    ),
    (
        "buero",
        "💼 Im Büro — Teambesprechung",
        "You are AJ's German colleague opening a short team standup meeting. "
        "Ask about his progress on a software project, discuss blockers, and "
        "plan the day. Use realistic engineering/workplace German.",
    ),
    (
        "arzt",
        "🏥 Beim Arzt",
        "You are a German GP (Hausarzt). AJ has come in with a common complaint "
        "(headache, tiredness). Ask about symptoms, give simple advice. Use "
        "clear, standard German — not overly technical.",
    ),
    (
        "restaurant",
        "🍽️ Im Restaurant",
        "You are a waiter at a mid-range German restaurant. AJ is a customer: "
        "take his order, answer questions about the menu, handle a small mix-up "
        "or special request naturally.",
    ),
    (
        "interview",
        "🎤 Vorstellungsgespräch",
        "You are an HR manager interviewing AJ for a software engineering role "
        "at a German company. Ask about his background, experience, and "
        "motivation in professional German. Adapt if he struggles.",
    ),
    (
        "technik",
        "🖥️ Technisches Problem erklären",
        "You are AJ's less-technical German manager. AJ needs to explain a "
        "server outage or bug in simple terms. Ask clarifying questions, push "
        "back when things are unclear. Use realistic workplace German.",
    ),
]

# ── English scenarios (for Spanish speakers) ──────────────────────────────────

SCENARIOS_EN: list[tuple[str, str, str]] = [
    (
        "coffee",
        "☕ At the Coffee Shop",
        "You are a friendly barista at a busy coffee shop. The user is ordering "
        "drinks and food, asking about options, and making small talk. Use "
        "natural everyday English at a relaxed pace.",
    ),
    (
        "doctor",
        "🏥 At the Doctor's",
        "You are a friendly GP. The user has come in with a common complaint "
        "(cold, headache, tiredness). Ask about symptoms, give simple advice. "
        "Use clear, standard English — not overly technical.",
    ),
    (
        "airport",
        "✈️ At the Airport",
        "You are an airline check-in agent. The user is checking in for a flight, "
        "asking about luggage, boarding gates, and delays. Use polite, standard "
        "English typical of airport staff.",
    ),
    (
        "phone",
        "📞 Making a Phone Call",
        "You are a customer service representative at a bank or utility company. "
        "The user is calling to ask about their account or report a problem. Use "
        "natural phone English: greetings, holds, clarifying questions.",
    ),
    (
        "hotel",
        "🏨 Hotel Check-in",
        "You are a hotel receptionist. The user is checking in, asking about "
        "amenities, and reporting a small problem with their room. Use polite "
        "hospitality English.",
    ),
    (
        "interview_en",
        "💼 Job Interview (English)",
        "You are an HR manager interviewing the user for an entry-level office "
        "role. Ask about their background, strengths, and why they want the job. "
        "Use professional but accessible English. Adapt if they struggle.",
    ),
]

_KEY_DE: dict[str, tuple[str, str, str]] = {s[0]: s for s in SCENARIOS_DE}
_KEY_EN: dict[str, tuple[str, str, str]] = {s[0]: s for s in SCENARIOS_EN}


def _scenario_keyboard(en: bool) -> InlineKeyboardMarkup:
    scenarios = SCENARIOS_EN if en else SCENARIOS_DE
    rows = []
    for key, title, _ in scenarios:
        rows.append([InlineKeyboardButton(title, callback_data=f"scene:{key}")])
    return InlineKeyboardMarkup(rows)


def _user_level(user) -> str:
    if user.cefr_estimate:
        try:
            data = json.loads(user.cefr_estimate)
            if isinstance(data, dict) and data.get("overall"):
                return str(data["overall"])
        except (ValueError, TypeError):
            pass
    return "A2-B1"


def _correction_block(level: int, en: bool) -> str:
    return prompts.build_correction_block(level, english=en)


def _scene_en(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.user_data.get("scene_mode") == "english"


@require_auth
async def roleplay_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user_by_telegram_id(update.effective_user.id)
    mode = getattr(user, "learning_mode", "german") if user else "german"
    en = mode == "english"
    context.user_data["scene_mode"] = mode

    args = context.args or []
    key_map = _KEY_EN if en else _KEY_DE
    if args and args[0] in key_map:
        return await _launch_scene(update, context, args[0])

    if en:
        await update.effective_message.reply_text(
            "🎭 Elige una escena para practicar inglés:",
            reply_markup=_scenario_keyboard(en=True),
        )
    else:
        await update.effective_message.reply_text(
            "🎭 Wähle eine Szene:\n(Choose a scene to practise German in context.)",
            reply_markup=_scenario_keyboard(en=False),
        )
    return PICKING


@require_auth
async def on_scene_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    await query.edit_message_reply_markup(reply_markup=None)
    return await _launch_scene(update, context, key)


async def _launch_scene(
    update: Update, context: ContextTypes.DEFAULT_TYPE, key: str
) -> int:
    en = _scene_en(context)
    key_map = _KEY_EN if en else _KEY_DE
    scenario = key_map.get(key)
    if not scenario:
        msg = "Escena desconocida." if en else "Unbekannte Szene. (Unknown scene.)"
        await update.effective_message.reply_text(msg)
        return ConversationHandler.END

    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return ConversationHandler.END

    _credit_status = credit_mod.credits_check(user.id, credit_mod.COSTS["chat"])
    if _credit_status != "ok":
        _text, _kb = credit_mod.credit_error_response(en, _credit_status)
        await update.effective_message.reply_text(_text, reply_markup=_kb)
        return ConversationHandler.END

    _, title, description = scenario
    level = _user_level(user)
    correction_block = _correction_block(user.correction_level, en)

    scene_prompt = prompts.ENGLISH_ROLEPLAY_SCENE if en else prompts.ROLEPLAY_SCENE
    system = scene_prompt.format(
        scene_title=title,
        scene_description=description,
        level=level,
        correction_block=correction_block,
    )

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        opening = await route(Task.chat, "Start the scene.", system=system)
    except QuotaExceeded:
        msg = "Límite alcanzado — inténtalo más tarde. 🙏" if en else "Tageslimit erreicht — versuch es später. 🙏"
        await update.effective_message.reply_text(msg)
        return ConversationHandler.END
    except LLMUnavailable:
        msg = "No se pudo iniciar la escena. Inténtalo más tarde." if en else "Szene konnte nicht gestartet werden. Versuch es später."
        await update.effective_message.reply_text(msg)
        return ConversationHandler.END

    credit_mod.spend(user.id, task="chat", model="roleplay")

    context.user_data["scene_key"] = key
    context.user_data["scene_title"] = title
    context.user_data["scene_system"] = system
    context.user_data["scene_history"] = [{"role": "assistant", "text": opening}]
    context.user_data["scene_turns"] = 0
    context.user_data["scene_user_id"] = user.id
    record_practice(user.id)

    done_hint = "/done para terminar" if en else "/done zum Beenden"
    header = f"🎭 *{title}*\n{done_hint}\n\n"
    await update.effective_message.reply_text(header + opening)
    return IN_SCENE


@require_auth
async def scene_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.effective_message.text or "").strip()
    system = context.user_data.get("scene_system")
    history = context.user_data.get("scene_history", [])
    en = _scene_en(context)
    if not system:
        return ConversationHandler.END

    user = get_user_by_telegram_id(update.effective_user.id)
    if user:
        _credit_status = credit_mod.credits_check(user.id, credit_mod.COSTS["chat"])
        if _credit_status != "ok":
            _text, _kb = credit_mod.credit_error_response(en, _credit_status)
            await update.effective_message.reply_text(_text, reply_markup=_kb)
            return IN_SCENE

    history.append({"role": "user", "text": text})
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    llm_history = [{"role": h["role"], "text": h["text"]} for h in history[:-1]]
    try:
        reply = await route(Task.chat, text, system=system, history=llm_history)
    except QuotaExceeded:
        msg = "Límite alcanzado — inténtalo más tarde. 🙏" if en else "Tageslimit erreicht — versuch es später. 🙏"
        await update.effective_message.reply_text(msg)
        return IN_SCENE
    except LLMUnavailable:
        msg = "(Backend no disponible — inténtalo de nuevo.)" if en else "(Backend nicht erreichbar — versuch nochmal.)"
        await update.effective_message.reply_text(msg)
        return IN_SCENE

    if user:
        credit_mod.spend(user.id, task="chat", model="roleplay")
    history.append({"role": "assistant", "text": reply})
    context.user_data["scene_history"] = history
    context.user_data["scene_turns"] = context.user_data.get("scene_turns", 0) + 1

    await update.effective_message.reply_text(reply)

    turns = context.user_data["scene_turns"]
    if turns == 10:
        nudge = "(¡Buen trabajo! Escribe /done cuando termines — te daré retroalimentación.)" if en else "(Gute Arbeit! Tippe /done wenn du fertig bist — ich gebe dir Feedback.)"
        await update.effective_message.reply_text(nudge)
    return IN_SCENE


@require_auth
async def scene_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    system = context.user_data.get("scene_system")
    history = context.user_data.get("scene_history", [])
    turns = context.user_data.get("scene_turns", 0)
    en = _scene_en(context)

    if turns == 0 or not system:
        _clear(context)
        msg = "Escena terminada." if en else "Szene beendet. (Scene ended.)"
        await update.effective_message.reply_text(msg)
        return ConversationHandler.END

    user_id = context.user_data.get("scene_user_id")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    llm_history = [{"role": h["role"], "text": h["text"]} for h in history]
    try:
        debrief = await route(Task.chat, "/done", system=system, history=llm_history)
        if user_id:
            credit_mod.spend(user_id, task="chat", model="roleplay_debrief")
    except (QuotaExceeded, LLMUnavailable):
        debrief = "(¡Buen trabajo de todas formas!)" if en else "(Feedback nicht verfügbar — gute Arbeit trotzdem!)"

    title = context.user_data.get("scene_title", "Scene")
    rounds_label = "rondas" if en else "Runden"
    _clear(context)
    await update.effective_message.reply_text(
        f"🎭 *{title}* — {turns} {rounds_label}\n\n{debrief}"
    )
    return ConversationHandler.END


@require_auth
async def scene_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    en = _scene_en(context)
    _clear(context)
    msg = "Escena cancelada." if en else "Szene abgebrochen. (Roleplay stopped.)"
    await update.effective_message.reply_text(msg)
    return ConversationHandler.END


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in (
        "scene_key", "scene_title", "scene_system",
        "scene_history", "scene_turns", "scene_user_id", "scene_mode",
    ):
        context.user_data.pop(k, None)


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("roleplay", roleplay_start)],
        states={
            PICKING: [
                CallbackQueryHandler(on_scene_pick, pattern=r"^scene:"),
            ],
            IN_SCENE: [
                CommandHandler("done", scene_done),
                CommandHandler("stop", scene_stop),
                CommandHandler("cancel", scene_stop),
                MessageHandler(filters.TEXT & ~filters.COMMAND, scene_message),
            ],
        },
        fallbacks=[
            CommandHandler("done", scene_done),
            CommandHandler("stop", scene_stop),
        ],
        name="roleplay",
        per_message=False,
    )
