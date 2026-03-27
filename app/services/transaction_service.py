from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import (
    CATEGORY_UNCLASSIFIED,
    SOURCE_ANDROID,
    Transaction,
)


async def create_transaction(
    db: AsyncSession,
    *,
    user_id: int,
    amount: Decimal,
    direction: str,
    merchant_name: str | None,
    raw_sms: str,
    category: str = CATEGORY_UNCLASSIFIED,
    source: str = SOURCE_ANDROID,
) -> Transaction:
    txn = Transaction(
        user_id=user_id,
        amount=amount,
        direction=direction,
        merchant_name=merchant_name,
        raw_sms=raw_sms,
        category=category,
        source=source,
    )
    db.add(txn)
    await db.flush()  # populates txn.id without committing
    return txn
