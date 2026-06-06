import asyncio
import copy
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
from anthropic import AsyncAnthropic

from app.config import settings
from app.models.user import UserProfile
from app.schemas.job import RawJob
from app.utils.aliases import ROLE_ALIASES

_anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY or "not-set")
logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "company_ats_registry.json"
_REACT_MODEL = "claude-haiku-4-5-20251001"
_MAX_REACT_ITERATIONS = 8
_CONTEXT_TRIM_AT = 4
_REACT_TIMEOUT_SECONDS = 60


def _dedup_jobs(jobs: list[RawJob]) -> list[RawJob]:
    seen = set()
    unique = []
    for job in jobs:
        key = (job.company or "").lower() + "::" + (job.title or "")[:20].lower()
        if key not in seen:
            seen.add(key)
            unique.append(job)
        else:
            logger.debug("dedup_jobs dropped duplicate company=%s title=%s", job.company, job.title)
    logger.debug("dedup_jobs input=%s output=%s", len(jobs), len(unique))
    return unique


async def _fetch_greenhouse(token: str, client: httpx.AsyncClient) -> list[RawJob]:
    logger.info("discover status=ats_fetch_start provider=greenhouse token=%s", token)
    try:
        resp = await client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
            params={"content": "true"},
            timeout=4,
        )
        resp.raise_for_status()
        jobs = [
            RawJob(
                title=j.get("title", ""),
                company=token,
                location=(j.get("location") or {}).get("name"),
                url=j.get("absolute_url"),
                description=j.get("content", ""),
                source="ats",
            )
            for j in resp.json().get("jobs", [])
        ]
        logger.info("discover status=ats_fetch_complete provider=greenhouse token=%s jobs=%s", token, len(jobs))
        return jobs
    except httpx.HTTPStatusError as exc:
        logger.debug("fetch_greenhouse token=%s status=%s", token, exc.response.status_code)
        return []
    except Exception:
        logger.exception("fetch_greenhouse failed token=%s", token)
        return []


async def _fetch_lever(token: str, client: httpx.AsyncClient) -> list[RawJob]:
    logger.info("discover status=ats_fetch_start provider=lever token=%s", token)
    try:
        resp = await client.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"}, timeout=4)
        resp.raise_for_status()
        jobs = [
            RawJob(
                title=j.get("text", ""),
                company=token,
                location=(j.get("categories") or {}).get("location"),
                url=j.get("hostedUrl"),
                description=j.get("descriptionPlain", ""),
                source="ats",
            )
            for j in resp.json()
        ]
        logger.info("discover status=ats_fetch_complete provider=lever token=%s jobs=%s", token, len(jobs))
        return jobs
    except httpx.HTTPStatusError as exc:
        logger.debug("fetch_lever token=%s status=%s", token, exc.response.status_code)
        return []
    except Exception:
        logger.exception("fetch_lever failed token=%s", token)
        return []


async def _fetch_ashby(token: str, client: httpx.AsyncClient) -> list[RawJob]:
    logger.info("discover status=ats_fetch_start provider=ashby token=%s", token)
    try:
        resp = await client.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{token}",
            params={"includeCompensation": "true"},
            timeout=4,
        )
        resp.raise_for_status()
        jobs = []
        for j in resp.json().get("jobPostings", []):
            compensation = j.get("compensation") or {}
            salary_max = compensation.get("maxValue")
            salary = None
            if compensation:
                salary = f"{compensation.get('minValue', '')}-{compensation.get('maxValue', '')} {compensation.get('currency', '')}"
            jobs.append(
                RawJob(
                    title=j.get("title", ""),
                    company=token,
                    location=j.get("locationName"),
                    url=j.get("jobUrl"),
                    description=j.get("descriptionPlain", ""),
                    salary=salary,
                    salary_max=salary_max,
                    source="ats",
                )
            )
        logger.info("discover status=ats_fetch_complete provider=ashby token=%s jobs=%s", token, len(jobs))
        return jobs
    except httpx.HTTPStatusError as exc:
        logger.debug("fetch_ashby token=%s status=%s", token, exc.response.status_code)
        return []
    except Exception:
        logger.exception("fetch_ashby failed token=%s", token)
        return []


_DEFAULT_BIGTECH = (
    "Google, Meta, Amazon, Microsoft, Apple, Netflix, OpenAI, Anthropic, Uber, Airbnb"
)


def _constraints_clause(profile: UserProfile, locations_str: str) -> str:
    """Shared hard constraints so the searcher returns jobs that survive the gates."""
    parts = [f"Location must be one of: {locations_str} (or fully remote)."]
    if profile.countries:
        parts.append(f"Only roles legally based in: {', '.join(profile.countries)}.")
    if profile.seniority:
        parts.append(f"Seniority level: {profile.seniority} (exclude roles far above this level).")
    if getattr(profile, "needs_sponsorship", False):
        parts.append("ONLY include roles that explicitly offer visa sponsorship; skip citizens-only / no-sponsorship roles.")
    return " ".join(parts)


def _load_company_registry() -> list[dict[str, str]]:
    try:
        data = json.loads(_REGISTRY_PATH.read_text())
    except FileNotFoundError:
        logger.warning("discover status=registry_missing path=%s", _REGISTRY_PATH)
        return []
    except Exception:
        logger.exception("discover status=registry_load_failed path=%s", _REGISTRY_PATH)
        return []
    return [
        entry
        for entry in data
        if isinstance(entry, dict) and entry.get("ats") in {"greenhouse", "lever", "ashby"} and entry.get("token")
    ]


async def _fetch_company_ats(company: dict[str, str], client: httpx.AsyncClient) -> list[RawJob]:
    ats_type = company.get("ats", "")
    token = company.get("token", "")
    if not ats_type or not token:
        logger.debug("discover_jobs skipped company missing ats/token entry=%s", company)
        return []
    if ats_type == "greenhouse":
        logger.debug("discover_jobs queued greenhouse token=%s", token)
        jobs = await _fetch_greenhouse(token, client)
    elif ats_type == "lever":
        logger.debug("discover_jobs queued lever token=%s", token)
        jobs = await _fetch_lever(token, client)
    elif ats_type == "ashby":
        logger.debug("discover_jobs queued ashby token=%s", token)
        jobs = await _fetch_ashby(token, client)
    else:
        logger.debug("discover_jobs unknown ats_type=%s token=%s", ats_type, token)
        return []

    company_name = company.get("name")
    if company_name:
        for job in jobs:
            job.company = company_name
    return jobs


def _queue_ats_fetch(company: dict[str, str], client: httpx.AsyncClient) -> Any | None:
    if not company.get("ats") or not company.get("token"):
        logger.debug("discover_jobs skipped company missing ats/token entry=%s", company)
        return None
    return _fetch_company_ats(company, client)


def _company_token_candidates(name: str) -> list[str]:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    compact = base.replace("-", "")
    candidates = [base, compact]
    without_suffix = re.sub(r"-(inc|labs|ai|hq|technologies|technology|software|systems)$", "", base)
    if without_suffix and without_suffix not in candidates:
        candidates.append(without_suffix)
    return [candidate for candidate in dict.fromkeys(candidates) if candidate]


async def _company_lookup(name: str, client: httpx.AsyncClient) -> list[RawJob]:
    for token in _company_token_candidates(name):
        for fetcher in (_fetch_greenhouse, _fetch_lever, _fetch_ashby):
            jobs = await fetcher(token, client)
            if jobs:
                for job in jobs:
                    job.company = name
                    job.source = "ats"
                return jobs
    return []


def _react_tools() -> list[dict[str, Any]]:
    return [
        {"type": "web_search_20250305", "name": "web_search"},
        {
            "name": "company_lookup",
            "description": "Find open jobs for one company by probing Greenhouse, Lever, and Ashby ATS boards.",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Company name, e.g. Vercel"}},
                "required": ["name"],
            },
        },
    ]


def _build_react_prompt(profile: UserProfile) -> str:
    role_terms = ", ".join(profile.domains or [])
    if not role_terms and profile.keywords:
        role_terms = ", ".join(k.strip() for k in (profile.keywords or "").split(",")[:3])
    for abbr, expansions in ROLE_ALIASES.items():
        if abbr in role_terms.lower():
            role_terms += ", " + ", ".join(sorted(expansions))

    pref_locations = ", ".join(profile.preferred_locations or [])
    countries = ", ".join(profile.countries or [])
    locations_str = ", ".join(filter(None, [pref_locations, countries])) or "Remote"
    target_names = [c.get("name", "") for c in (profile.target_companies or []) if c.get("name")]
    exclude = ", ".join(filter(None, [", ".join(target_names), _DEFAULT_BIGTECH]))
    constraints = _constraints_clause(profile, locations_str)

    return f"""Find 20-30 currently open job postings for this candidate.

Roles/domains: {role_terms or "software engineering"}
Keywords: {profile.keywords or role_terms}
Hard constraints: {constraints}
Exclude companies already covered elsewhere: {exclude}

Use web_search to discover unknown companies and niche boards such as LinkedIn, Indeed, Wellfound, Y Combinator Work at a Startup, Otta, startup ecosystem lists, and company career pages.
When you identify a promising company name, call company_lookup with only the company name.
Adapt each search based on gaps in prior results. Prefer startups and mid-size companies over household-name big tech.

Return discovered jobs as JSON arrays in text whenever possible, with objects shaped exactly as:
[{{"title":"...","company":"...","location":"...","url":"...","description":"...","posted_date":null}}]
Only include real open postings with apply URLs."""


def _text_from_response(response: Any) -> str:
    text_parts = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            text_parts.append(text)
        if isinstance(block, dict) and block.get("text"):
            text_parts.append(block["text"])
    return "\n".join(text_parts)


def _content_blocks_for_messages(content: Any) -> list[dict[str, Any]]:
    blocks = []
    for block in content or []:
        if isinstance(block, dict):
            blocks.append(block)
        elif hasattr(block, "model_dump"):
            blocks.append(block.model_dump(exclude_none=True))
        else:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                blocks.append({"type": "text", "text": getattr(block, "text", "")})
            elif block_type == "tool_use":
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {}),
                    }
                )
    return blocks


def _coerce_jobs_from_json_text(text: str, source: str) -> list[RawJob]:
    jobs: list[RawJob] = []
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\[", text):
        try:
            raw, _ = decoder.raw_decode(text[match.start() :])
        except Exception:
            continue
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict) or not item.get("title") or not item.get("company"):
                continue
            jobs.append(
                RawJob(
                    title=item.get("title", ""),
                    company=item.get("company", ""),
                    location=item.get("location"),
                    url=item.get("url"),
                    description=item.get("description", ""),
                    posted_date=item.get("posted_date"),
                    source=source,
                )
            )
    return jobs


async def _dispatch_tool(tool_call: Any, client: httpx.AsyncClient) -> str:
    name = getattr(tool_call, "name", None) or (tool_call.get("name") if isinstance(tool_call, dict) else None)
    if name == "web_search":
        return ""
    try:
        tool_input = getattr(tool_call, "input", None) or (tool_call.get("input") if isinstance(tool_call, dict) else {}) or {}
        if name == "company_lookup":
            company_name = str(tool_input.get("name", "")).strip()
            if not company_name:
                return "[]"
            jobs = await _company_lookup(company_name, client)
            return json.dumps([job.model_dump() for job in jobs])
    except Exception:
        logger.exception("react tool dispatch failed tool=%s", name)
    return ""


def _extract_jobs_from_results(dispatch_results: list[str]) -> list[RawJob]:
    jobs: list[RawJob] = []
    for result in dispatch_results:
        jobs.extend(_coerce_jobs_from_json_text(result or "", "ats"))
    return jobs


def _trim_to_summary(found_jobs: list[RawJob], profile: UserProfile) -> list[dict[str, Any]]:
    companies = sorted({job.company for job in found_jobs if job.company})[:30]
    remaining = ", ".join(profile.domains or []) or (profile.keywords or "matching roles")
    summary = (
        f"So far found {len(found_jobs)} jobs at: {', '.join(companies) or 'no companies yet'}. "
        f"Continue searching for gaps in: {remaining}."
    )
    return [
        {"role": "user", "content": _build_react_prompt(profile)},
        {"role": "assistant", "content": [{"type": "text", "text": summary}]},
    ]


async def _run_react_search_agent_inner(profile: UserProfile) -> list[RawJob]:
    user_id = getattr(profile, "user_id", None)
    messages: list[dict[str, Any]] = [{"role": "user", "content": _build_react_prompt(profile)}]
    found_jobs: list[RawJob] = []

    async with httpx.AsyncClient() as client:
        for iteration in range(_MAX_REACT_ITERATIONS):
            logger.info("discover status=react_iteration_start user_id=%s iteration=%s", user_id, iteration)
            response = await _anthropic.messages.create(
                model=_REACT_MODEL,
                max_tokens=4000,
                tools=_react_tools(),
                messages=copy.deepcopy(messages),
            )
            messages.append({"role": "assistant", "content": _content_blocks_for_messages(getattr(response, "content", []))})

            found_jobs.extend(_coerce_jobs_from_json_text(_text_from_response(response), "ai"))

            if getattr(response, "stop_reason", None) == "pause_turn":
                logger.info("discover status=react_pause_turn user_id=%s iteration=%s", user_id, iteration)
                messages.append({"role": "user", "content": []})
                continue

            tool_calls = [
                block
                for block in getattr(response, "content", []) or []
                if (getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)) == "tool_use"
            ]
            client_tool_calls = [
                tc
                for tc in tool_calls
                if (getattr(tc, "name", None) or (tc.get("name") if isinstance(tc, dict) else None)) != "web_search"
            ]
            if not tool_calls:
                logger.info("discover status=react_complete user_id=%s iteration=%s jobs=%s", user_id, iteration, len(found_jobs))
                break

            dispatch_results = await asyncio.gather(*[_dispatch_tool(tc, client) for tc in client_tool_calls])
            if client_tool_calls:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": getattr(tc, "id", None) or (tc.get("id") if isinstance(tc, dict) else ""),
                                "content": result,
                            }
                            for tc, result in zip(client_tool_calls, dispatch_results)
                        ],
                    }
                )
            else:
                messages.append({"role": "user", "content": []})

            found_jobs.extend(_extract_jobs_from_results(dispatch_results))
            found_jobs = _dedup_jobs(found_jobs)

            if iteration == _CONTEXT_TRIM_AT:
                messages = _trim_to_summary(found_jobs, profile)

    return found_jobs


async def _run_react_search_agent(profile: UserProfile) -> list[RawJob]:
    if not settings.ANTHROPIC_API_KEY:
        logger.info("discover status=search_skipped reason=missing_anthropic_api_key user_id=%s", getattr(profile, "user_id", None))
        return []
    try:
        return await asyncio.wait_for(_run_react_search_agent_inner(profile), timeout=_REACT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("discover status=react_timeout user_id=%s timeout=%s", getattr(profile, "user_id", None), _REACT_TIMEOUT_SECONDS)
        return []
    except Exception:
        logger.exception("react search agent failed user_id=%s", getattr(profile, "user_id", None))
        return []


async def discover_jobs(profile: UserProfile) -> list[RawJob]:
    logger.info("discover status=start user_id=%s target_companies=%s", getattr(profile, "user_id", None), len(profile.target_companies or []))
    ats_tasks = []
    registry = _load_company_registry()
    seen_registry_keys = {
        (company.get("ats", ""), company.get("token", ""))
        for company in profile.target_companies or []
        if company.get("ats") and company.get("token")
    }

    async with httpx.AsyncClient() as client:
        for company in profile.target_companies or []:
            task = _queue_ats_fetch(company, client)
            if task is not None:
                ats_tasks.append(task)

        for company in registry:
            key = (company.get("ats", ""), company.get("token", ""))
            if key in seen_registry_keys:
                continue
            task = _queue_ats_fetch(company, client)
            if task is not None:
                ats_tasks.append(task)

        ats_results, search_results = await asyncio.gather(
            asyncio.gather(*ats_tasks, return_exceptions=True) if ats_tasks else asyncio.sleep(0, result=[]),
            _run_react_search_agent(profile),
        )

    all_jobs: list[RawJob] = []
    for result in ats_results:
        if isinstance(result, list):
            all_jobs.extend(result)
        else:
            logger.debug("discover_jobs ats result exception=%r", result)
    all_jobs.extend(search_results)
    unique = _dedup_jobs(all_jobs)
    logger.info("discover status=complete user_id=%s raw=%s unique=%s", getattr(profile, "user_id", None), len(all_jobs), len(unique))
    return unique
