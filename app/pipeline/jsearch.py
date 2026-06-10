import asyncio
import logging

import httpx

from app.models.user import UserProfile
from app.schemas.job import RawJob
from app.utils.aliases import ROLE_ALIASES

logger = logging.getLogger(__name__)

_JSEARCH_BASE = "https://jsearch.p.rapidapi.com/search"
_JSEARCH_HOST = "jsearch.p.rapidapi.com"


def _build_jsearch_queries(profile: UserProfile) -> list[str]:
    """Build up to three profile-tuned JSearch queries."""
    domains = getattr(profile, "domains", None) or []
    keywords = getattr(profile, "keywords", None) or ""
    seniority = (getattr(profile, "seniority", None) or "").lower()
    locations = getattr(profile, "preferred_locations", None) or []
    location_str = locations[0] if locations else "remote"

    expanded: list[str] = []
    for domain in domains[:4]:
        domain_lower = domain.lower()
        for abbr, expansions in ROLE_ALIASES.items():
            normalized_expansions = {expansion.lower() for expansion in expansions}
            if abbr == domain_lower or domain_lower in normalized_expansions:
                expanded.append(sorted(expansions)[0])
                break
        else:
            expanded.append(domain)

    if not expanded and keywords:
        expanded = [keyword.strip() for keyword in keywords.split(",")[:2] if keyword.strip()]
    if not expanded:
        expanded = ["software engineer"]

    queries: list[str] = []
    primary = expanded[0]
    seniority_prefix = seniority if seniority in {"senior", "junior", "mid", "lead"} else ""
    queries.append(" ".join(part for part in [seniority_prefix, primary, "in", location_str] if part))

    if len(expanded) > 1:
        queries.append(f"{expanded[1]} jobs {location_str}")
    elif keywords:
        keyword_terms = [keyword.strip() for keyword in keywords.split(",")[:2] if keyword.strip()]
        if keyword_terms:
            queries.append(f"{' '.join(keyword_terms)} {location_str}")

    if len(queries) < 3 and "remote" not in location_str.lower():
        queries.append(f"{primary} remote")

    return queries[:3]


async def _fetch_jsearch(
    query: str,
    api_key: str,
    client: httpx.AsyncClient,
    num_pages: int = 1,
    date_posted: str = "week",
) -> list[RawJob]:
    if not api_key:
        return []
    try:
        resp = await client.get(
            _JSEARCH_BASE,
            params={
                "query": query,
                "page": "1",
                "num_pages": str(num_pages),
                "date_posted": date_posted,
            },
            headers={
                "X-RapidAPI-Key": api_key,
                "X-RapidAPI-Host": _JSEARCH_HOST,
            },
            timeout=30,
        )
        resp.raise_for_status()
        jobs: list[RawJob] = []
        for item in resp.json().get("data", []):
            city = item.get("job_city") or ""
            state = item.get("job_state") or ""
            country = item.get("job_country") or ""
            location = ", ".join(part for part in [city, state, country] if part) or None
            salary_max = item.get("job_max_salary")
            salary_min = item.get("job_min_salary")
            salary = f"{salary_min or ''}-{salary_max or ''} USD" if salary_min or salary_max else None
            posted_date = (item.get("job_posted_at_datetime_utc") or "")[:10] or None
            jobs.append(
                RawJob(
                    title=item.get("job_title", ""),
                    company=item.get("employer_name", ""),
                    location=location,
                    url=item.get("job_apply_link") or item.get("job_google_link"),
                    description=item.get("job_description", ""),
                    salary=salary,
                    salary_max=int(salary_max) if salary_max else None,
                    posted_date=posted_date,
                    source="jsearch",
                )
            )
        logger.info("jsearch query=%r jobs=%s", query, len(jobs))
        return jobs
    except httpx.HTTPStatusError as exc:
        logger.warning("jsearch status=%s query=%r", exc.response.status_code, query)
        return []
    except httpx.TimeoutException:
        logger.warning("jsearch timeout query=%r", query)
        return []
    except Exception:
        logger.exception("jsearch failed query=%r", query)
        return []


async def run_jsearch(profile: UserProfile, client: httpx.AsyncClient, api_key: str) -> list[RawJob]:
    if not api_key:
        logger.info("jsearch skipped reason=missing_api_key")
        return []
    queries = _build_jsearch_queries(profile)
    batches = await asyncio.gather(*[_fetch_jsearch(query, api_key, client) for query in queries])
    jobs: list[RawJob] = []
    for batch in batches:
        jobs.extend(batch)
    logger.info("jsearch total_jobs=%s queries=%s", len(jobs), len(queries))
    return jobs
