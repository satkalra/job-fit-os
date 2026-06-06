import logging
import re

from app.schemas.resume import EducationEntry, JobEntry, ProjectEntry, ResumeStructure

logger = logging.getLogger(__name__)

SECTION_ALIASES = {
    "summary": {"summary", "professional summary", "profile", "objective", "about"},
    "experience": {
        "experience", "professional experience", "work experience", "employment",
        "relevant experience", "work history", "career history", "employment history",
    },
    "projects": {
        "projects", "selected projects", "project experience", "technical projects",
        "personal projects", "key projects", "notable projects",
    },
    "skills": {
        "skills", "technical skills", "core skills", "competencies",
        "technical competencies", "technologies", "tools",
    },
    "education": {"education", "academic background", "academic history", "qualifications"},
}

# Pre-compute compact (no-space) versions of all aliases for PDF artifact matching
_COMPACT_ALIASES: dict[str, set[str]] = {
    name: {a.replace(" ", "") for a in aliases}
    for name, aliases in SECTION_ALIASES.items()
}

_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_RE = re.compile(
    r"(?i)"
    # Year-anchored range: "Jan 2024 – Present", "2024 – 2025"
    r"\b" + _MON + r"?\.?\s*\d{4}\s*(?:-|–|—|to)\s*(?:present|current|" + _MON + r"?\.?\s*\d{4})"
    r"|"
    r"\b\d{4}\s*(?:-|–|—|to)\s*(?:present|current|\d{4})\b"
    r"|"
    # Month-range-then-year: "July – August 2025", "Nov – Dec 2024"
    r"\b" + _MON + r"\s*(?:-|–|—|to)\s*" + _MON + r"\s+\d{4}\b"
)
BULLET_RE = re.compile(r"^\s*(?:[•\-*]|\d+\.)\s+")


def parse_resume(text: str) -> ResumeStructure:
    lines = [line.rstrip() for line in text.splitlines()]
    non_empty = [line.strip() for line in lines if line.strip()]
    name = non_empty[0] if non_empty else ""
    contact = non_empty[1] if len(non_empty) > 1 and _looks_like_contact(non_empty[1]) else ""
    sections = _split_sections(lines)

    result = ResumeStructure(
        name=name,
        contact=contact,
        summary="\n".join(sections.get("summary", [])).strip(),
        jobs=_parse_jobs(sections.get("experience", [])),
        projects=_parse_projects(sections.get("projects", [])),
        skills=_parse_skills(sections.get("skills", [])),
        education=_parse_education(sections.get("education", [])),
    )
    logger.debug(
        "parse_resume complete chars=%s sections=%s jobs=%s projects=%s skills=%s education=%s",
        len(text),
        list(sections.keys()),
        len(result.jobs),
        len(result.projects),
        len(result.skills),
        len(result.education),
    )
    return result


def _looks_like_contact(line: str) -> bool:
    return bool(re.search(r"@|linkedin|github|www|https?://|\d{3}", line, re.I))


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        section = _section_name(line)
        if section:
            current = section
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    return sections


def _section_name(line: str) -> str | None:
    normalized = re.sub(r"[:\s]+$", "", line).strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    # compact: collapse all spaces to handle PDF artifacts like "EXPERI ENCE", "SEL ECT ED PRO JECT S"
    compact = normalized.replace(" ", "")
    for name, aliases in SECTION_ALIASES.items():
        if normalized in aliases or compact in _COMPACT_ALIASES[name]:
            return name
    return None


def _parse_jobs(lines: list[str]) -> list[JobEntry]:
    jobs: list[JobEntry] = []
    current: dict | None = None
    for line in lines:
        if _is_bullet(line):
            if current is not None:
                current["bullets"].append(_clean_bullet(line))
            continue
        if _looks_like_entry_header(line):
            if current:
                jobs.append(JobEntry(**current))
            current = _job_from_header(line)
            continue
        if current is None:
            continue
        if not current["location"] and _looks_like_location(line):
            current["location"] = line
        elif not current["dates"] and DATE_RE.search(line):
            current["dates"] = DATE_RE.search(line).group(0)
        elif not current["company"]:
            current["company"] = line
    if current:
        jobs.append(JobEntry(**current))
    return jobs


def _parse_projects(lines: list[str]) -> list[ProjectEntry]:
    projects: list[ProjectEntry] = []
    current: dict | None = None
    for line in lines:
        if _is_bullet(line):
            if current is not None:
                current["bullets"].append(_clean_bullet(line))
            continue
        date_match = DATE_RE.search(line)
        is_header = date_match or "|" in line
        if is_header:
            if current:
                projects.append(ProjectEntry(**current))
            if date_match:
                name = line[:date_match.start()].strip().rstrip("-–— ").strip()
                dates = date_match.group(0)
            else:
                parts = _split_header(line)
                name = parts[0] if parts else line
                dates = _extract_dates(parts[-1]) if len(parts) > 1 else ""
            current = {"name": name or line, "dates": dates, "bullets": []}
        elif current and current["bullets"]:
            # wrapped continuation of previous bullet (PDF line-wrap artifact)
            current["bullets"][-1] += " " + line
        elif not current:
            current = {"name": line, "dates": "", "bullets": []}
    if current:
        projects.append(ProjectEntry(**current))
    return projects


def _parse_skills(lines: list[str]) -> list[str]:
    skills: list[str] = []
    for line in lines:
        cleaned = _clean_bullet(line)
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1]
        skills.extend(part.strip() for part in re.split(r"[,|;]", cleaned) if part.strip())
    return skills


def _parse_education(lines: list[str]) -> list[EducationEntry]:
    entries: list[EducationEntry] = []
    for line in lines:
        parts = _split_header(line)
        if len(parts) >= 2:
            dates = _extract_dates(parts[-1])
            location = parts[2] if len(parts) > 3 else ""
            entries.append(EducationEntry(degree=parts[0], school=parts[1], location=location, dates=dates))
    if not entries and lines:
        block = " ".join(lines)
        entries.append(EducationEntry(
            degree=lines[0],
            school=lines[1] if len(lines) > 1 else "",
            location="",
            dates=_extract_dates(block),
        ))
    return entries


def _looks_like_entry_header(line: str) -> bool:
    return "|" in line or bool(DATE_RE.search(line))


def _job_from_header(line: str) -> dict:
    parts = _split_header(line)
    title = parts[0] if len(parts) > 0 else ""
    company = parts[1] if len(parts) > 1 else ""
    location = parts[2] if len(parts) > 2 else ""
    dates = parts[3] if len(parts) > 3 else _extract_dates(line)
    # handle "Location DateRange" merged in last part e.g. "Tysons, VA July 2024 - Present"
    if len(parts) == 3:
        date_match = DATE_RE.search(parts[2])
        if date_match:
            dates = date_match.group(0)
            loc_raw = parts[2][:date_match.start()].strip().rstrip(",").strip()
            # strip any trailing standalone month name left by the year-first regex match
            location = re.sub(
                r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december"
                r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s*$",
                "",
                loc_raw,
                flags=re.I,
            ).strip().rstrip(",").strip()
    return {"title": title, "company": company, "location": location, "dates": dates, "bullets": []}


def _split_header(line: str) -> list[str]:
    if "|" in line:
        return [part.strip() for part in line.split("|") if part.strip()]
    if " - " in line:
        return [part.strip() for part in line.split(" - ") if part.strip()]
    return [line.strip()]


def _extract_dates(line: str) -> str:
    match = DATE_RE.search(line)
    return match.group(0) if match else ""


def _is_bullet(line: str) -> bool:
    return bool(BULLET_RE.match(line))


def _clean_bullet(line: str) -> str:
    return BULLET_RE.sub("", line).strip()


def _looks_like_location(line: str) -> bool:
    return bool(re.search(r",\s*[A-Z]{2}\b|remote|hybrid|united states", line, re.I))
