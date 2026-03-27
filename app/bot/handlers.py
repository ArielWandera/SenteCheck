"""
handlers.py — All Telegram bot command and callback handlers.

Database access pattern: each handler pulls the AsyncSessionLocal factory
from context.application.bot_data["session_factory"] and opens a short-lived
session for its work. This keeps handlers stateless and testable.
"""
from datetime import datetime, timezone
from decimal import Decimal

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from sqlalchemy import select

from app.bot.keyboards import (
    consent_keyboard,
    delete_confirm_keyboard,
    deposit_classification_keyboard,
    withdrawal_classification_keyboard,
)
from app.models.bet import RESULT_LOSS, RESULT_PENDING, RESULT_WIN, Bet
from app.models.known_merchant import KnownMerchant
from app.models.transaction import (
    CATEGORY_BET_DEPOSIT,
    CATEGORY_BET_WITHDRAWAL,
    CATEGORY_OTHER_INCOME,
    CATEGORY_OTHER_PAYMENT,
    DIRECTION_IN,
    DIRECTION_OUT,
    Transaction,
)
from app.models.user import User
from app.services import dashboard_service, merchant_service, transaction_service, user_service
from app.utils.rate_limiter import bot_limiter

# ── Consent message (verbatim from CLAUDE.md) ───────────────────────────────

CONSENT_TEXT = """👋 <b>Welcome to SenteCheck.</b>

Before we begin, please read this carefully.

📋 <b>WHAT WE COLLECT</b>
SenteCheck reads mobile money SMS on your phone to track your betting spend.
We only process SMS that contain mobile money keywords (UGX, MTN, Airtel Money).
We never read personal messages, WhatsApp, or any non-financial SMS.

💾 <b>WHAT WE STORE</b>
• Transaction amounts and merchant names
• Your classified bet deposits and withdrawals
• Your Telegram ID to send you updates
• The original SMS text, stored encrypted

🔒 <b>HOW WE PROTECT IT</b>
• All data is encrypted at rest
• We use HTTPS for all data transfer
• Your data is never sold or shared with anyone
• Only you can access your data

🗑️ <b>YOUR RIGHTS</b>
• You can delete all your data at any time with /deleteaccount
• You can view everything we have stored with /mydata
• You can withdraw consent at any time by deleting your account

⚖️ <b>LEGAL BASIS</b>
SenteCheck operates under Uganda's Data Protection and Privacy Act 2019.
By continuing, you consent to the collection and processing of your mobile money SMS data for the purpose of personal finance tracking.

Do you agree to these terms?"""

ONBOARDING_TEXT = """✅ <b>Consent recorded. Welcome to SenteCheck!</b>

Your Telegram ID is: <code>{telegram_id}</code>
<i>(You'll need this when connecting the Android app)</i>

<b>Next steps:</b>
1. Install the SenteCheck Android app
2. Open the app and enter your Telegram ID above
3. Press <b>Connect</b>

Once connected, every MTN/Airtel mobile money SMS will be automatically tracked. Unrecognised merchants will prompt a quick Yes/No here on Telegram.

Type /help to see all available commands."""

HELP_TEXT = """<b>SenteCheck Commands</b>

/summary — Full P&amp;L overview: deposits, withdrawals, win rate, bankroll
/losses — Loss dashboard
/wins — Win dashboard
/history [n] — Last <i>n</i> transactions (default 10)
/bankroll set [amount] — Set your monthly bankroll
/bankroll status — Check bankroll health and recommended stake
/bet [stake] [win/loss] [return] — Manually log a completed bet
/merchants — List all known merchant classifications
/addmerchant [NAME] [bet/other] — Manually classify a merchant name
/mydata — View everything we have stored about you
/deleteaccount — Permanently delete your account and all data
/help — Show this message"""


# ── Helpers ─────────────────────────────────────────────────────────────────

def _session_factory(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["session_factory"]


async def _get_registered_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> User | None:
    """
    Returns the User row if the sender is registered, has given consent,
    and is within the per-user rate limit (30 commands/minute).
    Sends an appropriate error message and returns None otherwise.
    """
    telegram_id = update.effective_user.id

    # Rate limit: 30 bot commands per user per minute
    if not bot_limiter.is_allowed(str(telegram_id)):
        await update.effective_message.reply_text(
            "⏳ You're sending commands too quickly. Please wait a moment."
        )
        return None

    factory = _session_factory(context)
    async with factory() as db:
        user = await user_service.get_by_telegram_id(db, telegram_id)

    if not user or not user.consent_given:
        await update.effective_message.reply_text(
            "You're not registered yet. Send /start to get started."
        )
        return None
    return user


# ── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    factory = _session_factory(context)

    async with factory() as db:
        user = await user_service.get_by_telegram_id(db, telegram_id)

    if user and user.consent_given:
        await update.message.reply_text(
            "You're already connected to SenteCheck. Type /help for all commands."
        )
        return

    await update.message.reply_text(
        CONSENT_TEXT,
        reply_markup=consent_keyboard(),
        parse_mode=ParseMode.HTML,
    )


# ── Consent callback ──────────────────────────────────────────────────────────

async def consent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    action = query.data.split(":")[1]  # "agree" or "disagree"

    if action == "disagree":
        await query.edit_message_text(
            "No problem. SenteCheck requires SMS access to work.\n"
            "You can come back any time if you change your mind."
        )
        return

    # action == "agree"
    telegram_id = update.effective_user.id
    factory = _session_factory(context)

    async with factory() as db:
        # Guard against double-tap: only create if not already registered
        existing = await user_service.get_by_telegram_id(db, telegram_id)
        if not existing:
            user = User(
                telegram_id=telegram_id,
                username=update.effective_user.username,
                consent_given=True,
                consent_given_at=datetime.now(timezone.utc),
                consent_version="v1",
            )
            db.add(user)
            await db.commit()

    await query.edit_message_text(
        ONBOARDING_TEXT.format(telegram_id=telegram_id),
        parse_mode=ParseMode.HTML,
    )


# ── /help ────────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


# ── Merchant classification callback ─────────────────────────────────────────
#
# Callback data format: "classify:{transaction_id}:{category}"
# Categories: bet_deposit | other_payment | bet_withdrawal | other_income

async def classification_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    _, txn_id_str, category = query.data.split(":")
    txn_id = int(txn_id_str)
    telegram_id = update.effective_user.id
    factory = _session_factory(context)

    async with factory() as db:
        user = await user_service.get_by_telegram_id(db, telegram_id)
        if not user:
            await query.edit_message_text("Session expired. Please send /start again.")
            return

        result = await db.execute(
            select(Transaction).where(
                Transaction.id == txn_id,
                Transaction.user_id == user.id,
            )
        )
        txn = result.scalar_one_or_none()

        if not txn:
            await query.edit_message_text("Transaction not found.")
            return

        # Update the transaction category
        txn.category = category

        # Record the merchant so future SMS from them are auto-classified
        if txn.merchant_name:
            await merchant_service.upsert_merchant(
                db,
                merchant_name=txn.merchant_name,
                direction=txn.direction,
                category=category,
                user_id=user.id,
            )

        await db.commit()

    # Build confirmation message
    label_map = {
        CATEGORY_BET_DEPOSIT: "logged as a bet deposit",
        CATEGORY_OTHER_PAYMENT: "logged as other payment",
        CATEGORY_BET_WITHDRAWAL: "logged as a bet withdrawal",
        CATEGORY_OTHER_INCOME: "logged as other income",
    }
    label = label_map.get(category, "classified")
    merchant = txn.merchant_name or "that merchant"

    await query.edit_message_text(
        f"Got it. UGX {txn.amount:,.0f} → {merchant} has been {label}.\n"
        f"Future payments to <b>{merchant}</b> will be auto-classified.",
        parse_mode=ParseMode.HTML,
    )


# ── /summary ─────────────────────────────────────────────────────────────────

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_registered_user(update, context)
    if not user:
        return

    factory = _session_factory(context)
    async with factory() as db:
        stats = await dashboard_service.get_summary(db, user.id)
        br_status = await dashboard_service.get_bankroll_status(db, user.id, user.bankroll)

    pnl_sign = "+" if stats.net_pnl >= 0 else ""
    pnl_line = f"{pnl_sign}UGX {stats.net_pnl:,.0f}"

    wr_line = f"{stats.win_rate}%" if stats.win_rate is not None else "No completed bets yet"

    br_line = ""
    if br_status:
        br_line = (
            f"\n\n💰 <b>Bankroll</b>\n"
            f"Monthly budget: UGX {br_status.bankroll:,.0f}\n"
            f"Used this month: UGX {br_status.deposited_this_month:,.0f} "
            f"({br_status.pct_used}%)\n"
            f"Remaining: UGX {br_status.remaining:,.0f}"
        )

    text = (
        f"📊 <b>Your SenteCheck Summary</b>\n\n"
        f"💸 <b>Deposited to betting sites:</b> UGX {stats.total_deposited:,.0f}\n"
        f"💰 <b>Withdrawn from betting sites:</b> UGX {stats.total_withdrawn:,.0f}\n"
        f"📉 <b>Net P&amp;L:</b> {pnl_line}\n\n"
        f"🎲 <b>Bets logged:</b> {stats.total_bets}\n"
        f"✅ <b>Wins:</b> {stats.wins}\n"
        f"❌ <b>Losses:</b> {stats.losses}\n"
        f"⏳ <b>Pending:</b> {stats.pending}\n"
        f"🎯 <b>Win rate:</b> {wr_line}"
        f"{br_line}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── /losses ───────────────────────────────────────────────────────────────────

async def losses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_registered_user(update, context)
    if not user:
        return

    factory = _session_factory(context)
    async with factory() as db:
        stats = await dashboard_service.get_losses(db, user.id)

    if stats.count == 0:
        await update.message.reply_text("No losses logged yet. Keep it that way! 🙏")
        return

    recent_lines = "\n".join(
        f"• UGX {b.stake:,.0f}"
        + (f" — {b.platform}" if b.platform else "")
        + f" — {b.created_at.strftime('%d %b')}"
        for b in stats.recent
    )

    text = (
        f"📉 <b>Your Loss Dashboard</b>\n\n"
        f"Total staked and lost: <b>UGX {stats.total_staked:,.0f}</b>\n"
        f"Number of losses: {stats.count}\n"
        f"Biggest single loss: UGX {stats.biggest_loss:,.0f}\n\n"
        f"<b>Recent losses:</b>\n{recent_lines}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── /wins ─────────────────────────────────────────────────────────────────────

async def wins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_registered_user(update, context)
    if not user:
        return

    factory = _session_factory(context)
    async with factory() as db:
        stats = await dashboard_service.get_wins(db, user.id)

    if stats.count == 0:
        await update.message.reply_text("No wins logged yet. Log your bets with /bet!")
        return

    recent_lines = "\n".join(
        f"• +UGX {b.net:,.0f} profit"
        + (f" — {b.platform}" if b.platform else "")
        + f" — {b.created_at.strftime('%d %b')}"
        for b in stats.recent
    )

    text = (
        f"📈 <b>Your Win Dashboard</b>\n\n"
        f"Total profit from wins: <b>UGX {stats.total_profit:,.0f}</b>\n"
        f"Number of wins: {stats.count}\n"
        f"Biggest single win profit: UGX {stats.biggest_profit:,.0f}\n\n"
        f"<b>Recent wins:</b>\n{recent_lines}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── /history ──────────────────────────────────────────────────────────────────

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_registered_user(update, context)
    if not user:
        return

    # Optional argument: /history 20
    limit = 10
    if context.args:
        try:
            limit = max(1, min(int(context.args[0]), 50))
        except ValueError:
            pass

    factory = _session_factory(context)
    async with factory() as db:
        txns = await dashboard_service.get_history(db, user.id, limit)

    if not txns:
        await update.message.reply_text("No transactions recorded yet.")
        return

    direction_icon = {DIRECTION_OUT: "💸", DIRECTION_IN: "💰"}
    lines = []
    for t in txns:
        icon = direction_icon.get(t.direction, "•")
        merchant = t.merchant_name or "—"
        category = t.category.replace("_", " ")
        lines.append(
            f"{icon} <b>UGX {t.amount:,.0f}</b> | {merchant} | {category} | "
            f"{t.created_at.strftime('%d %b %H:%M')}"
        )

    text = f"🕐 <b>Last {len(txns)} transactions</b>\n\n" + "\n".join(lines)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── /bankroll ─────────────────────────────────────────────────────────────────

_STATUS_ICON = {
    "healthy": "✅",
    "warning": "⚠️",
    "critical": "🔴",
    "exhausted": "🚫",
}


async def bankroll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_registered_user(update, context)
    if not user:
        return

    args = context.args or []

    # /bankroll set 100000
    if args and args[0].lower() == "set":
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: /bankroll set [amount]\nExample: /bankroll set 100000"
            )
            return
        try:
            amount = Decimal(args[1].replace(",", ""))
            if amount <= 0:
                raise ValueError
        except (ValueError, Exception):
            await update.message.reply_text("Please provide a valid positive amount.")
            return

        factory = _session_factory(context)
        async with factory() as db:
            db_user = await user_service.get_by_telegram_id(db, user.telegram_id)
            db_user.bankroll = amount
            await db.commit()

        await update.message.reply_text(
            f"✅ Monthly bankroll set to <b>UGX {amount:,.0f}</b>.\n"
            f"Use /bankroll status to track your spending.",
            parse_mode=ParseMode.HTML,
        )
        return

    # /bankroll status  (also default when no sub-command given)
    factory = _session_factory(context)
    async with factory() as db:
        fresh_user = await user_service.get_by_telegram_id(db, user.telegram_id)
        br = await dashboard_service.get_bankroll_status(db, fresh_user.id, fresh_user.bankroll)

    if not br:
        await update.message.reply_text(
            "You haven't set a bankroll yet.\n"
            "Use /bankroll set [amount] to set your monthly betting budget."
        )
        return

    icon = _STATUS_ICON.get(br.status, "•")
    now = datetime.now(timezone.utc)

    text = (
        f"💰 <b>Bankroll Status — {now.strftime('%B %Y')}</b>\n\n"
        f"Monthly budget: UGX {br.bankroll:,.0f}\n"
        f"Deposited this month: UGX {br.deposited_this_month:,.0f} ({br.pct_used}%)\n"
        f"Remaining: <b>UGX {br.remaining:,.0f}</b>\n\n"
        f"{icon} Status: <b>{br.status.upper()}</b>\n"
        f"Recommended stake: UGX {br.recommended_stake:,.0f} (2% of remaining)"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── /bet ──────────────────────────────────────────────────────────────────────

_BET_USAGE = (
    "Usage:\n"
    "/bet [stake] [win/loss] [return]\n\n"
    "Examples:\n"
    "/bet 5000 loss\n"
    "/bet 5000 win 15000\n"
    "/bet 5000 pending"
)


async def bet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_registered_user(update, context)
    if not user:
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(_BET_USAGE)
        return

    try:
        stake = Decimal(args[0].replace(",", ""))
        if stake <= 0:
            raise ValueError
    except (ValueError, Exception):
        await update.message.reply_text(f"Invalid stake amount.\n\n{_BET_USAGE}")
        return

    result_raw = args[1].lower()
    if result_raw not in (RESULT_WIN, RESULT_LOSS, RESULT_PENDING):
        await update.message.reply_text(
            f"Result must be win, loss, or pending.\n\n{_BET_USAGE}"
        )
        return

    return_amount = None
    if result_raw == RESULT_WIN:
        if len(args) < 3:
            await update.message.reply_text(
                "Please provide the return amount for a win.\n\n" + _BET_USAGE
            )
            return
        try:
            return_amount = Decimal(args[2].replace(",", ""))
            if return_amount <= 0:
                raise ValueError
        except (ValueError, Exception):
            await update.message.reply_text("Invalid return amount.")
            return

    platform = " ".join(args[3:]) if len(args) > 3 else None

    factory = _session_factory(context)
    async with factory() as db:
        new_bet = Bet(
            user_id=user.id,
            stake=stake,
            result=result_raw,
            return_amount=return_amount,
            platform=platform,
        )
        db.add(new_bet)
        await db.commit()

    if result_raw == RESULT_WIN:
        profit = return_amount - stake
        msg = (
            f"✅ Win logged!\n"
            f"Stake: UGX {stake:,.0f}\n"
            f"Return: UGX {return_amount:,.0f}\n"
            f"Profit: <b>+UGX {profit:,.0f}</b>"
        )
    elif result_raw == RESULT_LOSS:
        msg = (
            f"❌ Loss logged.\n"
            f"Stake lost: <b>UGX {stake:,.0f}</b>"
        )
    else:
        msg = f"⏳ Pending bet logged. Stake: UGX {stake:,.0f}"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


# ── /merchants ────────────────────────────────────────────────────────────────

_CATEGORY_LABEL = {
    CATEGORY_BET_DEPOSIT: "bet deposit",
    CATEGORY_BET_WITHDRAWAL: "bet withdrawal",
    "other_payment": "other payment",
    "other_income": "other income",
}


async def merchants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_registered_user(update, context)
    if not user:
        return

    factory = _session_factory(context)
    async with factory() as db:
        merchant_list = await dashboard_service.get_user_merchants(db, user.id)

    if not merchant_list:
        await update.message.reply_text(
            "No merchants classified yet.\n"
            "They'll appear here as you classify incoming SMS prompts, "
            "or you can add one manually with /addmerchant."
        )
        return

    lines = []
    for m in merchant_list:
        direction_label = "→ out" if m.direction == DIRECTION_OUT else "← in"
        cat_label = _CATEGORY_LABEL.get(m.category, m.category)
        lines.append(f"• <b>{m.merchant_name}</b> [{direction_label}] — {cat_label}")

    text = f"🏪 <b>Your Known Merchants ({len(merchant_list)})</b>\n\n" + "\n".join(lines)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── /addmerchant ──────────────────────────────────────────────────────────────

_ADDMERCHANT_USAGE = (
    "Usage: /addmerchant [MERCHANT NAME] [bet/other]\n\n"
    "Examples:\n"
    "/addmerchant PEGASUS bet\n"
    "/addmerchant UTILITY BILLS other\n\n"
    "'bet' classifies deposits out as bet_deposit and income in as bet_withdrawal.\n"
    "'other' classifies them as other_payment and other_income."
)


async def addmerchant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_registered_user(update, context)
    if not user:
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(_ADDMERCHANT_USAGE)
        return

    # Last arg is the type, everything before it is the merchant name
    type_arg = args[-1].lower()
    if type_arg not in ("bet", "other"):
        await update.message.reply_text(f"Type must be 'bet' or 'other'.\n\n{_ADDMERCHANT_USAGE}")
        return

    merchant_name = " ".join(args[:-1]).upper()

    if type_arg == "bet":
        out_cat, in_cat = CATEGORY_BET_DEPOSIT, CATEGORY_BET_WITHDRAWAL
    else:
        out_cat, in_cat = "other_payment", "other_income"

    factory = _session_factory(context)
    async with factory() as db:
        await merchant_service.upsert_merchant(
            db, merchant_name=merchant_name, direction=DIRECTION_OUT,
            category=out_cat, user_id=user.id,
        )
        await merchant_service.upsert_merchant(
            db, merchant_name=merchant_name, direction=DIRECTION_IN,
            category=in_cat, user_id=user.id,
        )
        await db.commit()

    await update.message.reply_text(
        f"✅ <b>{merchant_name}</b> saved.\n"
        f"Outgoing → {out_cat.replace('_', ' ')}\n"
        f"Incoming ← {in_cat.replace('_', ' ')}",
        parse_mode=ParseMode.HTML,
    )


# ── /mydata ───────────────────────────────────────────────────────────────────

async def mydata(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_registered_user(update, context)
    if not user:
        return

    factory = _session_factory(context)
    async with factory() as db:
        summary_data = await dashboard_service.get_mydata_summary(db, user.id)

    t = summary_data.transactions
    username_line = f"@{user.username}" if user.username else "—"
    bankroll_line = (
        f"UGX {user.bankroll:,.0f}" if user.bankroll > 0 else "Not set"
    )

    text = (
        f"📁 <b>Your SenteCheck Data</b>\n\n"
        f"<b>👤 Account</b>\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Username: {username_line}\n"
        f"Member since: {user.onboarded_at.strftime('%d %b %Y')}\n"
        f"Monthly bankroll: {bankroll_line}\n"
        f"Consent version: {user.consent_version}\n\n"
        f"<b>📊 Transactions ({t.total} total)</b>\n"
        f"Bet deposits: {t.bet_deposits} (UGX {t.bet_deposit_total:,.0f})\n"
        f"Bet withdrawals: {t.bet_withdrawals} (UGX {t.bet_withdrawal_total:,.0f})\n"
        f"Other payments: {t.other_payments}\n"
        f"Other income: {t.other_income}\n"
        f"Unclassified: {t.unclassified}\n\n"
        f"<b>🎲 Bets ({summary_data.total_bets} logged)</b>\n"
        f"Wins: {summary_data.wins} | "
        f"Losses: {summary_data.losses} | "
        f"Pending: {summary_data.pending}\n\n"
        f"<b>🏪 Known Merchants</b>\n"
        f"{summary_data.merchant_count} merchant(s) classified\n\n"
        f"<i>To delete all this data permanently, use /deleteaccount.</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── /deleteaccount ────────────────────────────────────────────────────────────

_DELETE_WARNING = (
    "⚠️ <b>Are you sure you want to delete your account?</b>\n\n"
    "This will permanently remove:\n"
    "• All your transactions\n"
    "• All your bets\n"
    "• All your merchant classifications\n"
    "• Your account\n\n"
    "<b>This cannot be undone.</b>"
)


async def deleteaccount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_registered_user(update, context)
    if not user:
        return

    await update.message.reply_text(
        _DELETE_WARNING,
        reply_markup=delete_confirm_keyboard(),
        parse_mode=ParseMode.HTML,
    )


async def deleteaccount_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    action = query.data.split(":")[1]  # "confirm" or "cancel"
    telegram_id = update.effective_user.id

    if action == "cancel":
        await query.edit_message_text("Deletion cancelled. Your data is safe. ✅")
        return

    # action == "confirm"
    factory = _session_factory(context)
    async with factory() as db:
        user = await user_service.get_by_telegram_id(db, telegram_id)
        if not user:
            # Already deleted (double-tap guard)
            await query.edit_message_text("Account not found — it may already have been deleted.")
            return

        await user_service.delete_user(db, user)
        await db.commit()

    await query.edit_message_text(
        "✅ Your account and all associated data have been permanently deleted.\n\n"
        "If you ever want to use SenteCheck again, send /start to create a new account."
    )
