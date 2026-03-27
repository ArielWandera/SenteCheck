from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_by_telegram_id(db: AsyncSession, telegram_id: int) -> User | None:
    result = await db.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def delete_user(db: AsyncSession, user: User) -> None:
    """
    Permanently delete the user and all their data.

    Cascade deletes on the FK constraints (set up in the Alembic migration with
    ondelete="CASCADE") handle transactions, bets, and known_merchants automatically.
    The caller must commit after this call.
    """
    await db.delete(user)
    await db.flush()
