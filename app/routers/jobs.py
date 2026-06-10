import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.job import JobResult
from app.models.user import User, UserProfile
from app.pipeline.score import _score_one_job
from app.routers.users import _verify_management_token
from app.schemas.job import ApplyResponse, CustomJobScoreRequest, CustomJobScoreResponse, RawJob
from app.utils.scraper import fetch_job_description
from app.utils.token import generate_rewrite_token

router = APIRouter(tags=["jobs"])
logger = logging.getLogger(__name__)


@router.patch("/users/{user_id}/jobs/{job_id}/apply", response_model=ApplyResponse)
async def mark_job_applied(
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    authorization: str | None = Header(default=None),
):
    if not authorization:
        raise HTTPException(401, "Invalid management token")
    _verify_management_token(authorization.removeprefix("Bearer "), user_id)
    async with AsyncSessionLocal() as db:
        job = (
            await db.execute(select(JobResult).where(JobResult.id == job_id, JobResult.user_id == user_id))
        ).scalar_one_or_none()
        if not job:
            raise HTTPException(404, "Job not found")
        job.status = "applied"
        job.applied_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(job)
    return ApplyResponse(
        job_id=str(job.id),
        status=job.status,
        applied_at=job.applied_at.isoformat() if job.applied_at else None,
    )


@router.post("/users/{user_id}/jobs/score", response_model=CustomJobScoreResponse)
async def score_custom_job(
    user_id: uuid.UUID,
    body: CustomJobScoreRequest,
    authorization: str | None = Header(default=None),
):
    if not authorization:
        raise HTTPException(401, "Invalid management token")
    _verify_management_token(authorization.removeprefix("Bearer "), user_id)

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(User, UserProfile)
                .join(UserProfile, UserProfile.user_id == User.id)
                .where(User.id == user_id)
            )
        ).one_or_none()
        if not row:
            raise HTTPException(404, "User not found.")

        _, profile = row
        if not profile.resume_text:
            raise HTTPException(422, "No resume on file.")

        url = body.url.strip() if body.url else None
        pasted_description = body.job_description.strip() if body.job_description else None
        description = pasted_description
        if url:
            scraped = await fetch_job_description(url)
            if scraped:
                logger.info("score_custom scrape_success url=%s chars=%s", url, len(scraped))
                description = scraped
            else:
                logger.info("score_custom scrape_failed url=%s using_pasted=True", url)
                if not pasted_description:
                    raise HTTPException(422, "Could not fetch URL. Paste the job posting and try again.")

        raw_job = RawJob(
            title=body.title or "",
            company=body.company or "",
            description=description,
            url=url,
            source="custom",
        )
        scored = await _score_one_job(raw_job, profile, profile.resume_text)
        from app.pipeline.discover import _job_hash

        job_id = uuid.uuid4()
        token = generate_rewrite_token(user_id, job_id)
        job_row = JobResult(
            id=job_id,
            user_id=user_id,
            run_date=date.today(),
            title=scored.title or body.title,
            company=scored.company or body.company,
            location=scored.location,
            posted_date=scored.posted_date,
            salary=scored.salary,
            description=description,
            requirements=scored.requirements,
            tags=scored.tags,
            url=url,
            source="custom",
            global_score=scored.global_score,
            verdict=scored.verdict,
            scores=scored.scores,
            red_flags=scored.red_flags,
            citations=scored.citations,
            summary=scored.summary,
            rewrite_token=token,
            job_hash=_job_hash(scored.company or body.company or "", scored.title or body.title or ""),
        )
        db.add(job_row)
        await db.commit()
        logger.info(
            "score_custom complete user_id=%s job_id=%s score=%s verdict=%s",
            user_id,
            job_id,
            scored.global_score,
            scored.verdict,
        )

    return CustomJobScoreResponse(
        global_score=scored.global_score,
        verdict=scored.verdict,
        scores=scored.scores,
        red_flags=scored.red_flags,
        citations=scored.citations,
        summary=scored.summary,
        rewrite_url=f"/rewrite?token={token}",
    )
