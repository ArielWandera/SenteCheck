from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.bot.setup import ptb_app
from app.config import settings
from app.routers.webhook import router as webhook_router

# ── slowapi — IP-based rate limiter (first line of DoS defence) ───────────────
# Applied globally; individual endpoints add tighter per-telegram_id limits on
# top of this via app/utils/rate_limiter.py.
limiter = Limiter(key_func=get_remote_address, default_limits=["300/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────
    if settings.ENVIRONMENT != "test":
        await ptb_app.initialize()
        await ptb_app.bot.set_webhook(
            url=f"{settings.FASTAPI_BASE_URL}/webhook/telegram",
            allowed_updates=["message", "callback_query"],
        )
        await ptb_app.start()

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    if settings.ENVIRONMENT != "test":
        await ptb_app.stop()
        await ptb_app.shutdown()


app = FastAPI(
    title="SenteCheck",
    description="Betting finance tracker for Ugandan bettors",
    version="0.1.0",
    debug=not settings.is_production,
    lifespan=lifespan,
)

# Attach slowapi
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(webhook_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
