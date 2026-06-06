import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import users


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
    user_id, token = created_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/users/{user_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "test2@example.com"


@pytest.mark.asyncio
async def test_create_user_with_preferred_locations():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/users",
            json={
                "email": "loc@example.com",
                "name": "Loc User",
                "profile_type": "engineering",
                "domains": ["Software Engineering"],
                "seniority": "senior",
                "briefing_time": "07:00",
                "timezone": "America/New_York",
                "preferred_locations": ["NYC", "Remote"],
            },
        )
    assert resp.status_code == 200
    user_id = resp.json()["user_id"]
    token = resp.json()["management_token"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        get_resp = await client.get(f"/users/{user_id}", headers={"Authorization": f"Bearer {token}"})
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["preferred_locations"] == ["NYC", "Remote"]
    assert "remote_only" not in data


@pytest.mark.asyncio
async def test_patch_user_preferred_locations(created_user):
    user_id, token = created_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/users/{user_id}",
            json={"preferred_locations": ["SF", "Austin"]},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200


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


@pytest.mark.asyncio
async def test_signup_token_required(monkeypatch):
    monkeypatch.setattr(users.settings, "SIGNUP_TOKEN", "secret-token")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/users",
            json={
                "email": "notoken@example.com",
                "name": "No Token",
                "profile_type": "engineering",
                "domains": ["AI"],
                "seniority": "senior",
                "briefing_time": "08:00",
                "timezone": "America/New_York",
            },
        )
    assert resp.status_code == 403
    assert "signup token" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_signup_wrong_token_rejected(monkeypatch):
    monkeypatch.setattr(users.settings, "SIGNUP_TOKEN", "secret-token")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/users",
            headers={"X-Signup-Token": "wrong-token"},
            json={
                "email": "wrongtoken@example.com",
                "name": "Wrong Token",
                "profile_type": "engineering",
                "domains": ["AI"],
                "seniority": "senior",
                "briefing_time": "08:00",
                "timezone": "America/New_York",
            },
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_signup_correct_token_accepted(monkeypatch):
    monkeypatch.setattr(users.settings, "SIGNUP_TOKEN", "secret-token")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/users",
            headers={"X-Signup-Token": "secret-token"},
            json={
                "email": "goodtoken@example.com",
                "name": "Good Token",
                "profile_type": "engineering",
                "domains": ["AI"],
                "seniority": "senior",
                "briefing_time": "08:00",
                "timezone": "America/New_York",
            },
        )
    assert resp.status_code == 200
    assert "management_token" in resp.json()
