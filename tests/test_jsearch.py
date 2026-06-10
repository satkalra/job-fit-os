import httpx
import pytest
from types import SimpleNamespace

from app.pipeline.jsearch import _build_jsearch_queries, _fetch_jsearch


def _make_profile(domains=None, keywords=None, preferred_locations=None, countries=None, seniority=None):
    return SimpleNamespace(
        domains=domains or [],
        keywords=keywords or "",
        preferred_locations=preferred_locations or [],
        countries=countries or [],
        seniority=seniority or "mid",
        target_companies=[],
        needs_sponsorship=False,
    )


FAKE_JSEARCH_RESPONSE = {
    "data": [
        {
            "job_title": "Data Analyst",
            "employer_name": "Stripe",
            "job_city": "New York",
            "job_country": "US",
            "job_apply_link": "https://stripe.com/jobs/123",
            "job_description": "We are looking for a data analyst...",
            "job_max_salary": 130000,
            "job_posted_at_datetime_utc": "2026-06-01T00:00:00.000Z",
        }
    ]
}


@pytest.mark.asyncio
async def test_fetch_jsearch_returns_raw_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "jsearch.p.rapidapi.com"
        assert request.headers["X-RapidAPI-Key"] == "testkey"
        return httpx.Response(200, json=FAKE_JSEARCH_RESPONSE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await _fetch_jsearch(
            query="data analyst in New York",
            api_key="testkey",
            client=client,
        )

    assert len(jobs) == 1
    assert jobs[0].title == "Data Analyst"
    assert jobs[0].company == "Stripe"
    assert jobs[0].source == "jsearch"
    assert jobs[0].url == "https://stripe.com/jobs/123"
    assert jobs[0].salary_max == 130000


@pytest.mark.asyncio
async def test_fetch_jsearch_empty_key_returns_empty():
    async with httpx.AsyncClient() as client:
        jobs = await _fetch_jsearch(query="analyst", api_key="", client=client)
    assert jobs == []


def test_build_jsearch_queries_analyst_profile():
    profile = _make_profile(
        domains=["analyst", "data"],
        preferred_locations=["New York"],
        seniority="mid",
    )
    queries = _build_jsearch_queries(profile)
    assert len(queries) >= 1
    combined = " ".join(queries).lower()
    assert "analyst" in combined or "data" in combined


def test_build_jsearch_queries_uses_location():
    profile = _make_profile(
        domains=["software engineer"],
        preferred_locations=["San Francisco"],
    )
    queries = _build_jsearch_queries(profile)
    assert any("san francisco" in query.lower() or "remote" in query.lower() for query in queries)


def test_build_jsearch_queries_max_three():
    profile = _make_profile(
        domains=["analyst", "pm", "ops", "finance"],
        preferred_locations=["New York"],
    )
    queries = _build_jsearch_queries(profile)
    assert len(queries) <= 3
