"""/roleplay — immersive German roleplay scenes.

AJ picks a scenario; Karly plays a character and keeps the conversation going
in German at AJ's level. Inline corrections fire using the same rules as normal
chat. /done ends the scene and triggers a short English debrief.
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

from bot.middleware import require_auth
from db.repo import get_user_by_telegram_id, record_practice
from llm import prompts
from llm.gemini import LLMUnavailable, QuotaExceeded
from llm.router import Task, route

logger = logging.getLogger(__name__)

PICKING = 1
IN_SCENE = 2

QUOTA_MSG = "Tageslimit erreicht — versuch es später. 🙏"
ERROR_MSG = "Szene konnte nicht gestartet werden. Versuch es später."

# Each scenario: (callback_key, display_title, scene_description)
SCENARIOS: list[tuple[str, str, str]] = [
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

_KEY_TO_SCENARIO: dict[str, tuple[str, str, str]] = {s[0]: s for s in SCENARIOS}


def _scenario_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, title, _ in SCENARIOS:
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


def _correction_block(level: str) -> str:
    if level == "strict":
        return prompts.CORRECTION_STRICT
    if level == "relaxed":
        return prompts.CORRECTION_RELAXED
    return prompts.NO_CORRECTION_NOTE


@require_auth
async def roleplay_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    args = context.args or []
    # If a scenario key was passed as an argument, skip the picker.
    if args and args[0] in _KEY_TO_SCENARIO:
        return await _launch_scene(update, context, args[0])

    await update.effective_message.reply_text(
        "🎭 Wähle eine Szene:\n(Choose a scene to practise German in context.)",
        reply_markup=_scenario_keyboard(),
    )
    return PICKING


@require_auth
async def on_scene_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    # Edit out the keyboard so it doesn't stay tappable.
    await query.edit_message_reply_markup(reply_markup=None)
    return await _launch_scene(update, context, key)


async def _launch_scene(
    update: Update, context: ContextTypes.DEFAULT_TYPE, key: str
) -> int:
    scenario = _KEY_TO_SCENARIO.get(key)
    if not scenario:
        await update.effective_message.reply_text("Unbekannte Szene. (Unknown scene.)")
        return ConversationHandler.END

    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return ConversationHandler.END

    _, title, description = scenario
    level = _user_level(user)
    correction_block = _correction_block(user.correction_level)

    system = prompts.ROLEPLAY_SCENE.format(
        scene_title=title,
        scene_description=description,
        level=level,
        correction_block=correction_block,
    )

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        opening = await route(Task.chat, "Start the scene.", system=system)
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        return ConversationHandler.END
    except LLMUnavailable:
        await update.effective_message.reply_text(ERROR_MSG)
        return ConversationHandler.END

    context.user_data["scene_key"] = key
    context.user_data["scene_title"] = title
    context.user_data["scene_system"] = system
    context.user_data["scene_history"] = [
        {"role": "assistant", "text": opening}
    ]
    context.user_data["scene_turns"] = 0
    context.user_data["scene_user_id"] = user.id
    record_practice(user.id)

    header = f"🎭 *{title}*\n/done zum Beenden\n\n"
    await update.effective_message.reply_text(header + opening)
    return IN_SCENE


@require_auth
async def scene_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.effective_message.text or "").strip()
    system = context.user_data.get("scene_system")
    history = context.user_data.get("scene_history", [])
    if not system:
        return ConversationHandler.END

    history.append({"role": "user", "text": text})
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Pass history as alternating user/assistant turns.
    llm_history = [
        {"role": h["role"], "content": h["text"]} for h in history[:-1]
    ]
    try:
        reply = await route(Task.chat, text, system=system, history=llm_history)
    except QuotaExceeded:
        await update.effective_message.reply_text(QUOTA_MSG)
        return IN_SCENE
    except LLMUnavailable:
        await update.effective_message.reply_text("(Backend nicht erreichbar — versuch nochmal.)")
        return IN_SCENE

    history.append({"role": "assistant", "text": reply})
    context.user_data["scene_history"] = history
    context.user_data["scene_turns"] = context.user_data.get("scene_turns", 0) + 1

    await update.effective_message.reply_text(reply)

    # Nudge toward /done after 10 turns so the scene doesn't run forever.
    turns = context.user_data["scene_turns"]
    if turns == 10:
        await update.effective_message.reply_text(
            "(Gute Arbeit! Tippe /done wenn du fertig bist — ich gebe dir Feedback.)"
        )
    return IN_SCENE


@require_auth
async def scene_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    system = context.user_data.get("scene_system")
    history = context.user_data.get("scene_history", [])
    turns = context.user_data.get("scene_turns", 0)

    if turns == 0 or not system:
        _clear(context)
        await update.effective_message.reply_text("Szene beendet. (Scene ended.)")
        return ConversationHandler.END

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    llm_history = [{"role": h["role"], "content": h["text"]} for h in history]
    try:
        debrief = await route(Task.chat, "/done", system=system, history=llm_history)
    except (QuotaExceeded, LLMUnavailable):
        debrief = "(Feedback nicht verfügbar — gute Arbeit trotzdem!)"

    title = context.user_data.get("scene_title", "Szene")
    _clear(context)
    await update.effective_message.reply_text(
        f"🎭 *{title}* — {turns} Runden\n\n{debrief}"
    )
    return ConversationHandler.END


@require_auth
async def scene_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear(context)
    await update.effective_message.reply_text(
        "Szene abgebrochen. (Roleplay stopped.)"
    )
    return ConversationHandler.END


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in (
        "scene_key", "scene_title", "scene_system",
        "scene_history", "scene_turns", "scene_user_id",
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
