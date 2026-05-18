import re

from app.schemas.resume import EducationEntry, JobEntry, ProjectEntry, ResumeStructure

SECTION_ALIASES = {
    "summary": {"summary", "professional summary", "profile"},
    "experience": {"experience", "professional experience", "work experience", "employment"},
    "projects": {"projects", "selected projects", "project experience"},
    "skills": {"skills", "technical skills", "core skills"},
    "education": {"education", "academic background"},
}

DATE_RE = re.compile(
    r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)?\.?\s*\d{4}\s*(?:-|–|—|to)\s*(?:present|current|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)?\.?\s*\d{4})|\b\d{4}\s*(?:-|–|—|to)\s*(?:present|current|\d{4})\b"
)
BULLET_RE = re.compile(r"^\s*(?:[•\-*]|\d+\.)\s+")


def parse_resume(text: str) -> ResumeStructure:
    """Best-effort resume parser that preserves structure when it can.

    The parser is intentionally conservative. It returns empty structured
    sections instead of raising when a resume layout is unfamiliar.
    """
    lines = [line.rstrip() for line in text.splitlines()]
    non_empty = [line.strip() for line in lines if line.strip()]
    name = non_empty[0] if non_empty else ""
    contact = non_empty[1] if len(non_empty) > 1 and _looks_like_contact(non_empty[1]) else ""
    sections = _split_sections(lines)

    return ResumeStructure(
        name=name,
        contact=contact,
        summary="\n".join(sections.get("summary", [])).strip(),
        jobs=_parse_jobs(sections.get("experience", [])),
        projects=_parse_projects(sections.get("projects", [])),
        skills=_parse_skills(sections.get("skills", [])),
        education=_parse_education(sections.get("education", [])),
    )


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
    for name, aliases in SECTION_ALIASES.items():
        if normalized in aliases:
            return name
    if line.isupper():
        return next((name for name, aliases in SECTION_ALIASES.items() if normalized.title().lower() in aliases), None)
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
        if _looks_like_entry_header(line) or not current:
            if current:
                projects.append(ProjectEntry(**current))
            parts = _split_header(line)
            name = parts[0] if parts else line
            dates = _extract_dates(parts[-1] if parts else line)
            current = {"name": name, "dates": dates, "bullets": []}
            continue
        if current and not current["dates"] and DATE_RE.search(line):
            current["dates"] = DATE_RE.search(line).group(0)
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
        entries.append(EducationEntry(degree=lines[0], school=lines[1] if len(lines) > 1 else "", location="", dates=_extract_dates(block)))
    return entries


def _looks_like_entry_header(line: str) -> bool:
    return "|" in line or bool(DATE_RE.search(line))


def _job_from_header(line: str) -> dict:
    parts = _split_header(line)
    title = parts[0] if len(parts) > 0 else ""
    company = parts[1] if len(parts) > 1 else ""
    location = parts[2] if len(parts) > 2 else ""
    dates = parts[3] if len(parts) > 3 else _extract_dates(line)
    if len(parts) == 3 and DATE_RE.search(parts[2]):
        location = ""
        dates = parts[2]
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
