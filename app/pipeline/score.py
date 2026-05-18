import asyncio
import uuid

from anthropic import AsyncAnthropic

from app.config import settings
from app.models.user import UserProfile
from app.schemas.job import RawJob, ScoredJob
from app.utils.aliases import expand_location, normalize_company
from app.utils.scoring import gate_filter, keyword_overlap_score
from app.utils.token import generate_rewrite_token

_anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY or "not-set")
_SEVERITY_PENALTY = {"low": 2, "med": 5, "high": 15}

_SCORE_TOOL = {
    "name": "score_job",
    "description": "Return structured job-fit scores for the candidate.",
    "input_schema": {
        "type": "object",
        "properties": {
            "roleMatch":        {"type": "integer", "minimum": 1, "maximum": 5},
            "skillsMatch":      {"type": "integer", "minimum": 1, "maximum": 5},
            "experienceLevel":  {"type": "integer", "minimum": 1, "maximum": 5},
            "compensation":     {"type": "integer", "minimum": 1, "maximum": 5},
            "cultural":         {"type": "integer", "minimum": 1, "maximum": 5},
            "globalScore":      {"type": "integer", "minimum": 0, "maximum": 100},
            "verdict":          {"type": "string", "enum": ["strong-apply", "apply", "maybe", "skip"]},
            "redFlags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["low", "med", "high"]},
                        "reason":   {"type": "string"},
                    },
                    "required": ["severity", "reason"],
                },
            },
            "citations": {"type": "array", "items": {"type": "string"}},
            "summary":   {"type": "string"},
        },
        "required": [
            "roleMatch", "skillsMatch", "experienceLevel", "compensation", "cultural",
            "globalScore", "verdict", "redFlags", "citations", "summary",
        ],
    },
}


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
    penalty = sum(
        _SEVERITY_PENALTY.get(flag.get("severity", "low") if isinstance(flag, dict) else "low", 2)
        for flag in red_flags
    )
    return score - penalty


def _score_to_verdict(score: float) -> str:
    if score >= 85:
        return "strong-apply"
    if score >= 70:
        return "apply"
    if score >= 55:
        return "maybe"
    return "skip"


def _company_boost(job: RawJob, profile: UserProfile) -> float:
    job_co = normalize_company(job.company or "")
    for entry in profile.target_companies or []:
        if normalize_company(entry.get("name", "")) == job_co:
            return 10.0
    return 0.0


def _location_boost(job: RawJob, profile: UserProfile) -> float:
    if not profile.preferred_locations or not job.location:
        return 0.0
    job_locs = expand_location(job.location.lower())
    for pref in profile.preferred_locations:
        if job_locs & expand_location(pref.lower()):
            return 5.0
    return 0.0


async def _score_one_job(job: RawJob, profile: UserProfile, resume: str) -> ScoredJob:
    prompt = (
        f"You are a job-fit evaluator. Score this job for the candidate.\n\n"
        f"RESUME:\n{resume[:3000]}\n\n"
        f"JOB TITLE: {job.title}\n"
        f"COMPANY: {job.company}\n"
        f"DESCRIPTION: {(job.description or '')[:2000]}"
    )
    response = await _anthropic.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        tools=[_SCORE_TOOL],
        tool_choice={"type": "tool", "name": "score_job"},
        messages=[{"role": "user", "content": prompt}],
    )
    # tool_choice forces the first block to be a tool_use block; .input is already a dict
    data = response.content[0].input
    weighted = _compute_weighted_score(data, profile)
    weighted += _company_boost(job, profile)
    weighted += _location_boost(job, profile)
    weighted = min(weighted, 100.0)
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
