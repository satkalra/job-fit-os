import asyncio
import json

import httpx
from anthropic import AsyncAnthropic

from app.config import settings
from app.models.user import UserProfile
from app.schemas.job import RawJob

_anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY or "not-set")


def _dedup_jobs(jobs: list[RawJob]) -> list[RawJob]:
    seen = set()
    unique = []
    for job in jobs:
        key = (job.company or "").lower() + "::" + (job.title or "")[:20].lower()
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


async def _fetch_greenhouse(token: str, client: httpx.AsyncClient) -> list[RawJob]:
    try:
        resp = await client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
            params={"content": "true"},
            timeout=4,
        )
        resp.raise_for_status()
        return [
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
    except Exception:
        return []


async def _fetch_lever(token: str, client: httpx.AsyncClient) -> list[RawJob]:
    try:
        resp = await client.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"}, timeout=4)
        resp.raise_for_status()
        return [
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
    except Exception:
        return []


async def _fetch_ashby(token: str, client: httpx.AsyncClient) -> list[RawJob]:
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
        return jobs
    except Exception:
        return []


async def _search_with_haiku(profile: UserProfile) -> list[RawJob]:
    if not settings.ANTHROPIC_API_KEY:
        return []
    try:
        domains_str = ", ".join(profile.domains or [])
        prompt = (
            f"Find 5 job postings posted in the last 7 days for roles in: {domains_str}. "
            f"Keywords: {profile.keywords or ''}. "
            "Return a JSON array with objects: {title, company, location, url, description, posted_date}. "
            "Return ONLY the JSON array, no other text."
        )
        response = await _anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            text = getattr(block, "text", "").strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                return [
                    RawJob(
                        title=j.get("title", ""),
                        company=j.get("company", ""),
                        location=j.get("location"),
                        url=j.get("url"),
                        description=j.get("description", ""),
                        posted_date=j.get("posted_date"),
                        source="ai",
                    )
                    for j in json.loads(text[start:end])
                ]
    except Exception:
        pass
    return []


async def discover_jobs(profile: UserProfile) -> list[RawJob]:
    ats_tasks = []
    async with httpx.AsyncClient() as client:
        for company in profile.target_companies or []:
            ats_type = company.get("ats", "")
            token = company.get("token", "")
            if ats_type == "greenhouse":
                ats_tasks.append(_fetch_greenhouse(token, client))
            elif ats_type == "lever":
                ats_tasks.append(_fetch_lever(token, client))
            elif ats_type == "ashby":
                ats_tasks.append(_fetch_ashby(token, client))

        ats_results, haiku_results = await asyncio.gather(
            asyncio.gather(*ats_tasks, return_exceptions=True) if ats_tasks else asyncio.sleep(0, result=[]),
            _search_with_haiku(profile),
        )

    all_jobs: list[RawJob] = []
    for result in ats_results:
        if isinstance(result, list):
            all_jobs.extend(result)
    all_jobs.extend(haiku_results)
    return _dedup_jobs(all_jobs)
