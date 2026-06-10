from pydantic import BaseModel, Field, model_validator


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


class ApplyResponse(BaseModel):
    job_id: str
    status: str
    applied_at: str | None


class CustomJobScoreRequest(BaseModel):
    job_description: str | None = None
    url: str | None = None
    title: str | None = None
    company: str | None = None

    @model_validator(mode="after")
    def url_or_job_description_required(self) -> "CustomJobScoreRequest":
        if not (self.url and self.url.strip()) and not (self.job_description and self.job_description.strip()):
            raise ValueError("url or job_description is required")
        return self


class CustomJobScoreResponse(BaseModel):
    global_score: int
    verdict: str
    scores: dict
    red_flags: list
    citations: list
    summary: str
    rewrite_url: str | None = None
