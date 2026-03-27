"""
POST /webhook/sms      — receives SMS payloads from the Android app.
POST /webhook/telegram — receives Telegram bot updates.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update

from app.bot.setup import ptb_app
from app.bot.keyboards import deposit_classification_keyboard, withdrawal_classification_keyboard
from app.config import settings
from app.database import get_db
from app.models.transaction import (
    CATEGORY_BET_DEPOSIT,
    CATEGORY_BET_WITHDRAWAL,
    CATEGORY_OTHER_INCOME,
    CATEGORY_OTHER_PAYMENT,
    CATEGORY_UNCLASSIFIED,
    DIRECTION_IN,
    DIRECTION_OUT,
)
from app.schemas.sms import SMSPayload, WebhookResponse
from app.services import merchant_service, transaction_service, user_service
from app.services.sms_parser import parse_sms
from app.utils.rate_limiter import sms_limiter

router = APIRouter(prefix="/webhook", tags=["webhook"])

# ---------------------------------------------------------------------------
# Authentication dependency
# ---------------------------------------------------------------------------

async def _require_webhook_secret(
    x_webhook_secret: str = Header(..., alias="X-Webhook-Secret"),
) -> None:
    if x_webhook_secret != settings.WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing webhook secret",
        )


# ---------------------------------------------------------------------------
# POST /webhook/sms
# ---------------------------------------------------------------------------

@router.post(
    "/sms",
    response_model=WebhookResponse,
    dependencies=[Depends(_require_webhook_secret)],
)
async def receive_sms(
    payload: SMSPayload,
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    # 1. Per-telegram_id rate limit: 60 requests/hour
    #    (a real user cannot receive more than ~1 mobile money SMS per minute)
    if not sms_limiter.is_allowed(str(payload.telegram_id)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Maximum 60 SMS per hour per user.",
        )

    # 2. Resolve user — must exist (onboarded via Telegram /start first)
    user = await user_service.get_by_telegram_id(db, payload.telegram_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Complete /start on Telegram first.",
        )

    # 2. Parse the SMS
    parsed = parse_sms(payload.raw_sms, sim_hint=payload.sim)

    # 3. Ignore non-payment SMS (personal messages, unrecognised formats)
    if not parsed.is_mobile_money or parsed.direction is None or parsed.amount is None:
        return WebhookResponse(status="ok", action="ignored")

    # 4. Handle the case where the parser found a direction but no merchant
    #    (e.g. MTN cash withdrawal). Log as unclassified silently — no prompt
    #    possible without a merchant name.
    if not parsed.merchant_name:
        txn = await transaction_service.create_transaction(
            db,
            user_id=user.id,
            amount=parsed.amount,
            direction=parsed.direction,
            merchant_name=None,
            raw_sms=payload.raw_sms,
            category=CATEGORY_UNCLASSIFIED,
        )
        await db.commit()
        return WebhookResponse(status="ok", action="logged", transaction_id=txn.id)

    # 5. Look up merchant in known_merchants
    known = await merchant_service.lookup_merchant(
        db,
        merchant_name=parsed.merchant_name,
        direction=parsed.direction,
        user_id=user.id,
    )

    # 6. Classify and log
    if known:
        category = known.category
        txn = await transaction_service.create_transaction(
            db,
            user_id=user.id,
            amount=parsed.amount,
            direction=parsed.direction,
            merchant_name=parsed.merchant_name,
            raw_sms=payload.raw_sms,
            category=category,
        )
        await db.commit()
        return WebhookResponse(status="ok", action="logged", transaction_id=txn.id)

    # 7. Unknown merchant — log as unclassified, then send Telegram classification prompt
    txn = await transaction_service.create_transaction(
        db,
        user_id=user.id,
        amount=parsed.amount,
        direction=parsed.direction,
        merchant_name=parsed.merchant_name,
        raw_sms=payload.raw_sms,
        category=CATEGORY_UNCLASSIFIED,
    )
    await db.commit()

    # Send the inline-keyboard prompt to the user's Telegram.
    # Best-effort: a Telegram failure must never cause the webhook to fail —
    # the transaction is already committed and the SMS data is safe.
    try:
        await _send_classification_prompt(
            telegram_id=user.telegram_id,
            txn_id=txn.id,
            amount=parsed.amount,
            merchant=parsed.merchant_name,
            direction=parsed.direction,
        )
    except Exception:
        pass  # logged via Telegram's own error handling; do not surface to Android app

    return WebhookResponse(
        status="ok",
        action="classification_requested",
        transaction_id=txn.id,
    )


async def _send_classification_prompt(
    telegram_id: int,
    txn_id: int,
    amount,
    merchant: str,
    direction: str,
) -> None:
    """Send the Yes/No classification keyboard to the user on Telegram."""
    if direction == DIRECTION_OUT:
        text = (
            f"You sent <b>UGX {amount:,.0f}</b> to <b>{merchant}</b>.\n"
            f"Was this a deposit to a betting site?"
        )
        keyboard = deposit_classification_keyboard(txn_id)
    else:
        text = (
            f"You received <b>UGX {amount:,.0f}</b> from <b>{merchant}</b>.\n"
            f"Was this a withdrawal from a betting site?"
        )
        keyboard = withdrawal_classification_keyboard(txn_id)

    await ptb_app.bot.send_message(
        chat_id=telegram_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# POST /webhook/telegram — receives Telegram bot updates
# ---------------------------------------------------------------------------

@router.post("/telegram", status_code=status.HTTP_200_OK)
async def telegram_webhook(request: Request) -> dict:
    import logging
    logger = logging.getLogger(__name__)
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
    except Exception as e:
        logger.exception("Error processing Telegram update: %s", e)
    return {"ok": True}
