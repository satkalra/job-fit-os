import re
from datetime import datetime

from app.schemas.job import RawJob
from app.utils.aliases import ROLE_ALIASES, expand_location


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

# Titles a candidate is over-qualified to be matched against, split by how senior.
_HIGH_TERMS = {"staff", "principal", "director", "vp", "vice president", "head of", "distinguished", "architect"}
_SENIOR_TERMS = {"senior", "sr.", "sr ", "lead"} | _HIGH_TERMS

# Candidate seniority -> (terms to reject in titles, max years-of-experience the JD may demand)
_JUNIOR_LABELS = {"junior", "entry", "entry-level", "entry level", "intern", "internship", "new grad", "graduate"}
_MID_LABELS = {"mid", "mid-level", "mid level", "intermediate"}

_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*years?", re.IGNORECASE)

# Phrases that mean the employer will NOT sponsor a visa / requires existing authorization.
_NO_SPONSORSHIP_PHRASES = (
    "no sponsorship",
    "no visa sponsorship",
    "without sponsorship",
    "not provide sponsorship",
    "not provide visa sponsorship",
    "not able to provide sponsorship",
    "does not offer sponsorship",
    "do not offer sponsorship",
    "do not sponsor",
    "does not sponsor",
    "unable to sponsor",
    "cannot sponsor",
    "can not sponsor",
    "not sponsor visa",
    "citizens only",
    "citizenship required",
    "must be a citizen",
    "must have work authorization",
    "must be authorized to work",
    "active security clearance",
    "security clearance required",
)


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


def _over_senior(title_lower: str, seniority: str | None) -> bool:
    """True if the title is too senior for the candidate's level."""
    label = (seniority or "").lower().strip()
    if label in _JUNIOR_LABELS:
        return any(t in title_lower for t in _SENIOR_TERMS)
    if label in _MID_LABELS:
        return any(t in title_lower for t in _HIGH_TERMS)
    return False


# Salary above these thresholds confirms the role is genuinely at that senior level.
# Below (or absent) = requirement is likely puffed-up marketing; don't hard-block.
_SENIOR_SALARY_THRESHOLD = 140_000   # confirmed senior/staff if salary_max >= this
_MID_SALARY_THRESHOLD = 110_000      # confirmed mid-senior if salary_max >= this


def _years_too_high(text: str, seniority: str | None, salary_max: int | None = None) -> bool:
    """True if the JD demands years the candidate lacks AND salary confirms the level is real.

    Without salary info we can't verify the stated requirement is genuine (many JDs inflate
    years to deter applicants while paying junior rates). Pass to the scorer instead.
    """
    label = (seniority or "").lower().strip()
    if label in _JUNIOR_LABELS:
        # For junior candidates even mid-confirmed salary ($110k+) validates the years claim.
        cap, salary_threshold = 3, _MID_SALARY_THRESHOLD
    elif label in _MID_LABELS:
        # For mid candidates require senior-confirmed salary before blocking.
        cap, salary_threshold = 5, _SENIOR_SALARY_THRESHOLD
    else:
        return False
    if not any(int(m) > cap for m in _YEARS_RE.findall(text)):
        return False
    if salary_max is None:
        return False
    return salary_max >= salary_threshold


def _location_allowed(job: RawJob, preferred_locations, countries) -> bool:
    if not preferred_locations and not countries:
        return True
    loc = (job.location or "").lower()
    if not loc:
        return True  # unknown location: let the scorer decide rather than hard-drop
    job_locs = expand_location(loc)
    if "remote" in job_locs:
        return True
    for pref in preferred_locations or []:
        if job_locs & expand_location(pref.lower()):
            return True
    for country in countries or []:
        if country.lower() in loc:
            return True
    return False


def _needs_sponsorship_blocked(job: RawJob) -> bool:
    text = f"{job.title or ''} {job.description or ''}".lower()
    return any(phrase in text for phrase in _NO_SPONSORSHIP_PHRASES)


def gate_filter(
    jobs: list[RawJob],
    seniority: str | None = None,
    min_salary: int | None = None,
    preferred_locations: list[str] | None = None,
    countries: list[str] | None = None,
    needs_sponsorship: bool = False,
) -> list[RawJob]:
    kept = []
    for job in jobs:
        title_lower = (job.title or "").lower()
        if seniority == "senior" and any(t in title_lower for t in _JUNIOR_TERMS):
            continue
        if _over_senior(title_lower, seniority):
            continue
        if _years_too_high(f"{title_lower} {(job.description or '').lower()}", seniority, job.salary_max):
            continue
        salary_floor = min_salary if min_salary is not None else 80000
        if job.salary_max is not None and job.salary_max < salary_floor:
            continue
        if _is_too_old(job.posted_date):
            continue
        if not _location_allowed(job, preferred_locations, countries):
            continue
        if needs_sponsorship and _needs_sponsorship_blocked(job):
            continue
        kept.append(job)
    return kept
