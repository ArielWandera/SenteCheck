"""
End-to-end tests — simulate the full lifecycle of a SenteCheck user.

These tests exercise the HTTP layer (via AsyncClient) plus the service and
persistence layers together, verifying that data flows correctly from
SMS receipt through classification to dashboard reporting.

No real Telegram API calls are made — outbound Telegram calls are patched.
The test DB is in-memory SQLite (same as other test modules).
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

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
from app.services import dashboard_service, merchant_service

SECRET = "test-webhook-secret-32-chars-xxxx"
HEADERS = {"X-Webhook-Secret": SECRET}

pytestmark = pytest.mark.asyncio

# Unique telegram_id range for this module
_COUNTER = iter(range(300_000_000, 400_000_000))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SMS_MTN_OUTGOING = (
    "You have sent UGX {amount} to {merchant}. "
    "Your new balance is UGX 50,000. Transaction ID: TXN123"
)
SMS_MTN_INCOMING = (
    "You have received UGX {amount} from {merchant}. "
    "Your new balance is UGX 60,000. Transaction ID: TXN124"
)
SMS_AIRTEL_OUTGOING = (
    "UGX {amount} sent to {merchant}. New Airtel Money balance: UGX 45,000."
)


async def _make_user(db_session, *, bankroll: Decimal | None = None) -> User:
    user = User(
        telegram_id=next(_COUNTER),
        username="e2e_user",
        consent_given=True,
        bankroll=bankroll or Decimal("0"),
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# Scenario 1 — Unknown merchant → classification prompt → re-send auto-classifies
# ---------------------------------------------------------------------------

async def test_unknown_merchant_then_reclassify_and_auto_classify(client, db_session):
    """
    Full round-trip:
    1. SMS arrives with unknown merchant → stored as UNCLASSIFIED, prompt fired.
    2. User classifies via merchant upsert (simulating bot callback).
    3. Second SMS from same merchant → auto-classified as bet_deposit, no prompt.
    """
    user = await _make_user(db_session)

    # ── Step 1: first SMS from unknown merchant ──────────────────────────────
    mock_prompt = AsyncMock()
    with patch("app.routers.webhook._send_classification_prompt", mock_prompt):
        resp = await client.post(
            "/webhook/sms",
            headers=HEADERS,
            json={
                "telegram_id": user.telegram_id,
                "raw_sms": SMS_MTN_OUTGOING.format(amount="15,000", merchant="SPORTYBET"),
                "received_at": "2026-03-27T10:00:00Z",
                "sim": "MTN",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "classification_requested"
    txn1_id = body["transaction_id"]

    # Transaction is stored as unclassified
    txn1 = await db_session.get(Transaction, txn1_id)
    assert txn1.category == CATEGORY_UNCLASSIFIED
    assert txn1.amount == Decimal("15000")
    assert txn1.merchant_name == "SPORTYBET"

    # Classification prompt was fired once
    mock_prompt.assert_called_once()

    # ── Step 2: user classifies SPORTYBET as bet_deposit ─────────────────────
    # (simulates what classification_callback does in handlers.py)
    txn1.category = CATEGORY_BET_DEPOSIT
    await merchant_service.upsert_merchant(
        db_session,
        merchant_name="SPORTYBET",
        direction=DIRECTION_OUT,
        category=CATEGORY_BET_DEPOSIT,
        user_id=user.id,
    )
    await db_session.flush()

    # ── Step 3: second SMS from same merchant → auto-classified ───────────────
    mock_prompt2 = AsyncMock()
    with patch("app.routers.webhook._send_classification_prompt", mock_prompt2):
        resp2 = await client.post(
            "/webhook/sms",
            headers=HEADERS,
            json={
                "telegram_id": user.telegram_id,
                "raw_sms": SMS_MTN_OUTGOING.format(amount="20,000", merchant="SPORTYBET"),
                "received_at": "2026-03-27T11:00:00Z",
                "sim": "MTN",
            },
        )

    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["action"] == "logged"  # auto-classified, no prompt needed

    txn2 = await db_session.get(Transaction, body2["transaction_id"])
    assert txn2.category == CATEGORY_BET_DEPOSIT
    assert txn2.amount == Decimal("20000")

    # No prompt fired this time
    mock_prompt2.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 2 — Global merchant promotion at 3 distinct-user confirmations
# ---------------------------------------------------------------------------

async def test_global_merchant_promotion_after_three_users(client, db_session):
    """
    When 3 different users all classify the same merchant+direction the same
    way, it is promoted to global and a 4th user's SMS is auto-classified.
    """
    MERCHANT = "BETWAY_AFRICA"
    users = [await _make_user(db_session) for _ in range(4)]

    # Users 0–2 each classify BETWAY_AFRICA outgoing as bet_deposit
    for u in users[:3]:
        await merchant_service.upsert_merchant(
            db_session,
            merchant_name=MERCHANT,
            direction=DIRECTION_OUT,
            category=CATEGORY_BET_DEPOSIT,
            user_id=u.id,
        )
    await db_session.flush()

    # Verify the merchant was promoted to global
    result = await db_session.execute(
        select(KnownMerchant).where(
            KnownMerchant.merchant_name == MERCHANT,
            KnownMerchant.direction == DIRECTION_OUT,
            KnownMerchant.is_global.is_(True),
        )
    )
    global_entry = result.scalar_one_or_none()
    assert global_entry is not None, "Merchant should have been promoted to global"
    assert global_entry.category == CATEGORY_BET_DEPOSIT

    # User 3 (never classified) — SMS should be auto-classified via the global entry
    mock_prompt = AsyncMock()
    with patch("app.routers.webhook._send_classification_prompt", mock_prompt):
        resp = await client.post(
            "/webhook/sms",
            headers=HEADERS,
            json={
                "telegram_id": users[3].telegram_id,
                "raw_sms": SMS_MTN_OUTGOING.format(amount="5,000", merchant=MERCHANT),
                "received_at": "2026-03-27T12:00:00Z",
                "sim": "MTN",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "logged"

    txn = await db_session.get(Transaction, body["transaction_id"])
    assert txn.category == CATEGORY_BET_DEPOSIT
    mock_prompt.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 3 — Dashboard reflects real transaction data
# ---------------------------------------------------------------------------

async def test_dashboard_summary_reflects_transactions(client, db_session):
    """
    After several classified transactions are stored, the dashboard service
    returns accurate totals.
    """
    user = await _make_user(db_session, bankroll=Decimal("100000"))

    # Seed: 3 bet deposits, 1 bet withdrawal, 1 other payment
    async def _seed_txn(direction, category, amount, merchant=None):
        from app.services.transaction_service import create_transaction
        txn = await create_transaction(
            db_session,
            user_id=user.id,
            amount=Decimal(str(amount)),
            direction=direction,
            merchant_name=merchant,
            raw_sms=None,
            category=category,
        )
        return txn

    await _seed_txn(DIRECTION_OUT, CATEGORY_BET_DEPOSIT, 10000, "SPORTYBET")
    await _seed_txn(DIRECTION_OUT, CATEGORY_BET_DEPOSIT, 20000, "BETWAY")
    await _seed_txn(DIRECTION_OUT, CATEGORY_BET_DEPOSIT, 5000, "SPORTYBET")
    await _seed_txn(DIRECTION_IN, CATEGORY_BET_WITHDRAWAL, 30000, "SPORTYBET")
    await _seed_txn(DIRECTION_OUT, CATEGORY_OTHER_PAYMENT, 8000, "UMEME")
    await db_session.flush()

    stats = await dashboard_service.get_summary(db_session, user.id)

    assert stats.total_deposited == Decimal("35000")   # 10k + 20k + 5k
    assert stats.total_withdrawn == Decimal("30000")
    assert stats.net_pnl == Decimal("-5000")           # 30k - 35k
    assert stats.total_bets == 0                       # no Bet rows


async def test_bankroll_status_warning_threshold(client, db_session):
    """
    When >75% of monthly bankroll is used in bet deposits the status is
    'warning' or higher.
    """
    user = await _make_user(db_session, bankroll=Decimal("100000"))

    from app.services.transaction_service import create_transaction
    # Deposit 80 000 — 80% of 100 000
    await create_transaction(
        db_session,
        user_id=user.id,
        amount=Decimal("80000"),
        direction=DIRECTION_OUT,
        merchant_name="BETWAY",
        raw_sms=None,
        category=CATEGORY_BET_DEPOSIT,
    )
    await db_session.flush()

    br = await dashboard_service.get_bankroll_status(db_session, user.id, user.bankroll)
    assert br is not None
    assert br.status in ("warning", "critical", "exhausted")
    assert br.pct_used == 80
    assert br.remaining == Decimal("20000")


# ---------------------------------------------------------------------------
# Scenario 4 — Multiple SMS types in sequence (MTN + Airtel, out + in)
# ---------------------------------------------------------------------------

async def test_mixed_sms_types_all_logged(client, db_session):
    """
    MTN outgoing, Airtel outgoing, and MTN incoming from the same user
    are each parsed and stored with correct direction and sim.
    """
    user = await _make_user(db_session)

    # Pre-seed merchants so all land as "logged" (no prompts)
    for merchant, direction, category in [
        ("BETPAWA", DIRECTION_OUT, CATEGORY_BET_DEPOSIT),
        ("TOPBETS", DIRECTION_OUT, CATEGORY_BET_DEPOSIT),
        ("BETPAWA", DIRECTION_IN, CATEGORY_BET_WITHDRAWAL),
    ]:
        await merchant_service.upsert_merchant(
            db_session,
            merchant_name=merchant,
            direction=direction,
            category=category,
            user_id=user.id,
        )
    await db_session.flush()

    cases = [
        (
            "MTN",
            SMS_MTN_OUTGOING.format(amount="12,000", merchant="BETPAWA"),
            DIRECTION_OUT,
            Decimal("12000"),
        ),
        (
            "Airtel",
            SMS_AIRTEL_OUTGOING.format(amount="8,000", merchant="TOPBETS"),
            DIRECTION_OUT,
            Decimal("8000"),
        ),
        (
            "MTN",
            SMS_MTN_INCOMING.format(amount="25,000", merchant="BETPAWA"),
            DIRECTION_IN,
            Decimal("25000"),
        ),
    ]

    for sim, sms, expected_direction, expected_amount in cases:
        resp = await client.post(
            "/webhook/sms",
            headers=HEADERS,
            json={
                "telegram_id": user.telegram_id,
                "raw_sms": sms,
                "received_at": "2026-03-27T13:00:00Z",
                "sim": sim,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "logged", f"Expected 'logged' for sim={sim}"

        txn = await db_session.get(Transaction, body["transaction_id"])
        assert txn.direction == expected_direction
        assert txn.amount == expected_amount


# ---------------------------------------------------------------------------
# Scenario 5 — Non-mobile-money SMS is silently ignored, no record created
# ---------------------------------------------------------------------------

async def test_personal_sms_ignored_no_transaction_stored(client, db_session):
    """Personal messages that pass the Android filter (shouldn't) are still
    dropped at the webhook level — no Transaction row is created."""
    user = await _make_user(db_session)

    before_count_result = await db_session.execute(
        select(Transaction).where(Transaction.user_id == user.id)
    )
    before_count = len(before_count_result.scalars().all())

    resp = await client.post(
        "/webhook/sms",
        headers=HEADERS,
        json={
            "telegram_id": user.telegram_id,
            "raw_sms": "Mum called — please call back when free.",
            "received_at": "2026-03-27T14:00:00Z",
            "sim": "MTN",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "ignored"

    after_count_result = await db_session.execute(
        select(Transaction).where(Transaction.user_id == user.id)
    )
    after_count = len(after_count_result.scalars().all())
    assert after_count == before_count  # no new row


# ---------------------------------------------------------------------------
# Scenario 6 — Withdrawal (no merchant) logged without classification prompt
# ---------------------------------------------------------------------------

async def test_mtn_withdrawal_logged_without_prompt(client, db_session):
    """
    MTN cash-withdrawal SMS has no merchant — should be stored as UNCLASSIFIED
    silently (no classification prompt since there's no merchant to learn).
    """
    user = await _make_user(db_session)

    withdrawal_sms = (
        "Your withdrawal of UGX 30,000 from your Mobile Money wallet was successful. "
        "New balance: UGX 20,000. Transaction ID: TXN789"
    )

    mock_prompt = AsyncMock()
    with patch("app.routers.webhook._send_classification_prompt", mock_prompt):
        resp = await client.post(
            "/webhook/sms",
            headers=HEADERS,
            json={
                "telegram_id": user.telegram_id,
                "raw_sms": withdrawal_sms,
                "received_at": "2026-03-27T15:00:00Z",
                "sim": "MTN",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "logged"

    txn = await db_session.get(Transaction, body["transaction_id"])
    assert txn.category == CATEGORY_UNCLASSIFIED
    assert txn.merchant_name is None

    mock_prompt.assert_not_called()
