"""Karly entrypoint: registers handlers and runs long polling."""
from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    Defaults,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

import config
from bot.handlers import (
    assessment,
    classroom,
    conversation,
    course,
    daily,
    leveltest,
    documents,
    drill,
    export,
    game,
    media,
    payments,
    practice,
    pronounce,
    quiz,
    reminders,
    report,
    roleplay,
    start,
    switcher,
    vocab,
)
from db.session import init_db
from llm import ollama_client

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
# python-telegram-bot talks to Telegram over httpx, which logs every request
# line at INFO — and the bot token is part of the Telegram API URL path. Quiet
# the HTTP client loggers so the token never lands in journald.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("karly")


def build_application() -> Application:
    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.MARKDOWN))
        .build()
    )

    app.add_handler(CommandHandler("start", start.start))
    app.add_handler(CommandHandler("help", start.help_cmd))
    app.add_handler(CommandHandler("language", start.language_cmd))
    app.add_handler(CommandHandler("profile", start.profile))
    app.add_handler(CommandHandler("mybudget", start.mybudget))
    app.add_handler(CommandHandler("pronounce", pronounce.pronounce))
    # Language picker callback (from /start and /language inline buttons).
    app.add_handler(
        CallbackQueryHandler(start.language_pick, pattern=r"^lang:")
    )

    # Teacher classroom commands.
    app.add_handler(CommandHandler("students", classroom.students))
    app.add_handler(CommandHandler("student", classroom.student))
    app.add_handler(CommandHandler("class", classroom.class_summary))
    app.add_handler(CommandHandler("budget", classroom.budget))
    app.add_handler(CommandHandler("grant", classroom.grant))
    app.add_handler(CommandHandler("assign", classroom.assign))
    app.add_handler(CommandHandler("assignunit", classroom.assignunit))
    app.add_handler(CommandHandler("classtopic", classroom.classtopic))
    app.add_handler(CommandHandler("newclass", classroom.newclass))
    app.add_handler(CommandHandler("classes", classroom.classes))
    app.add_handler(CommandHandler("moveclass", classroom.moveclass))
    app.add_handler(CommandHandler("classsetcorr", classroom.classsetcorr))
    app.add_handler(CommandHandler("export", export.export_csv))
    app.add_handler(CommandHandler("broadcast", classroom.broadcast))
    app.add_handler(CommandHandler("addword", vocab.addword))
    app.add_handler(media.build_setmedia_handler())
    app.add_handler(CommandHandler("task", media.task_cmd))
    app.add_handler(CommandHandler("results", media.results))
    app.add_handler(CommandHandler("clearmedia", media.clearmedia))
    # Superuser-only teacher management.
    app.add_handler(CommandHandler("addteacher", classroom.addteacher))
    app.add_handler(CommandHandler("removeteacher", classroom.removeteacher))
    app.add_handler(CommandHandler("grantunlimited", classroom.grantunlimited))
    app.add_handler(CommandHandler("revokeunlimited", classroom.revokeunlimited))
    app.add_handler(CommandHandler("teachers", classroom.teachers_list))
    # Approval flow callbacks (multi-step DM to superuser).
    app.add_handler(
        CallbackQueryHandler(classroom.on_approve_student, pattern=r"^approve_s:")
    )
    app.add_handler(
        CallbackQueryHandler(classroom.on_set_teacher, pattern=r"^set_teacher_s:")
    )
    app.add_handler(
        CallbackQueryHandler(classroom.on_set_class, pattern=r"^set_class_s:")
    )
    app.add_handler(
        CallbackQueryHandler(classroom.on_decline_student, pattern=r"^decline_student:")
    )
    app.add_handler(
        CallbackQueryHandler(classroom.on_broadcast_confirm, pattern=r"^broadcast:")
    )
    app.add_handler(
        CallbackQueryHandler(classroom.on_placement_pick, pattern=r"^placement:")
    )
    app.add_handler(
        CallbackQueryHandler(classroom.on_placement_level_pick, pattern=r"^placement_level:")
    )

    # Course handlers (H3/H4/H5) — registered before the catch-all text handler.
    for handler in course.build_handlers():
        app.add_handler(handler)
    for handler in leveltest.build_handlers():
        app.add_handler(handler)

    # Conversation flows (registered before the catch-all handler).
    assessment_h = assessment.build_handler()
    practice_h = practice.build_handler()
    daily_h = daily.build_handler()
    quiz_h = quiz.build_handler()
    drill_h = drill.build_handler()
    roleplay_h = roleplay.build_handler()

    # Register the session switcher so users can jump between modes without /stop.
    switcher.register({
        "assess_mode":   (assessment._clear,  assessment_h,  "Test"),
        "practice_mode": (practice._clear,    practice_h,    "Practice"),
        "daily_mode":    (daily._clear,       daily_h,       "Daily"),
        "quiz_mode":     (quiz._clear,        quiz_h,        "Quiz"),
        "drill_mode":    (drill._clear,       drill_h,       "Drill"),
        "scene_mode":    (roleplay._clear,    roleplay_h,    "Roleplay"),
    })
    app.add_handler(CommandHandler(switcher.ENTRY_COMMANDS, switcher.handle), group=-1)

    app.add_handler(assessment_h)
    app.add_handler(practice_h)
    app.add_handler(daily_h)
    app.add_handler(quiz_h)
    app.add_handler(drill_h)
    app.add_handler(roleplay_h)

    # Global /cancel — only fires when no conversation is active (the assessment
    # and practice handlers consume /cancel/​/stop themselves while running).
    app.add_handler(CommandHandler("cancel", start.cancel_cmd))

    app.add_handler(CommandHandler("review", practice.review))
    app.add_handler(CommandHandler("weekly", report.weekly_report))
    app.add_handler(CommandHandler("remind", reminders.remind))
    app.add_handler(CommandHandler("topic", conversation.topic))
    app.add_handler(CommandHandler("english", conversation.english))
    app.add_handler(CommandHandler("spanish", conversation.spanish))
    app.add_handler(CommandHandler("corrections", conversation.corrections))
    app.add_handler(CommandHandler("summary", conversation.summary))
    app.add_handler(CommandHandler("status", conversation.status))
    app.add_handler(CommandHandler("backend", conversation.backend))

    # Documents (Phase 4).
    app.add_handler(CommandHandler("docs", documents.docs))
    app.add_handler(CommandHandler("learn", documents.learn))
    app.add_handler(CommandHandler("docfocus", documents.docfocus))
    app.add_handler(MessageHandler(filters.Document.ALL, documents.handle_document))

    # The Impostor game.
    for handler in game.build_handlers():
        app.add_handler(handler)

    # Subscription and top-up payments (F-16, F-21).
    app.add_handler(CommandHandler("subscribe", payments.subscribe_handler))
    app.add_handler(CommandHandler("topup", payments.topup_handler))
    # Dual-payment choice buttons (subscribe:stars / subscribe:card).
    app.add_handler(
        CallbackQueryHandler(payments.on_subscribe_stars, pattern=r"^subscribe:stars$")
    )
    app.add_handler(
        CallbackQueryHandler(payments.on_subscribe_card, pattern=r"^subscribe:card$")
    )
    app.add_handler(
        CallbackQueryHandler(payments.on_topup_pack_pick, pattern=r"^topup:")
    )
    app.add_handler(PreCheckoutQueryHandler(payments.pre_checkout_handler))
    app.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, payments.payment_confirmed_handler)
    )
    # Limit-hit buttons: pay:subscribe → /subscribe, pay:topup → /topup.
    app.add_handler(
        CallbackQueryHandler(payments.subscribe_handler, pattern=r"^pay:subscribe$")
    )
    app.add_handler(
        CallbackQueryHandler(payments.topup_handler, pattern=r"^pay:topup$")
    )

    # "Free features" buttons shown on credit/quota exhaustion messages.
    app.add_handler(
        CallbackQueryHandler(conversation.on_free_feature_tap, pattern=r"^free:")
    )

    # Inline action buttons attached to corrected replies (📖/➕/🎯).
    app.add_handler(
        CallbackQueryHandler(conversation.on_correction_action, pattern=r"^corr:")
    )
    # Correction level picker buttons.
    app.add_handler(
        CallbackQueryHandler(conversation.on_corrections_pick, pattern=r"^setcorr:")
    )

    # Any non-command text: media task submission (if pending) then tutor chat.
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, conversation.chat)
    )

    return app


# The native Telegram command menu (the ≡ button), curated and ordered by
# expected frequency. Debug commands (/status, /backend) are intentionally
# omitted. Order is static for now; usage-sorted ordering is future work.
MENU_COMMANDS_GERMAN = [
    BotCommand("course", "📚 Englisch-Kurs — Lektion + Übungen"),
    BotCommand("browse", "Alle Kurseinheiten durchsuchen"),
    BotCommand("leveltest", "Ganzes Level testen"),
    BotCommand("practice", "Vokabeln üben (Spaced Repetition)"),
    BotCommand("flashcards", "Karteikarten üben (wie /practice)"),
    BotCommand("daily", "Tägliche Mini-Challenge (3 Aufgaben)"),
    BotCommand("quiz", "Schnell-Quiz auf schwache Skills"),
    BotCommand("drill", "Gezieltes Themen-Drill (10 Übungen)"),
    BotCommand("classtopic", "Aktuelles Klassen-Thema anzeigen"),
    BotCommand("roleplay", "Roleplay-Szene auf Deutsch"),
    BotCommand("weekly", "Wöchentlicher Lernbericht"),
    BotCommand("test", "Einstufungstest starten"),
    BotCommand("profile", "Dein Lernprofil ansehen"),
    BotCommand("mybudget", "Verbleibende Credits heute"),
    BotCommand("subscribe", "Abonnement (mehr Nachrichten)"),
    BotCommand("topup", "Nachrichten-Paket kaufen"),
    BotCommand("pronounce", "Aussprache als Sprachnachricht"),
    BotCommand("review", "Übungs-Statistik & Streak"),
    BotCommand("topic", "Gespräch auf ein Thema lenken"),
    BotCommand("summary", "Deine Fehler auswerten"),
    BotCommand("corrections", "Korrekturen ein/aus"),
    BotCommand("docs", "Deine Dokumente"),
    BotCommand("remind", "Tägliche Erinnerung setzen"),
    BotCommand("impostor", "🎮 Play The Impostor with friends"),
    BotCommand("start", "Willkommen / neu starten"),
    BotCommand("help", "Alle Befehle anzeigen"),
]

MENU_COMMANDS_ENGLISH = [
    BotCommand("course", "📚 English course — lesson + exercises"),
    BotCommand("browse", "Browse all course units"),
    BotCommand("leveltest", "Test yourself on an entire level"),
    BotCommand("practice", "Vocabulary flashcards (Spaced Repetition)"),
    BotCommand("flashcards", "Flashcard practice (same as /practice)"),
    BotCommand("daily", "Daily challenge (3 short exercises)"),
    BotCommand("quiz", "Quick quiz on your weakest skills"),
    BotCommand("drill", "Focused topic drill (10 exercises)"),
    BotCommand("classtopic", "Show current class topic"),
    BotCommand("roleplay", "Roleplay conversation scene"),
    BotCommand("weekly", "Weekly progress report"),
    BotCommand("test", "Start adaptive placement test"),
    BotCommand("profile", "Your learning profile"),
    BotCommand("mybudget", "Remaining credits today"),
    BotCommand("subscribe", "Subscription (more messages)"),
    BotCommand("topup", "Buy a message pack"),
    BotCommand("pronounce", "Hear pronunciation as voice note"),
    BotCommand("review", "Practice stats & streak"),
    BotCommand("topic", "Steer conversation to a topic"),
    BotCommand("summary", "Review your recent mistakes"),
    BotCommand("corrections", "Corrections on/off"),
    BotCommand("docs", "Your documents"),
    BotCommand("remind", "Set a daily reminder"),
    BotCommand("impostor", "🎮 Play The Impostor with friends"),
    BotCommand("start", "Welcome / restart"),
    BotCommand("help", "Show all commands"),
]

MENU_COMMANDS = (
    MENU_COMMANDS_ENGLISH if config.BOT_LANGUAGE == "english" else MENU_COMMANDS_GERMAN
)


async def _expire_subscriptions(context) -> None:  # noqa: ANN001
    from db.repo import clear_expired_subscriptions
    n = clear_expired_subscriptions()
    if n:
        logger.info("Cleared %d expired subscription(s).", n)


async def _post_init(app: Application) -> None:
    """Startup hooks: publish the command menu; probe Ollama; restore reminders."""
    await app.bot.set_my_commands(MENU_COMMANDS)
    await ollama_client.health_check()
    await reminders.reschedule_all(app)
    # Daily job to clear expired subscriptions (runs every 6 hours).
    app.job_queue.run_repeating(_expire_subscriptions, interval=6 * 3600, first=60)


def main() -> None:
    init_db()
    logger.info("Database ready.")
    app = build_application()
    app.post_init = _post_init
    logger.info("Starting Karly (long polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
