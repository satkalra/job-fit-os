from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.main import app
from app.models.job import JobResult
from app.schemas.job import ScoredJob


def _mock_scored_job() -> ScoredJob:
    return ScoredJob(
        title="Senior Engineer",
        company="Acme Corp",
        description="Build great things.",
        source="custom",
        global_score=82,
        verdict="apply",
        scores={
            "roleMatch": 4,
            "skillsMatch": 4,
            "experienceLevel": 4,
            "compensation": 4,
            "cultural": 4,
        },
        red_flags=[],
        citations=["5 years Python experience"],
        summary="Strong match on backend skills.",
        rewrite_token="transient-token",
    )


async def _upload_resume(user_id: str, token: str) -> None:
    resume = " ".join(["Senior Python engineer building FastAPI PostgreSQL AI systems"] * 110)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/users/{user_id}/resume/text",
            headers={"Authorization": f"Bearer {token}"},
            json={"resume_text": resume},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_score_job_returns_401_without_token(created_user):
    user_id, _ = created_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/users/{user_id}/jobs/score",
            json={"job_description": "We need a senior backend engineer with Python experience."},
        )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_score_job_returns_422_when_no_resume(created_user):
    user_id, token = created_user
    with patch("app.routers.jobs._score_one_job", new_callable=AsyncMock) as mock_score:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/users/{user_id}/jobs/score",
                headers={"Authorization": f"Bearer {token}"},
                json={"job_description": "We need a senior backend engineer with Python experience."},
            )

    assert resp.status_code == 422
    assert "resume" in resp.json()["detail"].lower()
    mock_score.assert_not_called()


@pytest.mark.asyncio
async def test_score_job_success_with_resume(created_user):
    user_id, token = created_user
    await _upload_resume(user_id, token)

    with patch("app.routers.jobs._score_one_job", new_callable=AsyncMock) as mock_score:
        mock_score.return_value = _mock_scored_job()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/users/{user_id}/jobs/score",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "job_description": "We need a senior backend engineer with Python experience.",
                    "title": "Senior Engineer",
                    "company": "Acme Corp",
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["global_score"] == 82
    assert data["verdict"] == "apply"
    assert "roleMatch" in data["scores"]
    assert data["rewrite_url"] is not None
    assert data["rewrite_url"].startswith("/rewrite?token=")

    async with AsyncSessionLocal() as db:
        job = (await db.execute(select(JobResult))).scalar_one()
    assert job.source == "custom"
    assert job.rewrite_token == data["rewrite_url"].removeprefix("/rewrite?token=")
    assert job.rewrite_token != "transient-token"


@pytest.mark.asyncio
async def test_score_job_uses_scraped_text_when_url_provided(created_user):
    user_id, token = created_user
    await _upload_resume(user_id, token)
    scraped_text = "Scraped job description with lots of detail about the role and requirements. " * 5

    with (
        patch("app.routers.jobs._score_one_job", new_callable=AsyncMock) as mock_score,
        patch("app.routers.jobs.fetch_job_description", new_callable=AsyncMock) as mock_scrape,
    ):
        mock_score.return_value = _mock_scored_job()
        mock_scrape.return_value = scraped_text

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/users/{user_id}/jobs/score",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "job_description": "Fallback description.",
                    "url": "https://example.com/job/123",
                    "title": "Senior Engineer",
                    "company": "Acme Corp",
                },
            )

    assert resp.status_code == 200
    mock_scrape.assert_called_once_with("https://example.com/job/123")
    job_arg = mock_score.call_args.args[0]
    assert job_arg.description == scraped_text

    async with AsyncSessionLocal() as db:
        job = (await db.execute(select(JobResult))).scalar_one()
    assert job.description == scraped_text


@pytest.mark.asyncio
async def test_score_job_accepts_url_without_pasted_description(created_user):
    user_id, token = created_user
    await _upload_resume(user_id, token)
    scraped_text = "Scraped job description with lots of detail about the role and requirements. " * 5

    with (
        patch("app.routers.jobs._score_one_job", new_callable=AsyncMock) as mock_score,
        patch("app.routers.jobs.fetch_job_description", new_callable=AsyncMock) as mock_scrape,
    ):
        mock_score.return_value = _mock_scored_job()
        mock_scrape.return_value = scraped_text

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/users/{user_id}/jobs/score",
                headers={"Authorization": f"Bearer {token}"},
                json={"url": "https://example.com/job/123"},
            )

    assert resp.status_code == 200
    mock_scrape.assert_called_once_with("https://example.com/job/123")
    job_arg = mock_score.call_args.args[0]
    assert job_arg.description == scraped_text


@pytest.mark.asyncio
async def test_score_job_falls_back_to_pasted_when_scrape_fails(created_user):
    user_id, token = created_user
    await _upload_resume(user_id, token)

    with (
        patch("app.routers.jobs._score_one_job", new_callable=AsyncMock) as mock_score,
        patch("app.routers.jobs.fetch_job_description", new_callable=AsyncMock) as mock_scrape,
    ):
        mock_score.return_value = _mock_scored_job()
        mock_scrape.return_value = None

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/users/{user_id}/jobs/score",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "job_description": "Fallback pasted description.",
                    "url": "https://example.com/job/broken",
                },
            )

    assert resp.status_code == 200
    job_arg = mock_score.call_args.args[0]
    assert job_arg.description == "Fallback pasted description."


@pytest.mark.asyncio
async def test_score_job_rejects_url_only_when_scrape_fails(created_user):
    user_id, token = created_user
    await _upload_resume(user_id, token)

    with (
        patch("app.routers.jobs._score_one_job", new_callable=AsyncMock) as mock_score,
        patch("app.routers.jobs.fetch_job_description", new_callable=AsyncMock) as mock_scrape,
    ):
        mock_scrape.return_value = None

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/users/{user_id}/jobs/score",
                headers={"Authorization": f"Bearer {token}"},
                json={"url": "https://example.com/job/broken"},
            )

    assert resp.status_code == 422
    assert "paste" in resp.json()["detail"].lower()
    mock_score.assert_not_called()


@pytest.mark.asyncio
async def test_score_job_rejects_when_url_and_job_description_are_blank(created_user):
    user_id, token = created_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/users/{user_id}/jobs/score",
            headers={"Authorization": f"Bearer {token}"},
            json={"job_description": "   "},
        )

    assert resp.status_code == 422
