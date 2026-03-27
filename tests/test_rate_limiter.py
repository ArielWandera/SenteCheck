"""
Tests for the sliding-window rate limiter and its integration with
the SMS webhook endpoint.
"""
import pytest

from app.models.user import User
from app.utils.rate_limiter import SlidingWindowLimiter, sms_limiter

SECRET = "test-webhook-secret-32-chars-xxxx"
HEADERS = {"X-Webhook-Secret": SECRET}

MTN_SMS = (
    "You have sent UGX 5,000 to PEGASUS. "
    "Your new balance is UGX 20,000. Transaction ID: TXN001"
)

_COUNTER = iter(range(500_000_000, 600_000_000))


# ---------------------------------------------------------------------------
# Unit tests — SlidingWindowLimiter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("_", range(1))  # run once as a regular test
def test_allows_calls_within_limit(_):
    limiter = SlidingWindowLimiter(max_calls=3, window_seconds=60)
    key = "unit_user_1"
    assert limiter.is_allowed(key) is True
    assert limiter.is_allowed(key) is True
    assert limiter.is_allowed(key) is True


def test_blocks_calls_over_limit():
    limiter = SlidingWindowLimiter(max_calls=3, window_seconds=60)
    key = "unit_user_2"
    for _ in range(3):
        limiter.is_allowed(key)
    assert limiter.is_allowed(key) is False


def test_different_keys_are_independent():
    limiter = SlidingWindowLimiter(max_calls=2, window_seconds=60)
    for _ in range(2):
        limiter.is_allowed("unit_key_a")
    assert limiter.is_allowed("unit_key_a") is False
    assert limiter.is_allowed("unit_key_b") is True


def test_reset_clears_key():
    limiter = SlidingWindowLimiter(max_calls=1, window_seconds=60)
    key = "unit_user_reset"
    limiter.is_allowed(key)
    assert limiter.is_allowed(key) is False
    limiter.reset(key)
    assert limiter.is_allowed(key) is True


def test_expired_calls_not_counted():
    """Timestamps older than the window must not count against the limit."""
    limiter = SlidingWindowLimiter(max_calls=2, window_seconds=1)
    key = "unit_user_expire"
    limiter.is_allowed(key)
    limiter.is_allowed(key)
    assert limiter.is_allowed(key) is False

    # Backdate all stored timestamps to simulate the window having passed
    with limiter._lock:
        limiter._store[key] = [t - 2 for t in limiter._store[key]]

    assert limiter.is_allowed(key) is True


# ---------------------------------------------------------------------------
# Integration — SMS webhook returns 429 when rate limit exceeded
# ---------------------------------------------------------------------------

async def _create_user(db_session, telegram_id: int | None = None) -> User:
    user = User(
        telegram_id=telegram_id if telegram_id is not None else next(_COUNTER),
        username="ratelimituser",
        consent_given=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_sms_webhook_rate_limit_returns_429(client, db_session):
    """After 60 requests the endpoint must respond 429."""
    from unittest.mock import AsyncMock, patch

    user = await _create_user(db_session)
    key = str(user.telegram_id)

    # Pre-fill the limiter to the threshold
    sms_limiter.reset(key)
    for _ in range(60):
        sms_limiter.is_allowed(key)

    with patch("app.routers.webhook._send_classification_prompt", AsyncMock()):
        resp = await client.post(
            "/webhook/sms",
            headers=HEADERS,
            json={
                "telegram_id": user.telegram_id,
                "raw_sms": MTN_SMS,
                "received_at": "2026-03-27T10:00:00Z",
                "sim": "MTN",
            },
        )

    assert resp.status_code == 429
    sms_limiter.reset(key)  # clean up so other tests are unaffected


async def test_sms_webhook_allows_request_within_limit(client, db_session):
    """A fresh user's first request must be accepted (not rate-limited)."""
    from unittest.mock import AsyncMock, patch

    user = await _create_user(db_session)
    sms_limiter.reset(str(user.telegram_id))

    with patch("app.routers.webhook._send_classification_prompt", AsyncMock()):
        resp = await client.post(
            "/webhook/sms",
            headers=HEADERS,
            json={
                "telegram_id": user.telegram_id,
                "raw_sms": MTN_SMS,
                "received_at": "2026-03-27T10:00:00Z",
                "sim": "MTN",
            },
        )

    assert resp.status_code == 200
    sms_limiter.reset(str(user.telegram_id))
