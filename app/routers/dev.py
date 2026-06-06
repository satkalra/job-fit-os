import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import JobResult
from app.models.user import User, UserProfile
from app.pipeline.discover import discover_jobs
from app.pipeline.score import score_jobs_debug
from app.schemas.job import ScoredJob
from app.services.email import send_briefing_email, send_rewrite_email

router = APIRouter(prefix="/dev", tags=["dev"])
logger = logging.getLogger(__name__)


@router.post("/send-briefing/{user_id}")
async def dev_send_briefing(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Trigger a full discover→score→email run for a user right now."""
    logger.info("dev_send_briefing requested user_id=%s", user_id)
    result = await db.execute(
        select(User, UserProfile)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(User.id == user_id)
    )
    row = result.one_or_none()
    if not row:
        logger.info("dev_send_briefing user_not_found user_id=%s", user_id)
        raise HTTPException(404, "User not found")

    user, profile = row
    if not profile.resume_text:
        logger.info("dev_send_briefing missing_resume user_id=%s", user_id)
        raise HTTPException(422, "No resume on file. Upload via /users/{id}/resume/text first.")

    jobs = await discover_jobs(profile)
    logger.info("dev_send_briefing status=discovered user_id=%s jobs=%s", user_id, len(jobs))
    scored, pipeline = await score_jobs_debug(jobs, profile, profile.resume_text)
    logger.info("dev_send_briefing status=scored user_id=%s pipeline=%s", user_id, pipeline)
    sent = await send_briefing_email(user, scored)
    logger.info("dev_send_briefing email_sent=%s user_id=%s", sent, user_id)

    return {
        "pipeline": pipeline,
        "email_sent": sent,
        "sent_to": user.email,
        "top_jobs": [
            {"title": j.title, "company": j.company, "score": j.global_score, "verdict": j.verdict}
            for j in scored[:5]
        ],
    }


@router.post("/send-rewrite/{user_id}/{job_id}")
async def dev_send_rewrite(
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a Rewacto rewrite + email for a specific stored job result."""
    logger.info("dev_send_rewrite requested user_id=%s job_id=%s", user_id, job_id)
    result = await db.execute(
        select(User, UserProfile)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(User.id == user_id)
    )
    row = result.one_or_none()
    if not row:
        logger.info("dev_send_rewrite user_not_found user_id=%s", user_id)
        raise HTTPException(404, "User not found")
    user, profile = row

    job_result = await db.execute(select(JobResult).where(JobResult.id == job_id))
    job_row = job_result.scalar_one_or_none()
    if not job_row:
        logger.info("dev_send_rewrite job_not_found user_id=%s job_id=%s", user_id, job_id)
        raise HTTPException(404, "Job result not found")

    if not profile.resume_text:
        logger.info("dev_send_rewrite missing_resume user_id=%s", user_id)
        raise HTTPException(422, "No resume on file.")

    from app.pipeline.rewacto import rewacto_rewrite

    job = ScoredJob(
        title=job_row.title or "",
        company=job_row.company or "",
        location=job_row.location,
        description=job_row.description,
        url=job_row.url,
        source=job_row.source or "ats",
        global_score=job_row.global_score or 0,
        verdict=job_row.verdict or "apply",
        scores=job_row.scores or {},
        red_flags=job_row.red_flags or [],
        citations=job_row.citations or [],
        summary=job_row.summary or "",
    )

    result = await rewacto_rewrite(profile.resume_text, job)
    logger.info("dev_send_rewrite status=rewritten markdown_chars=%s docx_bytes=%s gaps=%s", len(result.markdown), len(result.docx_bytes), len(result.gaps))
    sent = await send_rewrite_email(user, job, result.docx_bytes)
    logger.info("dev_send_rewrite email_sent=%s user_id=%s job_id=%s", sent, user_id, job_id)

    return {"email_sent": sent, "sent_to": user.email, "job": f"{job.title} at {job.company}"}


@router.get("/users")
async def dev_list_users(db: AsyncSession = Depends(get_db)):
    """List all users with their IDs — for finding user_id to test with."""
    logger.debug("dev_list_users requested")
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [{"id": str(u.id), "email": u.email, "name": u.name} for u in users]


@router.get("/jobs/{user_id}")
async def dev_list_jobs(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List recent job results for a user — for finding job_id to rewrite."""
    logger.debug("dev_list_jobs requested user_id=%s", user_id)
    result = await db.execute(
        select(JobResult)
        .where(JobResult.user_id == user_id)
        .order_by(JobResult.created_at.desc())
        .limit(10)
    )
    jobs = result.scalars().all()
    return [
        {"id": str(j.id), "title": j.title, "company": j.company, "verdict": j.verdict, "score": j.global_score}
        for j in jobs
    ]


@router.delete("/reset-results/{user_id}")
async def dev_reset_results(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete today's JobResult rows for a user so the scheduler (and /send-briefing) can re-run."""
    logger.info("dev_reset_results requested user_id=%s", user_id)
    result = await db.execute(
        delete(JobResult).where(
            JobResult.user_id == user_id,
            JobResult.run_date == date.today(),
        )
    )
    await db.commit()
    deleted = result.rowcount
    logger.info("dev_reset_results deleted=%s user_id=%s", deleted, user_id)
    return {"deleted_today_results": deleted, "user_id": str(user_id)}
