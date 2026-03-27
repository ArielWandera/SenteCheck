"""
Shared pytest fixtures.

Uses an in-memory SQLite database (via aiosqlite) so tests require no
running PostgreSQL instance. The schema is created fresh for every test
session via SQLAlchemy's create_all.
"""
import os

# Set required env vars before any app module is imported.
# These are test-only values — the real secrets live in .env.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0000000000:test_token")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret-32-chars-xxxx")
os.environ.setdefault("FASTAPI_BASE_URL", "http://localhost:8000")
os.environ.setdefault("ENVIRONMENT", "test")
# Valid 32-byte Fernet key for test encryption (NOT used in production)
os.environ.setdefault(
    "ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1zZW50ZWNoZWNrISE="
)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models import Base

# SQLite in-memory — fast, no external service needed
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def engine():
    _engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    await _engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    """
    Yields an AsyncSession whose commits use SAVEPOINTs so the outer
    transaction can be rolled back after each test, giving a clean slate
    even when the code under test calls session.commit().
    """
    async with engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(
            conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    """AsyncClient wired to the FastAPI app with the test DB injected."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
