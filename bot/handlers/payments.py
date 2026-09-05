"""Payment handlers for subscriptions (PayPal + Stars) and top-up packs (F-16, F-21)."""
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

_PAYLOAD_SUBSCRIBE = "karly_subscribe_30d"
_PAYLOAD_TOPUP_PREFIX = "karly_topup_"  # + pack index (0/1/2)


@require_auth
async def subscribe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/subscribe — show dual-payment choice (PayPal card or Telegram Stars)."""
    user = get_user_by_telegram_id(update.effective_user.id)
    en = user and getattr(user, "learning_mode", "german") == "english"

    if user and user.subscribed:
        expires = (
            user.subscription_expires_at.strftime("%Y-%m-%d")
            if user.subscription_expires_at
            else "?"
        )
        if en:
            await update.effective_message.reply_text(
                f"✅ You already have an active subscription (until {expires})."
            )
        else:
            await update.effective_message.reply_text(
                f"✅ Du hast schon ein aktives Abonnement (bis {expires})."
            )
        return

    days = config.SUBSCRIBE_DAYS
    stars = config.SUBSCRIBE_PRICE_STARS
    usd = config.SUBSCRIBE_PRICE_USD_CENTS / 100  # e.g. 4.99

    card_available = bool(config.PAYMENT_PROVIDER_TOKEN)

    if en:
        text = (
            f"🎓 *Karly subscription — {days} days*\n\n"
            f"Get *{config.SESSION_CAP_SUBSCRIBER} messages per session* "
            f"and *{config.WEEK_CAP_SUBSCRIBER} per week*.\n\n"
        )
        if card_available:
            text += (
                f"💳 *Card — ${usd:.2f}/month* ← better deal\n"
                f"⭐ *Telegram Stars — {stars} ⭐/month*\n\n"
                "Card payments via PayPal cost less in fees. "
                "Stars work too — the choice is yours."
            )
            buttons = [
                [InlineKeyboardButton(f"💳 Pay ${usd:.2f} by card", callback_data="subscribe:card")],
                [InlineKeyboardButton(f"⭐ Pay {stars} Stars", callback_data="subscribe:stars")],
            ]
        else:
            text += f"⭐ *{stars} Telegram Stars* for {days} days."
            buttons = [
                [InlineKeyboardButton(f"⭐ Pay {stars} Stars", callback_data="subscribe:stars")],
            ]
    else:
        text = (
            f"🎓 *Karly-Abonnement — {days} Tage*\n\n"
            f"*{config.SESSION_CAP_SUBSCRIBER} Nachrichten pro Session* "
            f"und *{config.WEEK_CAP_SUBSCRIBER} pro Woche*.\n\n"
        )
        if card_available:
            text += (
                f"💳 *Karte — ${usd:.2f}/Monat* ← besser\n"
                f"⭐ *Telegram Stars — {stars} ⭐/Monat*\n\n"
                "Kartenzahlung via PayPal hat niedrigere Gebühren."
            )
            buttons = [
                [InlineKeyboardButton(f"💳 {usd:.2f} $ per Karte zahlen", callback_data="subscribe:card")],
                [InlineKeyboardButton(f"⭐ {stars} Stars zahlen", callback_data="subscribe:stars")],
            ]
        else:
            text += f"⭐ *{stars} Telegram Stars* für {days} Tage."
            buttons = [
                [InlineKeyboardButton(f"⭐ {stars} Stars zahlen", callback_data="subscribe:stars")],
            ]

    await update.effective_message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def _send_stars_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a Telegram Stars subscription invoice."""
    user = get_user_by_telegram_id(update.effective_user.id)
    en = user and getattr(user, "learning_mode", "german") == "english"
    stars = config.SUBSCRIBE_PRICE_STARS
    days = config.SUBSCRIBE_DAYS

    title = "Karly Subscription" if en else "Karly Abonnement"
    description = (
        f"{days}-day subscription — {config.SESSION_CAP_SUBSCRIBER} messages/session, "
        f"{config.WEEK_CAP_SUBSCRIBER}/week."
        if en else
        f"{days}-Tage-Abo — {config.SESSION_CAP_SUBSCRIBER} Nachrichten/Session, "
        f"{config.WEEK_CAP_SUBSCRIBER}/Woche."
    )

    msg = update.callback_query.message if update.callback_query else update.effective_message
    await msg.reply_invoice(
        title=title,
        description=description,
        payload=_PAYLOAD_SUBSCRIBE,
        provider_token="",  # Stars require an empty token
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=stars)],
    )


async def _send_card_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a PayPal card subscription invoice."""
    user = get_user_by_telegram_id(update.effective_user.id)
    en = user and getattr(user, "learning_mode", "german") == "english"
    cents = config.SUBSCRIBE_PRICE_USD_CENTS
    days = config.SUBSCRIBE_DAYS

    title = "Karly Subscription" if en else "Karly Abonnement"
    description = (
        f"{days}-day subscription — {config.SESSION_CAP_SUBSCRIBER} messages/session, "
        f"{config.WEEK_CAP_SUBSCRIBER}/week."
        if en else
        f"{days}-Tage-Abo — {config.SESSION_CAP_SUBSCRIBER} Nachrichten/Session, "
        f"{config.WEEK_CAP_SUBSCRIBER}/Woche."
    )

    msg = update.callback_query.message if update.callback_query else update.effective_message
    await msg.reply_invoice(
        title=title,
        description=description,
        payload=_PAYLOAD_SUBSCRIBE,
        provider_token=config.PAYMENT_PROVIDER_TOKEN,
        currency="USD",
        prices=[LabeledPrice(label=title, amount=cents)],
    )


@require_auth
async def on_subscribe_stars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: user chose Stars payment."""
    await update.callback_query.answer()
    await _send_stars_invoice(update, context)


@require_auth
async def on_subscribe_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: user chose card (PayPal) payment."""
    await update.callback_query.answer()
    if not config.PAYMENT_PROVIDER_TOKEN:
        await update.callback_query.message.reply_text(
            "Card payments are not set up yet. Please use Stars for now."
        )
        return
    await _send_card_invoice(update, context)


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
    await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


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
    """Answer all pre-checkout queries with ok."""
    await update.pre_checkout_query.answer(ok=True)


async def payment_confirmed_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle successful_payment — works for both PayPal and Stars invoices."""
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
    amount = payment.total_amount
    currency = payment.currency  # "XTR" or "USD"

    if payload == _PAYLOAD_SUBSCRIBE:
        days = config.SUBSCRIBE_DAYS
        set_subscribed(user.id, days=days)
        stars_amount = amount if currency == "XTR" else None
        record_payment(
            user.id,
            kind="subscription",
            stars_amount=stars_amount,
            telegram_charge_id=charge_id,
        )
        logger.info(
            "Subscription activated user_id=%s currency=%s amount=%d",
            user.id, currency, amount,
        )
        if en:
            await message.reply_text(
                f"🎉 *Subscribed!* You now have *{config.SESSION_CAP_SUBSCRIBER} messages per session* "
                f"and *{config.WEEK_CAP_SUBSCRIBER} per week* for the next {days} days.\n\n"
                "Thank you for supporting Karly! 🙏",
                parse_mode="Markdown",
            )
        else:
            await message.reply_text(
                f"🎉 *Abonniert!* Du hast jetzt *{config.SESSION_CAP_SUBSCRIBER} Nachrichten pro Session* "
                f"und *{config.WEEK_CAP_SUBSCRIBER} pro Woche* für die nächsten {days} Tage.\n\n"
                "Danke, dass du Karly unterstützt! 🙏",
                parse_mode="Markdown",
            )

    elif payload.startswith(_PAYLOAD_TOPUP_PREFIX):
        pack_idx = int(payload[len(_PAYLOAD_TOPUP_PREFIX):])
        if pack_idx < len(config.TOPUP_PACKS):
            pack_label, msgs, _ = config.TOPUP_PACKS[pack_idx]
            add_topup_credits(user.id, msgs)
            record_payment(
                user.id,
                kind="topup",
                stars_amount=amount if currency == "XTR" else None,
                credits_purchased=msgs,
                telegram_charge_id=charge_id,
            )
            logger.info("Top-up %d messages user_id=%s", msgs, user.id)
            if en:
                await message.reply_text(
                    f"✅ *{msgs} extra messages added* to your account. They never expire.",
                    parse_mode="Markdown",
                )
            else:
                await message.reply_text(
                    f"✅ *{msgs} extra Nachrichten* wurden deinem Konto gutgeschrieben.",
                    parse_mode="Markdown",
                )
