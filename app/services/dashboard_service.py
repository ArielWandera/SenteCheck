"""
dashboard_service.py — Data queries powering all dashboard bot commands.

All functions receive an open AsyncSession and the user's integer PK.
They return plain dataclasses/dicts so handlers can format them however
they like without touching SQL.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bet import RESULT_LOSS, RESULT_PENDING, RESULT_WIN, Bet
from app.models.known_merchant import KnownMerchant
from app.models.transaction import (
    CATEGORY_BET_DEPOSIT,
    CATEGORY_BET_WITHDRAWAL,
    DIRECTION_IN,
    DIRECTION_OUT,
    Transaction,
)


# ── Summary ──────────────────────────────────────────────────────────────────

@dataclass
class SummaryStats:
    total_deposited: Decimal
    total_withdrawn: Decimal
    net_pnl: Decimal
    total_bets: int
    wins: int
    losses: int
    pending: int
    win_rate: float | None  # None when no completed bets yet


async def get_summary(db: AsyncSession, user_id: int) -> SummaryStats:
    dep = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.category == CATEGORY_BET_DEPOSIT,
        )
    )
    total_deposited = Decimal(str(dep.scalar()))

    wth = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.category == CATEGORY_BET_WITHDRAWAL,
        )
    )
    total_withdrawn = Decimal(str(wth.scalar()))

    bets = await db.execute(
        select(
            func.count().label("total"),
            func.sum(case((Bet.result == RESULT_WIN, 1), else_=0)).label("wins"),
            func.sum(case((Bet.result == RESULT_LOSS, 1), else_=0)).label("losses"),
            func.sum(case((Bet.result == RESULT_PENDING, 1), else_=0)).label("pending"),
        ).where(Bet.user_id == user_id)
    )
    row = bets.one()
    total_bets = row.total or 0
    wins = row.wins or 0
    losses = row.losses or 0
    pending = row.pending or 0

    completed = wins + losses
    win_rate = round(wins / completed * 100, 1) if completed > 0 else None

    return SummaryStats(
        total_deposited=total_deposited,
        total_withdrawn=total_withdrawn,
        net_pnl=total_withdrawn - total_deposited,
        total_bets=total_bets,
        wins=wins,
        losses=losses,
        pending=pending,
        win_rate=win_rate,
    )


# ── Losses ───────────────────────────────────────────────────────────────────

@dataclass
class LossStats:
    count: int
    total_staked: Decimal
    biggest_loss: Decimal
    recent: list[Bet]


async def get_losses(db: AsyncSession, user_id: int) -> LossStats:
    agg = await db.execute(
        select(
            func.count().label("count"),
            func.coalesce(func.sum(Bet.stake), 0).label("total"),
            func.coalesce(func.max(Bet.stake), 0).label("biggest"),
        ).where(
            Bet.user_id == user_id,
            Bet.result == RESULT_LOSS,
        )
    )
    row = agg.one()

    recent_result = await db.execute(
        select(Bet)
        .where(Bet.user_id == user_id, Bet.result == RESULT_LOSS)
        .order_by(Bet.created_at.desc())
        .limit(5)
    )
    return LossStats(
        count=row.count or 0,
        total_staked=Decimal(str(row.total)),
        biggest_loss=Decimal(str(row.biggest)),
        recent=list(recent_result.scalars()),
    )


# ── Wins ─────────────────────────────────────────────────────────────────────

@dataclass
class WinStats:
    count: int
    total_profit: Decimal
    biggest_profit: Decimal
    recent: list[Bet]


async def get_wins(db: AsyncSession, user_id: int) -> WinStats:
    agg = await db.execute(
        select(
            func.count().label("count"),
            func.coalesce(
                func.sum(Bet.return_amount - Bet.stake), 0
            ).label("total_profit"),
            func.coalesce(
                func.max(Bet.return_amount - Bet.stake), 0
            ).label("biggest_profit"),
        ).where(
            Bet.user_id == user_id,
            Bet.result == RESULT_WIN,
            Bet.return_amount.is_not(None),
        )
    )
    row = agg.one()

    recent_result = await db.execute(
        select(Bet)
        .where(
            Bet.user_id == user_id,
            Bet.result == RESULT_WIN,
            Bet.return_amount.is_not(None),
        )
        .order_by(Bet.created_at.desc())
        .limit(5)
    )
    return WinStats(
        count=row.count or 0,
        total_profit=Decimal(str(row.total_profit)),
        biggest_profit=Decimal(str(row.biggest_profit)),
        recent=list(recent_result.scalars()),
    )


# ── History ───────────────────────────────────────────────────────────────────

async def get_history(
    db: AsyncSession, user_id: int, limit: int = 10
) -> list[Transaction]:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.created_at.desc())
        .limit(min(limit, 50))  # cap at 50 to avoid massive messages
    )
    return list(result.scalars())


# ── Bankroll ──────────────────────────────────────────────────────────────────

@dataclass
class BankrollStatus:
    bankroll: Decimal
    deposited_this_month: Decimal
    remaining: Decimal
    pct_used: float
    recommended_stake: Decimal
    status: str  # healthy | warning | critical | exhausted


async def get_bankroll_status(
    db: AsyncSession, user_id: int, bankroll: Decimal
) -> BankrollStatus | None:
    """Returns None if the user has not set a bankroll."""
    if bankroll <= 0:
        return None

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.category == CATEGORY_BET_DEPOSIT,
            Transaction.created_at >= month_start,
        )
    )
    deposited = Decimal(str(result.scalar()))
    remaining = max(bankroll - deposited, Decimal("0"))
    pct_used = float(deposited / bankroll * 100)
    # Recommended stake: 2 % of remaining, rounded to nearest 100 UGX
    recommended = (remaining * Decimal("0.02") / 100).quantize(Decimal("1")) * 100

    if pct_used >= 100:
        status = "exhausted"
    elif pct_used >= 75:
        status = "critical"
    elif pct_used >= 50:
        status = "warning"
    else:
        status = "healthy"

    return BankrollStatus(
        bankroll=bankroll,
        deposited_this_month=deposited,
        remaining=remaining,
        pct_used=round(pct_used, 1),
        recommended_stake=recommended,
        status=status,
    )


# ── Merchants ─────────────────────────────────────────────────────────────────

async def get_user_merchants(
    db: AsyncSession, user_id: int
) -> list[KnownMerchant]:
    """Returns per-user known merchants, sorted by name."""
    result = await db.execute(
        select(KnownMerchant)
        .where(KnownMerchant.user_id == user_id)
        .order_by(KnownMerchant.merchant_name, KnownMerchant.direction)
    )
    return list(result.scalars())


# ── /mydata summary ───────────────────────────────────────────────────────────

@dataclass
class TransactionCounts:
    total: int
    bet_deposits: int
    bet_deposit_total: Decimal
    bet_withdrawals: int
    bet_withdrawal_total: Decimal
    other_payments: int
    other_income: int
    unclassified: int


@dataclass
class MyDataSummary:
    transactions: TransactionCounts
    total_bets: int
    wins: int
    losses: int
    pending: int
    merchant_count: int


async def get_mydata_summary(db: AsyncSession, user_id: int) -> MyDataSummary:
    from app.models.transaction import (
        CATEGORY_BET_DEPOSIT,
        CATEGORY_BET_WITHDRAWAL,
        CATEGORY_OTHER_INCOME,
        CATEGORY_OTHER_PAYMENT,
        CATEGORY_UNCLASSIFIED,
    )

    txn_rows = await db.execute(
        select(
            func.count().label("total"),
            func.sum(
                case((Transaction.category == CATEGORY_BET_DEPOSIT, 1), else_=0)
            ).label("dep_count"),
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.category == CATEGORY_BET_DEPOSIT, Transaction.amount),
                        else_=0,
                    )
                ),
                0,
            ).label("dep_total"),
            func.sum(
                case((Transaction.category == CATEGORY_BET_WITHDRAWAL, 1), else_=0)
            ).label("wth_count"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Transaction.category == CATEGORY_BET_WITHDRAWAL,
                            Transaction.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("wth_total"),
            func.sum(
                case((Transaction.category == CATEGORY_OTHER_PAYMENT, 1), else_=0)
            ).label("other_pay"),
            func.sum(
                case((Transaction.category == CATEGORY_OTHER_INCOME, 1), else_=0)
            ).label("other_inc"),
            func.sum(
                case((Transaction.category == CATEGORY_UNCLASSIFIED, 1), else_=0)
            ).label("unclass"),
        ).where(Transaction.user_id == user_id)
    )
    t = txn_rows.one()

    bet_rows = await db.execute(
        select(
            func.count().label("total"),
            func.sum(case((Bet.result == RESULT_WIN, 1), else_=0)).label("wins"),
            func.sum(case((Bet.result == RESULT_LOSS, 1), else_=0)).label("losses"),
            func.sum(case((Bet.result == RESULT_PENDING, 1), else_=0)).label("pending"),
        ).where(Bet.user_id == user_id)
    )
    b = bet_rows.one()

    merchant_count_row = await db.execute(
        select(func.count()).where(KnownMerchant.user_id == user_id)
    )

    return MyDataSummary(
        transactions=TransactionCounts(
            total=t.total or 0,
            bet_deposits=t.dep_count or 0,
            bet_deposit_total=Decimal(str(t.dep_total)),
            bet_withdrawals=t.wth_count or 0,
            bet_withdrawal_total=Decimal(str(t.wth_total)),
            other_payments=t.other_pay or 0,
            other_income=t.other_inc or 0,
            unclassified=t.unclass or 0,
        ),
        total_bets=b.total or 0,
        wins=b.wins or 0,
        losses=b.losses or 0,
        pending=b.pending or 0,
        merchant_count=merchant_count_row.scalar() or 0,
    )
