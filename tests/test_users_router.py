import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_create_user():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/users",
            json={
                "email": "test@example.com",
                "name": "Test User",
                "profile_type": "engineering",
                "domains": ["AI Engineering"],
                "seniority": "senior",
                "briefing_time": "08:00",
                "timezone": "America/New_York",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "user_id" in data
    assert "management_token" in data


@pytest.mark.asyncio
async def test_get_user(created_user):
    user_id, _token = created_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/users/{user_id}")
    assert resp.status_code == 200
    assert resp.json()["email"] == "test2@example.com"


@pytest.mark.asyncio
async def test_upload_resume_text(created_user):
    user_id, token = created_user
    resume = " ".join(["Python engineer building FastAPI PostgreSQL AI systems"] * 110)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/users/{user_id}/resume/text",
            headers={"Authorization": f"Bearer {token}"},
            json={"resume_text": resume},
        )
    assert resp.status_code == 200
    assert resp.json()["word_count"] >= 100
