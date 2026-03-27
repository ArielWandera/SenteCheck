"""
merchant_service.py — Known-merchant lookup and learning logic.

Lookup order:
  1. Global merchants (is_global=TRUE) — shared across all users.
  2. Per-user merchants (is_global=FALSE, user_id=<this user>).

When a user classifies an unknown merchant, upsert_merchant() stores the
classification. If 3 or more distinct users independently classify the same
(merchant_name, direction) pair with the same category, it is automatically
promoted to a global entry so future users are never asked again.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.known_merchant import GLOBAL_CONFIRMATION_THRESHOLD, KnownMerchant


async def lookup_merchant(
    db: AsyncSession,
    merchant_name: str,
    direction: str,
    user_id: int,
) -> KnownMerchant | None:
    """
    Return the best matching KnownMerchant for this (merchant_name, direction)
    pair, or None if the merchant is unknown.

    Global entries take precedence over per-user entries.
    """
    # 1. Global match
    result = await db.execute(
        select(KnownMerchant).where(
            KnownMerchant.merchant_name == merchant_name,
            KnownMerchant.direction == direction,
            KnownMerchant.is_global.is_(True),
        )
    )
    global_match = result.scalar_one_or_none()
    if global_match:
        return global_match

    # 2. Per-user match
    result = await db.execute(
        select(KnownMerchant).where(
            KnownMerchant.merchant_name == merchant_name,
            KnownMerchant.direction == direction,
            KnownMerchant.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_merchant(
    db: AsyncSession,
    *,
    merchant_name: str,
    direction: str,
    category: str,
    user_id: int,
    platform: str | None = None,
) -> KnownMerchant:
    """
    Insert or update a per-user merchant classification, then attempt
    promotion to global if the threshold is reached.
    """
    result = await db.execute(
        select(KnownMerchant).where(
            KnownMerchant.merchant_name == merchant_name,
            KnownMerchant.direction == direction,
            KnownMerchant.user_id == user_id,
        )
    )
    merchant = result.scalar_one_or_none()

    if merchant:
        merchant.category = category
        merchant.confirmed_count += 1
        if platform:
            merchant.platform = platform
    else:
        merchant = KnownMerchant(
            merchant_name=merchant_name,
            direction=direction,
            category=category,
            user_id=user_id,
            platform=platform,
            is_global=False,
        )
        db.add(merchant)

    await db.flush()
    await _maybe_promote_to_global(db, merchant_name, direction, category)
    return merchant


async def _maybe_promote_to_global(
    db: AsyncSession,
    merchant_name: str,
    direction: str,
    category: str,
) -> None:
    """
    Count distinct users who classified (merchant_name, direction) as
    `category`. If the count reaches GLOBAL_CONFIRMATION_THRESHOLD,
    create or refresh a global entry.
    """
    result = await db.execute(
        select(func.count(KnownMerchant.user_id.distinct())).where(
            KnownMerchant.merchant_name == merchant_name,
            KnownMerchant.direction == direction,
            KnownMerchant.category == category,
            KnownMerchant.is_global.is_(False),
        )
    )
    count: int = result.scalar_one()

    if count < GLOBAL_CONFIRMATION_THRESHOLD:
        return

    # Check if a global entry already exists
    result = await db.execute(
        select(KnownMerchant).where(
            KnownMerchant.merchant_name == merchant_name,
            KnownMerchant.direction == direction,
            KnownMerchant.is_global.is_(True),
        )
    )
    global_entry = result.scalar_one_or_none()

    if global_entry:
        global_entry.confirmed_count = count
    else:
        db.add(
            KnownMerchant(
                merchant_name=merchant_name,
                direction=direction,
                category=category,
                is_global=True,
                user_id=None,
                confirmed_count=count,
            )
        )

    await db.flush()
