import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user import UserProfile
from app.pipeline.discover import (
    _build_react_scout_prompt,
    _dedup_jobs,
    _filter_registry_by_domain,
    _filter_seen,
    _job_hash,
    _run_react_search_agent,
    discover_jobs,
)
from app.schemas.job import RawJob


def make_profile():
    profile = UserProfile()
    profile.domains = ["AI Engineering", "Software Engineering"]
    profile.target_companies = [{"name": "Anthropic", "ats": "greenhouse", "token": "anthropic"}]
    profile.keywords = "python fastapi llm"
    profile.preferred_locations = None
    profile.countries = []
    profile.seniority = "senior"
    return profile


def test_dedup_removes_duplicates():
    jobs = [
        RawJob(title="Senior Engineer", company="Acme", source="ats"),
        RawJob(title="Senior Engineer", company="Acme", source="ai"),
        RawJob(title="Staff Engineer", company="Acme", source="ats"),
    ]
    assert len(_dedup_jobs(jobs)) == 2


def _text_response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason)


def _tool_response(tool_id: str, name: str, tool_input: dict):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)],
        stop_reason="tool_use",
    )


def _tool_and_text_response(tool_id: str, name: str, tool_input: dict, text: str):
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text=text),
            SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input),
        ],
        stop_reason="tool_use",
    )


@pytest.mark.asyncio
async def test_discover_returns_list():
    profile = make_profile()
    with patch("app.pipeline.discover._load_company_registry", return_value=[]):
        with patch("app.pipeline.discover.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"jobs": []}
            mock_resp.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            with patch("app.pipeline.discover._run_react_search_agent", return_value=[]):
                result = await discover_jobs(profile)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_discover_fetches_registry_entries():
    profile = make_profile()
    profile.target_companies = []

    with patch("app.pipeline.discover._load_company_registry", return_value=[{"name": "Vercel", "ats": "greenhouse", "token": "vercel"}]):
        with patch("app.pipeline.discover.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "jobs": [{"title": "Engineer", "location": {"name": "Remote"}, "absolute_url": "https://example.com", "content": "python"}]
            }
            mock_resp.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            with patch("app.pipeline.discover._run_react_search_agent", return_value=[]):
                result = await discover_jobs(profile)

    assert len(result) == 1
    assert result[0].company == "Vercel"


@pytest.mark.asyncio
async def test_react_zero_iter_ignores_text_jobs():
    profile = make_profile()
    response = _text_response(
        '[{"title":"ML Engineer","company":"Acme","location":"Remote","url":"https://example.com","description":"python","posted_date":null}]'
    )
    with patch("app.pipeline.discover.settings.ANTHROPIC_API_KEY", "test-key"):
        with patch("app.pipeline.discover._anthropic.messages.create", new=AsyncMock(return_value=response)):
            jobs = await _run_react_search_agent(profile)

    assert jobs == []


@pytest.mark.asyncio
async def test_react_single_web_search_continues_without_client_dispatch():
    profile = make_profile()
    responses = [
        _tool_response("web-1", "web_search", {"query": "software engineer jobs"}),
        _text_response(
            '[{"title":"Backend Engineer","company":"SearchCo","location":"NYC","url":"https://example.com","description":"fastapi","posted_date":null}]'
        ),
    ]
    with patch("app.pipeline.discover.settings.ANTHROPIC_API_KEY", "test-key"):
        with patch("app.pipeline.discover._anthropic.messages.create", new=AsyncMock(side_effect=responses)) as mock_create:
            with patch("app.pipeline.discover._company_lookup", new=AsyncMock()) as mock_lookup:
                jobs = await _run_react_search_agent(profile)

    assert jobs == []
    assert mock_create.await_count == 2
    mock_lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_react_company_lookup_resolves_jobs():
    profile = make_profile()
    responses = [
        _tool_response("tool-1", "company_lookup", {"name": "Vercel"}),
        _text_response("done"),
    ]
    resolved = [RawJob(title="AI Engineer", company="Vercel", location="Remote", url="https://example.com", description="llm", source="ats")]
    with patch("app.pipeline.discover.settings.ANTHROPIC_API_KEY", "test-key"):
        with patch("app.pipeline.discover._anthropic.messages.create", new=AsyncMock(side_effect=responses)):
            with patch("app.pipeline.discover._company_lookup", new=AsyncMock(return_value=resolved)):
                jobs = await _run_react_search_agent(profile)

    assert len(jobs) == 1
    assert jobs[0].source == "ats"


@pytest.mark.asyncio
async def test_react_does_not_extract_response_text_jobs():
    profile = make_profile()
    responses = [
        _tool_and_text_response(
            "tool-1",
            "company_lookup",
            {"name": "Vercel"},
            '[{"title":"AI Engineer","company":"Acme","location":"Remote","url":"https://example.com","description":"llm","posted_date":null}]',
        ),
        _text_response("done"),
    ]
    with patch("app.pipeline.discover.settings.ANTHROPIC_API_KEY", "test-key"):
        with patch("app.pipeline.discover._anthropic.messages.create", new=AsyncMock(side_effect=responses)):
            with patch("app.pipeline.discover._company_lookup", new=AsyncMock(return_value=[])):
                jobs = await _run_react_search_agent(profile)

    assert jobs == []


@pytest.mark.asyncio
async def test_react_trims_context_at_iter_four():
    profile = make_profile()
    responses = [
        _tool_response(f"tool-{i}", "company_lookup", {"name": f"Company {i}"})
        for i in range(5)
    ] + [_text_response("done")]
    with patch("app.pipeline.discover.settings.ANTHROPIC_API_KEY", "test-key"):
        with patch("app.pipeline.discover._anthropic.messages.create", new=AsyncMock(side_effect=responses)) as mock_create:
            with patch("app.pipeline.discover._company_lookup", new=AsyncMock(return_value=[])):
                await _run_react_search_agent(profile)

    last_messages = mock_create.await_args_list[-1].kwargs["messages"]
    assert len(last_messages) == 2
    assert "So far found" in last_messages[1]["content"][0]["text"]
    assert last_messages[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_react_handles_pause_turn():
    profile = make_profile()
    responses = [
        _text_response("", stop_reason="pause_turn"),
        _text_response(
            '[{"title":"Platform Engineer","company":"PauseCo","location":"Remote","url":"https://example.com","description":"python","posted_date":null}]'
        ),
    ]
    with patch("app.pipeline.discover.settings.ANTHROPIC_API_KEY", "test-key"):
        with patch("app.pipeline.discover._anthropic.messages.create", new=AsyncMock(side_effect=responses)) as mock_create:
            jobs = await _run_react_search_agent(profile)

    second_messages = mock_create.await_args_list[1].kwargs["messages"]
    assert second_messages[-1] == {"role": "user", "content": []}
    assert jobs == []


@pytest.mark.asyncio
async def test_react_wall_clock_timeout_returns_empty():
    profile = make_profile()

    async def slow_inner(_profile, _exclude_companies):
        await asyncio.sleep(1)
        return [RawJob(title="Engineer", company="LateCo")]

    with patch("app.pipeline.discover.settings.ANTHROPIC_API_KEY", "test-key"):
        with patch("app.pipeline.discover._REACT_TIMEOUT_SECONDS", 0.01):
            with patch("app.pipeline.discover._run_react_search_agent_inner", new=slow_inner):
                jobs = await _run_react_search_agent(profile)

    assert jobs == []


@pytest.mark.asyncio
async def test_discover_skips_ats_for_name_only_company():
    """Company with name-only (no ats/token) should not trigger an ATS fetch.
    JSearch calls are separate; we patch run_jsearch to isolate ATS behaviour."""
    profile = UserProfile()
    profile.domains = ["Software Engineering"]
    profile.keywords = "python"
    profile.preferred_locations = None
    profile.target_companies = [{"name": "Stripe"}]

    with patch("app.pipeline.discover._load_company_registry", return_value=[]):
        with patch("app.pipeline.discover._run_react_search_agent", return_value=[]):
            with patch("app.pipeline.jsearch.run_jsearch", return_value=[]):
                with patch("app.pipeline.discover.httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=False)
                    mock_client_cls.return_value = mock_client
                    result = await discover_jobs(profile)

    mock_client.get.assert_not_called()
    assert result == []


@pytest.mark.asyncio
async def test_discover_still_fetches_ats_when_token_present():
    """Company with ats+token should trigger exactly one ATS fetch (Greenhouse).
    JSearch is patched out to isolate ATS call count."""
    profile = UserProfile()
    profile.domains = ["Software Engineering"]
    profile.keywords = "python"
    profile.preferred_locations = ["NYC"]
    profile.target_companies = [
        {"name": "Stripe"},
        {"name": "Anthropic", "ats": "greenhouse", "token": "anthropic"},
    ]

    with patch("app.pipeline.discover._load_company_registry", return_value=[]):
        with patch("app.pipeline.discover._run_react_search_agent", return_value=[]):
            with patch("app.pipeline.jsearch.run_jsearch", return_value=[]):
                with patch("app.pipeline.discover.httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=False)
                    mock_resp = MagicMock()
                    mock_resp.json.return_value = {"jobs": []}
                    mock_resp.raise_for_status = MagicMock()
                    mock_client.get = AsyncMock(return_value=mock_resp)
                    mock_client_cls.return_value = mock_client
                    await discover_jobs(profile)

    assert mock_client.get.call_count == 1


def test_scout_prompt_does_not_ask_for_json():
    profile = make_profile()
    profile.domains = ["analyst"]
    profile.preferred_locations = ["NYC"]
    prompt = _build_react_scout_prompt(profile, exclude_companies=set())
    assert "do not output json" in prompt.lower()
    assert "company_lookup" in prompt


def test_scout_prompt_excludes_known_companies():
    profile = make_profile()
    prompt = _build_react_scout_prompt(profile, exclude_companies={"Scale AI", "GitLab"})
    assert "Scale AI" in prompt
    assert "GitLab" in prompt


def test_scout_prompt_includes_domain():
    profile = make_profile()
    profile.domains = ["business analyst", "data analyst"]
    prompt = _build_react_scout_prompt(profile, exclude_companies=set())
    assert "business analyst" in prompt.lower() or "analyst" in prompt.lower()


def test_job_hash_is_16_chars():
    assert len(_job_hash("Scale AI", "Data Analyst")) == 16


def test_job_hash_same_company_title_same_hash():
    assert _job_hash("Scale AI", "Data Analyst") == _job_hash("Scale AI", "Data Analyst")


def test_job_hash_case_insensitive():
    assert _job_hash("scale ai", "data analyst") == _job_hash("Scale AI", "Data Analyst")


def test_job_hash_different_company_different_hash():
    assert _job_hash("Stripe", "Data Analyst") != _job_hash("Scale AI", "Data Analyst")


def test_filter_seen_removes_by_hash():
    job = RawJob(title="Data Analyst", company="Scale AI", url=None)
    result = _filter_seen([job], seen_hashes={_job_hash("Scale AI", "Data Analyst")})
    assert result == []


def test_filter_seen_keeps_new_job():
    job = RawJob(title="Data Analyst", company="Stripe", url=None)
    result = _filter_seen([job], seen_hashes={_job_hash("Scale AI", "Data Analyst")})
    assert len(result) == 1


def test_filter_seen_empty_set_passes_all():
    jobs = [RawJob(title="Analyst", company="Acme"), RawJob(title="PM", company="Other")]
    assert len(_filter_seen(jobs, seen_hashes=set())) == 2


def test_filter_registry_matches_domain():
    registry = [
        {"name": "Stripe", "ats": "greenhouse", "token": "stripe", "domains": ["fintech", "engineering"]},
        {"name": "dbt Labs", "ats": "greenhouse", "token": "dbt", "domains": ["analytics", "data"]},
        {"name": "Vercel", "ats": "greenhouse", "token": "vercel", "domains": ["engineering"]},
    ]
    result = _filter_registry_by_domain(registry, ["analytics", "data"])
    assert len(result) == 1
    assert result[0]["name"] == "dbt Labs"


def test_filter_registry_falls_back_to_all_on_no_match():
    registry = [{"name": "Stripe", "ats": "greenhouse", "token": "stripe", "domains": ["fintech"]}]
    result = _filter_registry_by_domain(registry, ["quantum_computing"])
    assert len(result) == 1


def test_filter_registry_no_profile_domains_returns_all():
    registry = [{"name": "X", "ats": "greenhouse", "token": "x", "domains": ["engineering"]}]
    assert len(_filter_registry_by_domain(registry, None)) == 1
