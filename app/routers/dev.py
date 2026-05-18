import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User, UserProfile
from app.models.job import JobResult
from app.schemas.job import ScoredJob
from app.services.email import send_briefing_email, send_rewrite_email
from app.services.docx_builder import build_resume_docx
from app.pipeline.discover import discover_jobs
from app.pipeline.score import score_jobs

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/send-briefing/{user_id}")
async def dev_send_briefing(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Trigger a full discover→score→email run for a user right now."""
    result = await db.execute(
        select(User, UserProfile)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(User.id == user_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, "User not found")

    user, profile = row
    if not profile.resume_text:
        raise HTTPException(422, "No resume on file. Upload via /users/{id}/resume/text first.")

    jobs = await discover_jobs(profile)
    scored = await score_jobs(jobs, profile, profile.resume_text)
    sent = await send_briefing_email(user, scored)

    return {
        "jobs_found": len(jobs),
        "jobs_scored": len(scored),
        "email_sent": sent,
        "sent_to": user.email,
    }


@router.post("/send-rewrite/{user_id}/{job_id}")
async def dev_send_rewrite(
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a Rewacto rewrite + email for a specific stored job result."""
    result = await db.execute(
        select(User, UserProfile)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(User.id == user_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, "User not found")
    user, profile = row

    job_result = await db.execute(select(JobResult).where(JobResult.id == job_id))
    job_row = job_result.scalar_one_or_none()
    if not job_row:
        raise HTTPException(404, "Job result not found")

    if not profile.resume_text:
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

    tailored_md = await rewacto_rewrite(profile.resume_text, job)
    docx_bytes = build_resume_docx(tailored_md, user.name or user.email, job)
    sent = await send_rewrite_email(user, job, docx_bytes)

    return {"email_sent": sent, "sent_to": user.email, "job": f"{job.title} at {job.company}"}


@router.get("/users")
async def dev_list_users(db: AsyncSession = Depends(get_db)):
    """List all users with their IDs — for finding user_id to test with."""
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [{"id": str(u.id), "email": u.email, "name": u.name} for u in users]


@router.get("/jobs/{user_id}")
async def dev_list_jobs(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List recent job results for a user — for finding job_id to rewrite."""
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
