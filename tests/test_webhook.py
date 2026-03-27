"""
Tests for POST /webhook/sms.

Uses the in-memory SQLite DB + AsyncClient fixtures from conftest.py.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models.known_merchant import KnownMerchant
from app.models.transaction import (
    CATEGORY_BET_DEPOSIT,
    CATEGORY_OTHER_PAYMENT,
    CATEGORY_UNCLASSIFIED,
    DIRECTION_OUT,
    Transaction,
)
from app.models.user import User

SECRET = "test-webhook-secret-32-chars-xxxx"
HEADERS = {"X-Webhook-Secret": SECRET}

MTN_OUTGOING = (
    "You have sent UGX 10,000 to PEGASUS. "
    "Your new balance is UGX 40,000. Transaction ID: TXN001"
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COUNTER = iter(range(100_000_000, 200_000_000))


async def _create_user(db_session, telegram_id: int | None = None) -> User:
    user = User(
        telegram_id=telegram_id if telegram_id is not None else next(_COUNTER),
        username="testuser",
        consent_given=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

async def test_missing_secret_returns_401(client):
    resp = await client.post(
        "/webhook/sms",
        json={
            "telegram_id": 111222333,
            "raw_sms": MTN_OUTGOING,
            "received_at": "2026-03-27T10:00:00Z",
            "sim": "MTN",
        },
    )
    assert resp.status_code == 422  # Header is required by FastAPI before our check


async def test_wrong_secret_returns_401(client):
    resp = await client.post(
        "/webhook/sms",
        headers={"X-Webhook-Secret": "wrong-secret"},
        json={
            "telegram_id": 111222333,
            "raw_sms": MTN_OUTGOING,
            "received_at": "2026-03-27T10:00:00Z",
            "sim": "MTN",
        },
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# User resolution
# ---------------------------------------------------------------------------

async def test_unknown_user_returns_404(client):
    resp = await client.post(
        "/webhook/sms",
        headers=HEADERS,
        json={
            "telegram_id": 999999999,
            "raw_sms": MTN_OUTGOING,
            "received_at": "2026-03-27T10:00:00Z",
            "sim": "MTN",
        },
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Non-mobile-money SMS
# ---------------------------------------------------------------------------

async def test_non_mm_sms_is_ignored(client, db_session):
    user = await _create_user(db_session)
    resp = await client.post(
        "/webhook/sms",
        headers=HEADERS,
        json={
            "telegram_id": user.telegram_id,
            "raw_sms": "Hey, are you coming tonight?",
            "received_at": "2026-03-27T10:00:00Z",
            "sim": "MTN",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "ignored"


# ---------------------------------------------------------------------------
# Unknown merchant → classification_requested
# ---------------------------------------------------------------------------

async def test_unknown_merchant_returns_classification_requested(client, db_session):
    user = await _create_user(db_session)

    mock_prompt = AsyncMock()
    with patch("app.routers.webhook._send_classification_prompt", mock_prompt):
        resp = await client.post(
            "/webhook/sms",
            headers=HEADERS,
            json={
                "telegram_id": user.telegram_id,
                "raw_sms": MTN_OUTGOING,
                "received_at": "2026-03-27T10:00:00Z",
                "sim": "MTN",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "classification_requested"
    assert body["transaction_id"] is not None

    # Transaction must be stored as unclassified
    txn = await db_session.get(Transaction, body["transaction_id"])
    assert txn is not None
    assert txn.category == CATEGORY_UNCLASSIFIED
    assert txn.direction == DIRECTION_OUT
    assert txn.amount == Decimal("10000")
    assert txn.merchant_name == "PEGASUS"

    # Telegram prompt must have been fired with the right args
    mock_prompt.assert_called_once()
    call_kwargs = mock_prompt.call_args.kwargs
    assert call_kwargs["telegram_id"] == user.telegram_id
    assert call_kwargs["merchant"] == "PEGASUS"
    assert call_kwargs["direction"] == DIRECTION_OUT


# ---------------------------------------------------------------------------
# Known merchant (per-user) → logged silently
# ---------------------------------------------------------------------------

async def test_known_merchant_logs_silently(client, db_session):
    user = await _create_user(db_session)

    # Pre-seed known merchant for this user
    db_session.add(
        KnownMerchant(
            merchant_name="PEGASUS",
            direction=DIRECTION_OUT,
            category=CATEGORY_BET_DEPOSIT,
            user_id=user.id,
            is_global=False,
        )
    )
    await db_session.flush()

    resp = await client.post(
        "/webhook/sms",
        headers=HEADERS,
        json={
            "telegram_id": user.telegram_id,
            "raw_sms": MTN_OUTGOING,
            "received_at": "2026-03-27T10:00:00Z",
            "sim": "MTN",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "logged"

    txn = await db_session.get(Transaction, body["transaction_id"])
    assert txn.category == CATEGORY_BET_DEPOSIT


# ---------------------------------------------------------------------------
# Known merchant (global) → logged silently
# ---------------------------------------------------------------------------

async def test_global_merchant_takes_precedence(client, db_session):
    user = await _create_user(db_session)

    db_session.add(
        KnownMerchant(
            merchant_name="SAINTS BETTING",
            direction=DIRECTION_OUT,
            category=CATEGORY_BET_DEPOSIT,
            user_id=None,
            is_global=True,
        )
    )
    await db_session.flush()

    sms = (
        "You have sent UGX 20,000 to SAINTS BETTING. "
        "Your new balance is UGX 30,000. Transaction ID: TXN002"
    )
    resp = await client.post(
        "/webhook/sms",
        headers=HEADERS,
        json={
            "telegram_id": user.telegram_id,
            "raw_sms": sms,
            "received_at": "2026-03-27T10:00:00Z",
            "sim": "MTN",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "logged"

    txn = await db_session.get(Transaction, body["transaction_id"])
    assert txn.category == CATEGORY_BET_DEPOSIT
    assert txn.amount == Decimal("20000")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

async def test_negative_telegram_id_rejected(client):
    resp = await client.post(
        "/webhook/sms",
        headers=HEADERS,
        json={
            "telegram_id": -1,
            "raw_sms": MTN_OUTGOING,
            "received_at": "2026-03-27T10:00:00Z",
            "sim": "MTN",
        },
    )
    assert resp.status_code == 422


async def test_sms_over_1000_chars_rejected(client):
    resp = await client.post(
        "/webhook/sms",
        headers=HEADERS,
        json={
            "telegram_id": 111222333,
            "raw_sms": "A" * 1001,
            "received_at": "2026-03-27T10:00:00Z",
            "sim": "MTN",
        },
    )
    assert resp.status_code == 422


async def test_invalid_sim_rejected(client):
    resp = await client.post(
        "/webhook/sms",
        headers=HEADERS,
        json={
            "telegram_id": 111222333,
            "raw_sms": MTN_OUTGOING,
            "received_at": "2026-03-27T10:00:00Z",
            "sim": "Safaricom",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
