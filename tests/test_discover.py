from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user import UserProfile
from app.pipeline.discover import _dedup_jobs, discover_jobs
from app.schemas.job import RawJob


def make_profile():
    profile = UserProfile()
    profile.domains = ["AI Engineering", "Software Engineering"]
    profile.target_companies = [{"name": "Anthropic", "ats": "greenhouse", "token": "anthropic"}]
    profile.keywords = "python fastapi llm"
    return profile


def test_dedup_removes_duplicates():
    jobs = [
        RawJob(title="Senior Engineer", company="Acme", source="ats"),
        RawJob(title="Senior Engineer", company="Acme", source="ai"),
        RawJob(title="Staff Engineer", company="Acme", source="ats"),
    ]
    assert len(_dedup_jobs(jobs)) == 2


@pytest.mark.asyncio
async def test_discover_returns_list():
    profile = make_profile()
    with patch("app.pipeline.discover.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"jobs": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client
        with patch("app.pipeline.discover._search_with_haiku", return_value=[]):
            result = await discover_jobs(profile)
    assert isinstance(result, list)
