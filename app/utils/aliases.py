import re

LOCATION_ALIASES: dict[str, set[str]] = {
    "nyc": {"new york", "new york city", "manhattan", "brooklyn", "queens"},
    "sf": {"san francisco", "bay area", "south bay", "silicon valley"},
    "la": {"los angeles", "socal", "southern california"},
    "dc": {"washington dc", "washington d c", "dmv"},
    "boston": {"cambridge", "ma"},
    "seattle": {"bellevue", "redmond"},
    "chicago": {"chi town"},
    "austin": {"atx"},
    "denver": {"colorado"},
    "miami": {"south florida"},
    "remote": {"distributed", "work from home", "wfh", "anywhere", "fully remote"},
}

ROLE_ALIASES: dict[str, set[str]] = {
    "swe": {"software engineer", "software developer", "software development"},
    "ml": {"machine learning", "ml engineer", "mlops"},
    "ai": {"artificial intelligence", "ai engineer"},
    "pm": {"product manager", "product management"},
    "ds": {"data scientist", "data science"},
    "de": {"data engineer", "data engineering"},
    "fe": {"frontend", "front-end", "front end"},
    "be": {"backend", "back-end", "back end"},
    "devops": {"platform engineer", "infrastructure", "sre", "site reliability"},
    "em": {"engineering manager", "eng manager"},
}

COMPANY_SUFFIXES: set[str] = {
    "inc",
    "incorporated",
    "ltd",
    "limited",
    "llc",
    "corp",
    "corporation",
    "co",
    "company",
    "group",
    "labs",
    "technologies",
}


def _normalize_text(value: str) -> str:
    value = re.sub(r"[^\w\s]", " ", value.lower())
    return " ".join(value.split())


def normalize_company(name: str) -> str:
    name = _normalize_text(name)
    tokens = [token for token in name.split() if token not in COMPANY_SUFFIXES]
    return " ".join(tokens).strip()


def expand_location(s: str) -> set[str]:
    s = _normalize_text(s)
    if s in LOCATION_ALIASES:
        return {s} | LOCATION_ALIASES[s]
    for key, aliases in LOCATION_ALIASES.items():
        if key in s or any(alias in s for alias in aliases):
            return {key} | aliases
    return {s}


def expand_role(s: str) -> set[str]:
    s = _normalize_text(s)
    if s in ROLE_ALIASES:
        return {s} | ROLE_ALIASES[s]
    for key, aliases in ROLE_ALIASES.items():
        if s == key or s in {_normalize_text(alias) for alias in aliases}:
            return {key} | aliases
    return {s}
