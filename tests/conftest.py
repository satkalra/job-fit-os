import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def created_user():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/users",
            json={
                "email": "test2@example.com",
                "name": "Fixture User",
                "profile_type": "engineering",
                "domains": ["Software Engineering"],
                "seniority": "senior",
                "briefing_time": "07:00",
                "timezone": "America/New_York",
            },
        )
    data = resp.json()
    return data["user_id"], data["management_token"]
