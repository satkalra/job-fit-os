import re
from datetime import datetime

from app.schemas.job import RawJob
from app.utils.aliases import ROLE_ALIASES


def _tokenize(text: str) -> set[str]:
    text = text.lower()
    for abbr, expansions in ROLE_ALIASES.items():
        text = re.sub(r"\b" + re.escape(abbr) + r"\b", " ".join(sorted(expansions)), text)
    text = re.sub(r"[^\w\s]", " ", text)
    return {w for w in text.split() if len(w) > 3}


def keyword_overlap_score(resume: str, job_description: str) -> float:
    resume_tokens = _tokenize(resume)
    jd_tokens = _tokenize(job_description)
    if not resume_tokens or not jd_tokens:
        return 0.0
    overlap_resume_to_jd = len(resume_tokens & jd_tokens) / len(resume_tokens)
    overlap_jd_to_resume = len(jd_tokens & resume_tokens) / len(jd_tokens)
    return 0.6 * overlap_resume_to_jd + 0.4 * overlap_jd_to_resume


_JUNIOR_TERMS = {"intern", "internship", "junior", "entry", "entry-level", "entrylevel"}


def _is_too_old(posted_date: str | None) -> bool:
    if not posted_date:
        return False
    cleaned = posted_date.strip()
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            return (datetime.now() - dt).days > 30
        except ValueError:
            pass
    return False


def gate_filter(jobs: list[RawJob], seniority: str | None, min_salary: int | None) -> list[RawJob]:
    kept = []
    for job in jobs:
        title_lower = (job.title or "").lower()
        if seniority == "senior" and any(t in title_lower for t in _JUNIOR_TERMS):
            continue
        salary_floor = min_salary if min_salary is not None else 80000
        if job.salary_max is not None and job.salary_max < salary_floor:
            continue
        if _is_too_old(job.posted_date):
            continue
        kept.append(job)
    return kept
