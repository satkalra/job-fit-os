import asyncio
import copy
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
from anthropic import AsyncAnthropic, RateLimitError

from app.config import settings
from app.models.user import UserProfile
from app.schemas.job import RawJob
from app.utils.aliases import ROLE_ALIASES, expand_role
from app.utils.usage import record_usage_in_new_session

_anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY or "not-set")
logger = logging.getLogger(__name__)
_REACT_SEMAPHORE = asyncio.Semaphore(1)

_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "company_ats_registry.json"
_REACT_MODEL = "claude-haiku-4-5-20251001"
_MAX_REACT_ITERATIONS = 10
_CONTEXT_TRIM_AT = 4
_WEB_SEARCH_MAX_USES = 3
_KEEP_SEARCH_RESULTS_LAST_N = 1
_REACT_TIMEOUT_SECONDS = 180


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


def _job_hash(company: str, title: str) -> str:
    def _norm(value: str) -> str:
        return re.sub(r"[^\w]", "", value.lower().strip())

    key = f"{_norm(company)}::{_norm(title)}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _filter_seen(jobs: list[RawJob], seen_hashes: set[str]) -> list[RawJob]:
    if not seen_hashes:
        return jobs
    kept = []
    for job in jobs:
        job_key = _job_hash(job.company or "", job.title or "")
        if job_key in seen_hashes:
            logger.debug("filter_seen dropped company=%s title=%s hash=%s", job.company, job.title, job_key)
        else:
            kept.append(job)
    logger.info("filter_seen before=%s after=%s", len(jobs), len(kept))
    return kept


def _filter_registry_by_domain(
    registry: list[dict[str, Any]],
    profile_domains: list[str] | None,
) -> list[dict[str, Any]]:
    if not profile_domains:
        return registry
    profile_set: set[str] = set()
    for domain in profile_domains:
        profile_set.add(domain.lower())
        profile_set.update(term.lower() for term in expand_role(domain))
        profile_set.update(token for token in re.split(r"\W+", domain.lower()) if token)
    matched = [
        entry
        for entry in registry
        if profile_set & {domain.lower() for domain in (entry.get("domains") or [])}
    ]
    if not matched:
        logger.info("discover registry_domain_filter no_match domains=%s returning_all=%s", profile_domains, len(registry))
        return registry
    logger.info("discover registry_domain_filter matched=%s total=%s", len(matched), len(registry))
    return matched


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
    except httpx.TimeoutException:
        logger.debug("fetch_greenhouse timeout token=%s", token)
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
    except httpx.TimeoutException:
        logger.debug("fetch_lever timeout token=%s", token)
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
    except httpx.TimeoutException:
        logger.debug("fetch_ashby timeout token=%s", token)
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


def _load_company_registry() -> list[dict[str, Any]]:
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
        {"type": "web_search_20250305", "name": "web_search", "max_uses": _WEB_SEARCH_MAX_USES},
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
    target_names = {company.get("name", "") for company in (getattr(profile, "target_companies", None) or []) if company.get("name")}
    target_names.update(name.strip() for name in _DEFAULT_BIGTECH.split(",") if name.strip())
    return _build_react_scout_prompt(profile, target_names)


def _build_react_scout_prompt(profile: UserProfile, exclude_companies: set[str]) -> str:
    role_terms = ", ".join(getattr(profile, "domains", None) or [])
    keywords = getattr(profile, "keywords", None) or ""
    if not role_terms and keywords:
        role_terms = ", ".join(k.strip() for k in keywords.split(",")[:3])
    for abbr, expansions in ROLE_ALIASES.items():
        if abbr in role_terms.lower():
            role_terms += ", " + ", ".join(sorted(expansions))

    pref_locations = ", ".join(getattr(profile, "preferred_locations", None) or ["Remote"])
    countries = ", ".join(getattr(profile, "countries", None) or [])
    locations_str = ", ".join(filter(None, [pref_locations, countries])) or "Remote"
    seniority = getattr(profile, "seniority", None) or "mid-level"
    exclude_list = ", ".join(sorted(exclude_companies)) if exclude_companies else "none"

    return f"""You are a company discovery agent. Your ONLY job is to find company names that are hiring.

TARGET CANDIDATE:
- Roles: {role_terms or "software engineering"}
- Seniority: {seniority}
- Location: {locations_str} (or fully remote)

INSTRUCTIONS:
1. Use web_search to find companies actively hiring for {role_terms or "matching"} roles in {locations_str}.
2. Search job boards, startup lists, LinkedIn hiring posts, Y Combinator, Wellfound, Otta, AngelList.
3. For each promising company you find, immediately call company_lookup with the company name.
4. Do NOT output job listings. Do NOT output JSON. Your text output should only be brief search reasoning.
5. Focus on startups and mid-size companies. Skip big tech.

ALREADY COVERED - skip these: {exclude_list}

Good search queries to try:
- "{role_terms} jobs hiring {pref_locations} startup 2026"
- "companies hiring {role_terms} {pref_locations} site:wellfound.com OR site:ycombinator.com"
- "{role_terms} job openings {pref_locations} series B OR series C"

Call company_lookup for every promising company name you discover. That is your primary output."""


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


_SEARCH_BLOCK_TYPES = {"server_tool_use", "web_search_tool_result"}


def _prune_search_results(messages: list[dict[str, Any]], keep_last_n: int) -> None:
    """Drop bulky web-search blocks from older turns in place.

    Server-side web search embeds ``server_tool_use`` + ``web_search_tool_result``
    blocks (with large ``encrypted_content`` blobs) directly in the assistant
    message, and the whole history is resent every iteration — that is the token
    hog that trips the rate limit. We keep the search blocks for the most recent
    ``keep_last_n`` search turns and strip them from older turns, leaving the
    model's own reasoning text (and any company_lookup ``tool_use`` blocks, which
    must stay to pair with their ``tool_result``) intact.
    """
    search_turn_indices = [
        idx
        for idx, message in enumerate(messages)
        if isinstance(message.get("content"), list)
        and any(isinstance(b, dict) and b.get("type") in _SEARCH_BLOCK_TYPES for b in message["content"])
    ]
    prune_indices = set(search_turn_indices[:-keep_last_n] if keep_last_n else search_turn_indices)
    for idx in prune_indices:
        kept = [
            block
            for block in messages[idx]["content"]
            if not (isinstance(block, dict) and block.get("type") in _SEARCH_BLOCK_TYPES)
        ]
        # Never leave an assistant turn with empty content — the API rejects it.
        if not kept:
            kept = [{"type": "text", "text": "(searched; results elided)"}]
        messages[idx]["content"] = kept


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


def _trim_to_summary(found_jobs: list[RawJob], profile: UserProfile, exclude_companies: set[str]) -> list[dict[str, Any]]:
    companies = sorted({job.company for job in found_jobs if job.company})[:30]
    remaining = ", ".join(getattr(profile, "domains", None) or []) or (getattr(profile, "keywords", None) or "matching roles")
    summary = (
        f"So far found {len(found_jobs)} jobs at: {', '.join(companies) or 'no companies yet'}. "
        f"Continue searching for gaps in: {remaining}."
    )
    return [
        {"role": "user", "content": _build_react_scout_prompt(profile, exclude_companies)},
        {"role": "assistant", "content": [{"type": "text", "text": summary}]},
    ]


async def _run_react_search_agent_inner(profile: UserProfile, exclude_companies: set[str]) -> list[RawJob]:
    user_id = getattr(profile, "user_id", None)
    messages: list[dict[str, Any]] = [{"role": "user", "content": _build_react_scout_prompt(profile, exclude_companies)}]
    found_jobs: list[RawJob] = []

    async with httpx.AsyncClient() as client:
        for iteration in range(_MAX_REACT_ITERATIONS):
            logger.info("discover status=react_iteration_start user_id=%s iteration=%s", user_id, iteration)
            _prune_search_results(messages, _KEEP_SEARCH_RESULTS_LAST_N)
            for _attempt in range(4):
                try:
                    response = await _anthropic.messages.create(
                        model=_REACT_MODEL,
                        max_tokens=2000,
                        tools=_react_tools(),
                        messages=copy.deepcopy(messages),
                    )
                    break
                except RateLimitError:
                    if _attempt == 3:
                        raise
                    wait = 15 * (2 ** _attempt)
                    logger.warning("discover rate_limit user_id=%s attempt=%s/%s sleeping=%ss", user_id, _attempt + 1, 4, wait)
                    await asyncio.sleep(wait)
            else:
                raise RuntimeError("unreachable")
            if user_id:
                await record_usage_in_new_session(
                    response=response,
                    user_id=user_id,
                    stage="discover",
                    provider="anthropic",
                    model=_REACT_MODEL,
            )
            messages.append({"role": "assistant", "content": _content_blocks_for_messages(getattr(response, "content", []))})

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
                messages = _trim_to_summary(found_jobs, profile, exclude_companies)

    return found_jobs


async def _run_react_search_agent(
    profile: UserProfile,
    exclude_companies: set[str] | None = None,
) -> list[RawJob]:
    if not settings.ENABLE_REACT_SEARCH:
        logger.info("discover status=search_skipped reason=react_disabled user_id=%s", getattr(profile, "user_id", None))
        return []
    if not settings.ANTHROPIC_API_KEY:
        logger.info("discover status=search_skipped reason=missing_anthropic_api_key user_id=%s", getattr(profile, "user_id", None))
        return []
    try:
        async with _REACT_SEMAPHORE:
            return await asyncio.wait_for(
                _run_react_search_agent_inner(profile, exclude_companies or set()),
                timeout=_REACT_TIMEOUT_SECONDS,
            )
    except asyncio.TimeoutError:
        logger.warning("discover status=react_timeout user_id=%s timeout=%s", getattr(profile, "user_id", None), _REACT_TIMEOUT_SECONDS)
        return []
    except Exception:
        logger.exception("react search agent failed user_id=%s", getattr(profile, "user_id", None))
        return []


async def discover_jobs(
    profile: UserProfile,
    seen_hashes: set[str] | None = None,
) -> list[RawJob]:
    from app.pipeline.jsearch import run_jsearch

    user_id = getattr(profile, "user_id", None)
    logger.info("discover status=start user_id=%s target_companies=%s", user_id, len(profile.target_companies or []))
    ats_tasks = []
    registry = _filter_registry_by_domain(_load_company_registry(), getattr(profile, "domains", None))
    seen_registry_keys = {
        (company.get("ats", ""), company.get("token", ""))
        for company in profile.target_companies or []
        if company.get("ats") and company.get("token")
    }
    known_company_names = {
        company.get("name", "")
        for company in (profile.target_companies or []) + registry
        if company.get("name")
    }

    async with httpx.AsyncClient() as client:
        if settings.ENABLE_ATS_SEARCH:
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
        else:
            logger.info("discover status=ats_skipped reason=ats_disabled user_id=%s", user_id)

        ats_results, jsearch_results, search_results = await asyncio.gather(
            asyncio.gather(*ats_tasks, return_exceptions=True) if ats_tasks else asyncio.sleep(0, result=[]),
            run_jsearch(profile, client, api_key=settings.JSEARCH_API_KEY),
            _run_react_search_agent(profile, exclude_companies=known_company_names),
        )

    all_jobs: list[RawJob] = []
    for result in ats_results:
        if isinstance(result, list):
            all_jobs.extend(result)
        else:
            logger.debug("discover_jobs ats result exception=%r", result)
    all_jobs.extend(jsearch_results)
    all_jobs.extend(search_results)
    unique = _dedup_jobs(all_jobs)
    before_seen = len(unique)
    if seen_hashes:
        unique = _filter_seen(unique, seen_hashes)
    logger.info(
        "discover status=complete user_id=%s raw=%s unique=%s after_seen_filter=%s",
        user_id,
        len(all_jobs),
        before_seen,
        len(unique),
    )
    return unique
