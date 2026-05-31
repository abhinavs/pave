import os

os.environ.setdefault("USE_SQLITE", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from collections.abc import AsyncGenerator  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth.password import hash_password  # noqa: E402
from app.auth.sessions import SESSION_COOKIE, create_session  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402

# One shared in-memory database for the whole test session. StaticPool keeps a
# single connection so schema created in one fixture is visible in another.
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _schema() -> AsyncGenerator[None, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async session that is rolled back after the test, never committed."""
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    # raise_app_exceptions=False mirrors how the production runtime treats
    # an unhandled exception: the registered 500 handler converts it into
    # an HTTP response, and the worker keeps going. With the default True,
    # httpx re-raises out of the test, masking what a real user would see.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """A created, unverified user with a known password."""
    user = User(
        name="Ada",
        email="ada@example.com",
        password_hash=hash_password("correct horse"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def verified_user(db_session: AsyncSession) -> User:
    """Same as test_user but with email already verified."""
    user = User(
        name="Grace",
        email="grace@example.com",
        password_hash=hash_password("correct horse"),
        email_verified_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def authenticated_client(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> AsyncClient:
    """async_client carrying a real DB-backed session cookie for test_user.

    The session is minted through the same `create_session` the auth routes
    use, so the fixture exercises the production path - no special-case
    "test cookie" that would diverge from how real users authenticate."""
    token = await create_session(db_session, user_id=test_user.id)
    await db_session.commit()
    async_client.cookies.set(SESSION_COOKIE, token)
    return async_client


@pytest.fixture(autouse=True)
def mock_soniq_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.jobs

    async def _fake_enqueue(target: object, **kwargs: object) -> str:
        return "fake-job-id"

    monkeypatch.setattr(app.jobs.soniq, "enqueue", _fake_enqueue)
