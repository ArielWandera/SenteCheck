"""
rate_limiter.py — Sliding-window rate limiter for per-telegram_id limits.

slowapi (added to main.py) handles IP-based DoS protection at the middleware
level. This module handles the per-user limits the spec requires:
  - SMS webhook:   60 requests per telegram_id per hour
  - Bot commands:  30 commands per telegram_id per minute
"""
import threading
from collections import defaultdict
from datetime import datetime, timezone


class SlidingWindowLimiter:
    """
    Thread-safe sliding-window rate limiter backed by an in-memory dict.

    Each key stores a list of UTC timestamps for calls within the current
    window. Old timestamps are pruned on each check, so memory is bounded
    by (active_users × max_calls).
    """

    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._store: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """
        Return True and record the call if it is within the limit.
        Return False (without recording) if the limit has been reached.
        """
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - self.window_seconds

        with self._lock:
            recent = [t for t in self._store[key] if t > cutoff]
            if len(recent) >= self.max_calls:
                self._store[key] = recent  # keep pruned list
                return False
            recent.append(now)
            self._store[key] = recent
            return True

    def reset(self, key: str) -> None:
        """Clear all call records for a key (useful in tests)."""
        with self._lock:
            self._store.pop(key, None)


# ── Singletons used throughout the app ───────────────────────────────────────

# POST /webhook/sms — a real user cannot receive > 1 mobile money SMS per minute
sms_limiter = SlidingWindowLimiter(max_calls=60, window_seconds=3600)

# Telegram bot commands — prevents command spam
bot_limiter = SlidingWindowLimiter(max_calls=30, window_seconds=60)
