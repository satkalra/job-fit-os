import asyncio
import json
import uuid

from anthropic import AsyncAnthropic

from app.config import settings
from app.models.user import UserProfile
from app.schemas.job import RawJob, ScoredJob
from app.utils.scoring import gate_filter, keyword_overlap_score
from app.utils.token import generate_rewrite_token

_anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY or "not-set")
_SEVERITY_PENALTY = {"low": 2, "med": 5, "high": 15}


def _validate_weights(profile: UserProfile) -> None:
    total = (
        profile.weight_role_match
        + profile.weight_skills_match
        + profile.weight_experience_level
        + profile.weight_compensation
        + profile.weight_cultural
    )
    if abs(total - 1.0) > 0.05:
        raise ValueError(f"Profile weights must sum to 1.0, got {total:.4f}")


def _compute_weighted_score(scores: dict, profile: UserProfile) -> float:
    return (
        (scores["roleMatch"] / 5) * profile.weight_role_match
        + (scores["skillsMatch"] / 5) * profile.weight_skills_match
        + (scores["experienceLevel"] / 5) * profile.weight_experience_level
        + (scores["compensation"] / 5) * profile.weight_compensation
        + (scores["cultural"] / 5) * profile.weight_cultural
    ) * 100


def _apply_red_flag_penalties(score: float, red_flags: list) -> float:
    penalty = sum(_SEVERITY_PENALTY.get(flag.get("severity", "low"), 2) for flag in red_flags)
    return score - penalty


def _score_to_verdict(score: float) -> str:
    if score >= 85:
        return "strong-apply"
    if score >= 70:
        return "apply"
    if score >= 55:
        return "maybe"
    return "skip"


async def _score_one_job(job: RawJob, profile: UserProfile, resume: str) -> ScoredJob:
    prompt = f"""You are a job-fit evaluator. Score this job for the candidate.

RESUME:
{resume[:3000]}

JOB TITLE: {job.title}
COMPANY: {job.company}
DESCRIPTION: {(job.description or '')[:2000]}

Return ONLY a JSON object with keys roleMatch, skillsMatch, experienceLevel, compensation, cultural, globalScore, verdict, redFlags, citations, summary."""
    response = await _anthropic.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    data = json.loads(text[text.find("{") : text.rfind("}") + 1])
    weighted = _compute_weighted_score(data, profile)
    final_score = max(0, int(round(_apply_red_flag_penalties(weighted, data.get("redFlags", [])))))
    job_id = uuid.uuid4()
    user_id = getattr(profile, "user_id", None)
    token = generate_rewrite_token(user_id, job_id) if user_id else None
    return ScoredJob(
        **job.model_dump(),
        global_score=final_score,
        verdict=_score_to_verdict(final_score),
        scores={
            "roleMatch": data["roleMatch"],
            "skillsMatch": data["skillsMatch"],
            "experienceLevel": data["experienceLevel"],
            "compensation": data["compensation"],
            "cultural": data["cultural"],
        },
        red_flags=data.get("redFlags", []),
        citations=data.get("citations", []),
        summary=data.get("summary", ""),
        rewrite_token=token,
    )


async def score_jobs(jobs: list[RawJob], profile: UserProfile, resume: str) -> list[ScoredJob]:
    _validate_weights(profile)
    gated = gate_filter(jobs, profile.seniority, profile.min_salary)
    keyword_filtered = [
        job
        for job in gated
        if keyword_overlap_score(resume, f"{job.description or ''} {job.title or ''}") >= 0.08
    ]
    scored = await asyncio.gather(*[_score_one_job(job, profile, resume) for job in keyword_filtered[:10]])
    results = [job for job in scored if job.verdict != "skip"]
    results.sort(key=lambda job: job.global_score, reverse=True)
    return results
