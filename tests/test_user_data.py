"""
Tests for /mydata summary queries and /deleteaccount cascade.

These test the service layer directly (no HTTP, no Telegram) using the same
in-memory SQLite DB fixture from conftest.py.
"""
from decimal import Decimal

import pytest

from app.models.bet import Bet
from app.models.known_merchant import KnownMerchant
from app.models.transaction import (
    CATEGORY_BET_DEPOSIT,
    CATEGORY_BET_WITHDRAWAL,
    CATEGORY_OTHER_PAYMENT,
    CATEGORY_UNCLASSIFIED,
    DIRECTION_IN,
    DIRECTION_OUT,
    Transaction,
)
from app.models.user import User
from app.services import dashboard_service, user_service

pytestmark = pytest.mark.asyncio

_COUNTER = iter(range(300_000_000, 400_000_000))


async def _seed_user(db) -> User:
    user = User(
        telegram_id=next(_COUNTER),
        username="ario",
        consent_given=True,
    )
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# /mydata — get_mydata_summary
# ---------------------------------------------------------------------------

async def test_mydata_empty_user(db_session):
    """A brand-new user with no activity returns all-zero counts."""
    user = await _seed_user(db_session)
    result = await dashboard_service.get_mydata_summary(db_session, user.id)

    assert result.transactions.total == 0
    assert result.transactions.bet_deposits == 0
    assert result.transactions.bet_deposit_total == Decimal("0")
    assert result.total_bets == 0
    assert result.merchant_count == 0


async def test_mydata_counts_transactions_correctly(db_session):
    """Transaction counts per category must be accurate."""
    user = await _seed_user(db_session)

    for cat in [CATEGORY_BET_DEPOSIT, CATEGORY_BET_DEPOSIT, CATEGORY_BET_WITHDRAWAL,
                CATEGORY_OTHER_PAYMENT, CATEGORY_UNCLASSIFIED]:
        db_session.add(Transaction(
            user_id=user.id, amount=Decimal("10000"),
            direction=DIRECTION_OUT, category=cat,
            raw_sms="test", source="android_app",
        ))
    await db_session.flush()

    result = await dashboard_service.get_mydata_summary(db_session, user.id)
    t = result.transactions

    assert t.total == 5
    assert t.bet_deposits == 2
    assert t.bet_deposit_total == Decimal("20000")
    assert t.bet_withdrawals == 1
    assert t.other_payments == 1
    assert t.unclassified == 1


async def test_mydata_counts_bets_correctly(db_session):
    """Bet counts by result must be accurate."""
    user = await _seed_user(db_session)

    db_session.add(Bet(user_id=user.id, stake=Decimal("5000"), result="win",
                       return_amount=Decimal("12000")))
    db_session.add(Bet(user_id=user.id, stake=Decimal("3000"), result="loss"))
    db_session.add(Bet(user_id=user.id, stake=Decimal("2000"), result="pending"))
    await db_session.flush()

    result = await dashboard_service.get_mydata_summary(db_session, user.id)

    assert result.total_bets == 3
    assert result.wins == 1
    assert result.losses == 1
    assert result.pending == 1


async def test_mydata_counts_merchants(db_session):
    """Known merchant count reflects per-user entries only."""
    user = await _seed_user(db_session)

    for name in ["PEGASUS", "SAINTS BETTING"]:
        db_session.add(KnownMerchant(
            merchant_name=name, direction=DIRECTION_OUT,
            category=CATEGORY_BET_DEPOSIT, user_id=user.id, is_global=False,
        ))
    # Global merchant — should NOT be counted against this user
    db_session.add(KnownMerchant(
        merchant_name="GLOBAL_MCC", direction=DIRECTION_OUT,
        category=CATEGORY_BET_DEPOSIT, user_id=None, is_global=True,
    ))
    await db_session.flush()

    result = await dashboard_service.get_mydata_summary(db_session, user.id)
    assert result.merchant_count == 2


# ---------------------------------------------------------------------------
# /deleteaccount — delete_user cascade
# ---------------------------------------------------------------------------

async def test_delete_user_removes_user_row(db_session):
    user = await _seed_user(db_session)
    tid = user.telegram_id

    await user_service.delete_user(db_session, user)
    await db_session.flush()

    gone = await user_service.get_by_telegram_id(db_session, tid)
    assert gone is None


async def test_delete_user_cascades_to_transactions(db_session):
    """Deleting a user must cascade-delete their transactions."""
    from sqlalchemy import select

    user = await _seed_user(db_session)
    txn = Transaction(
        user_id=user.id, amount=Decimal("5000"),
        direction=DIRECTION_OUT, category=CATEGORY_BET_DEPOSIT,
        raw_sms="test", source="android_app",
    )
    db_session.add(txn)
    await db_session.flush()
    txn_id = txn.id

    await user_service.delete_user(db_session, user)
    await db_session.flush()

    result = await db_session.execute(
        select(Transaction).where(Transaction.id == txn_id)
    )
    assert result.scalar_one_or_none() is None


async def test_delete_user_cascades_to_bets(db_session):
    """Deleting a user must cascade-delete their bets."""
    from sqlalchemy import select

    user = await _seed_user(db_session)
    b = Bet(user_id=user.id, stake=Decimal("3000"), result="pending")
    db_session.add(b)
    await db_session.flush()
    bet_id = b.id

    await user_service.delete_user(db_session, user)
    await db_session.flush()

    result = await db_session.execute(select(Bet).where(Bet.id == bet_id))
    assert result.scalar_one_or_none() is None


async def test_delete_user_cascades_to_merchants(db_session):
    """Deleting a user must cascade-delete their known_merchants entries."""
    from sqlalchemy import select

    user = await _seed_user(db_session)
    m = KnownMerchant(
        merchant_name="TESTCO", direction=DIRECTION_OUT,
        category=CATEGORY_BET_DEPOSIT, user_id=user.id, is_global=False,
    )
    db_session.add(m)
    await db_session.flush()
    mid = m.id

    await user_service.delete_user(db_session, user)
    await db_session.flush()

    result = await db_session.execute(
        select(KnownMerchant).where(KnownMerchant.id == mid)
    )
    assert result.scalar_one_or_none() is None


async def test_delete_only_affects_target_user(db_session):
    """Deleting user A must not remove user B's data."""
    from sqlalchemy import select

    user_a = await _seed_user(db_session)
    user_b = await _seed_user(db_session)

    txn_b = Transaction(
        user_id=user_b.id, amount=Decimal("7000"),
        direction=DIRECTION_OUT, category=CATEGORY_BET_DEPOSIT,
        raw_sms="test", source="android_app",
    )
    db_session.add(txn_b)
    await db_session.flush()
    txn_b_id = txn_b.id

    await user_service.delete_user(db_session, user_a)
    await db_session.flush()

    # User B and their transaction must still exist
    assert await user_service.get_by_telegram_id(db_session, user_b.telegram_id) is not None
    result = await db_session.execute(
        select(Transaction).where(Transaction.id == txn_b_id)
    )
    assert result.scalar_one_or_none() is not None
