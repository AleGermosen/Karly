"""Payment handlers for Telegram Stars subscriptions and top-up packs (F-16, F-21)."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import ContextTypes

import config
from bot.middleware import require_auth
from db.repo import (
    add_topup_credits,
    get_user_by_telegram_id,
    record_payment,
    set_subscribed,
)

logger = logging.getLogger(__name__)

# Payload prefixes used to distinguish invoice types in pre-checkout/confirmed.
_PAYLOAD_SUBSCRIBE = "karly_subscribe_30d"
_PAYLOAD_TOPUP_PREFIX = "karly_topup_"  # + pack index (0/1/2)


@require_auth
async def subscribe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/subscribe — send a Telegram Stars invoice for a 30-day subscription."""
    user = get_user_by_telegram_id(update.effective_user.id)
    en = user and getattr(user, "learning_mode", "german") == "english"

    if user and user.subscribed:
        if en:
            await update.effective_message.reply_text(
                "✅ You already have an active subscription! "
                f"It runs until {user.subscription_expires_at.strftime('%Y-%m-%d') if user.subscription_expires_at else 'unknown'}."
            )
        else:
            await update.effective_message.reply_text(
                "✅ Du hast schon ein aktives Abonnement! "
                f"Es läuft bis {user.subscription_expires_at.strftime('%Y-%m-%d') if user.subscription_expires_at else 'unbekannt'}."
            )
        return

    stars = config.SUBSCRIBE_PRICE_STARS
    days = config.SUBSCRIBE_DAYS
    if en:
        title = "Karly Subscription"
        description = (
            f"{days}-day subscription — {config.SESSION_CAP_SUBSCRIBER} messages per session, "
            f"{config.WEEK_CAP_SUBSCRIBER} per week."
        )
    else:
        title = "Karly Abonnement"
        description = (
            f"{days}-Tage-Abo — {config.SESSION_CAP_SUBSCRIBER} Nachrichten pro Session, "
            f"{config.WEEK_CAP_SUBSCRIBER} pro Woche."
        )

    await update.effective_message.reply_invoice(
        title=title,
        description=description,
        payload=_PAYLOAD_SUBSCRIBE,
        provider_token="",  # Stars require an empty token.
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=stars)],
    )


@require_auth
async def topup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/topup — show top-up pack options as inline buttons."""
    user = get_user_by_telegram_id(update.effective_user.id)
    en = user and getattr(user, "learning_mode", "german") == "english"

    buttons = []
    for i, (label, msgs, stars) in enumerate(config.TOPUP_PACKS):
        if en:
            btn_label = f"{label}: {msgs} messages — {stars} ⭐"
        else:
            btn_label = f"{label}: {msgs} Nachrichten — {stars} ⭐"
        buttons.append([InlineKeyboardButton(btn_label, callback_data=f"topup:{i}")])

    kb = InlineKeyboardMarkup(buttons)
    if en:
        text = (
            "➕ *Buy extra messages*\n\n"
            "Top-up credits never expire and are used after your session/weekly allowance runs out.\n\n"
            "Choose a pack:"
        )
    else:
        text = (
            "➕ *Nachrichten kaufen*\n\n"
            "Top-up-Credits verfallen nie und werden erst genutzt, wenn dein Session-/Wochenkontingent aufgebraucht ist.\n\n"
            "Pack auswählen:"
        )
    await update.effective_message.reply_text(text, reply_markup=kb)


@require_auth
async def on_topup_pack_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the top-up pack selection buttons."""
    query = update.callback_query
    await query.answer()
    pack_idx = int(query.data.split(":")[1])
    if pack_idx >= len(config.TOPUP_PACKS):
        return

    user = get_user_by_telegram_id(update.effective_user.id)
    en = user and getattr(user, "learning_mode", "german") == "english"
    label, msgs, stars = config.TOPUP_PACKS[pack_idx]

    if en:
        title = f"Karly Top-up — {label}"
        description = f"{msgs} extra messages (never expire)."
    else:
        title = f"Karly Top-up — {label}"
        description = f"{msgs} extra Nachrichten (verfallen nie)."

    await query.message.reply_invoice(
        title=title,
        description=description,
        payload=f"{_PAYLOAD_TOPUP_PREFIX}{pack_idx}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=stars)],
    )


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer all pre-checkout queries with ok (validation already done at send time)."""
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def payment_confirmed_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle successful_payment — activate subscription or add top-up credits."""
    message = update.effective_message
    if message is None or message.successful_payment is None:
        return

    payment = message.successful_payment
    user = get_user_by_telegram_id(update.effective_user.id)
    if user is None:
        return

    en = getattr(user, "learning_mode", "german") == "english"
    charge_id = payment.telegram_payment_charge_id
    payload = payment.invoice_payload
    stars = payment.total_amount

    if payload == _PAYLOAD_SUBSCRIBE:
        days = config.SUBSCRIBE_DAYS
        set_subscribed(user.id, days=days)
        record_payment(user.id, kind="subscription", stars_amount=stars, telegram_charge_id=charge_id)
        logger.info("Subscription activated for user_id=%s (%d Stars)", user.id, stars)
        if en:
            await message.reply_text(
                f"🎉 *Subscribed!* You now have *{config.SESSION_CAP_SUBSCRIBER} messages per session* "
                f"and *{config.WEEK_CAP_SUBSCRIBER} per week* for the next {days} days.\n\n"
                "Thank you for supporting Karly! 🙏"
            )
        else:
            await message.reply_text(
                f"🎉 *Abonniert!* Du hast jetzt *{config.SESSION_CAP_SUBSCRIBER} Nachrichten pro Session* "
                f"und *{config.WEEK_CAP_SUBSCRIBER} pro Woche* für die nächsten {days} Tage.\n\n"
                "Danke, dass du Karly unterstützt! 🙏"
            )

    elif payload.startswith(_PAYLOAD_TOPUP_PREFIX):
        pack_idx = int(payload[len(_PAYLOAD_TOPUP_PREFIX):])
        if pack_idx < len(config.TOPUP_PACKS):
            pack_label, msgs, _ = config.TOPUP_PACKS[pack_idx]
            add_topup_credits(user.id, msgs)
            record_payment(user.id, kind="topup", stars_amount=stars, credits_purchased=msgs, telegram_charge_id=charge_id)
            logger.info("Top-up %d messages for user_id=%s (%d Stars)", msgs, user.id, stars)
            if en:
                await message.reply_text(
                    f"✅ *{msgs} extra messages added* to your account. They never expire. "
                    "They'll kick in once your session/weekly allowance runs out."
                )
            else:
                await message.reply_text(
                    f"✅ *{msgs} extra Nachrichten* wurden deinem Konto gutgeschrieben. "
                    "Sie verfallen nie und werden genutzt, wenn dein Session-/Wochenkontingent erschöpft ist."
                )
