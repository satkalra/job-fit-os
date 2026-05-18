from pydantic import BaseModel, Field


class RawJob(BaseModel):
    title: str
    company: str
    location: str | None = None
    posted_date: str | None = None
    salary: str | None = None
    salary_max: int | None = None
    description: str | None = None
    requirements: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    url: str | None = None
    source: str = "ats"


class ScoredJob(RawJob):
    global_score: int
    verdict: str
    scores: dict
    red_flags: list
    citations: list
    summary: str
    rewrite_token: str | None = None


class BriefingRunResult(BaseModel):
    jobs_found: int
    jobs_after_gates: int
    jobs_scored: int
    email_sent: bool
