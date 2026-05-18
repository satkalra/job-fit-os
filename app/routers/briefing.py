import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import JobResult
from app.models.user import User, UserProfile
from app.pipeline.discover import discover_jobs
from app.pipeline.score import score_jobs
from app.schemas.job import BriefingRunResult
from app.services.email import send_briefing_email
from app.utils.scoring import gate_filter

router = APIRouter(prefix="/briefing", tags=["briefing"])


@router.post("/run/{user_id}", response_model=BriefingRunResult)
async def run_briefing(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(User, UserProfile)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(User.id == user_id)
        )
    ).one_or_none()
    if not row:
        raise HTTPException(404, "User not found")
    user, profile = row
    if not profile.resume_text:
        raise HTTPException(422, "User has no resume. Upload via /resume/upload or /resume/text first.")

    jobs = await discover_jobs(profile)
    gated = gate_filter(jobs, profile.seniority, profile.min_salary)
    scored = await score_jobs(jobs, profile, profile.resume_text)
    for job in scored:
        db.add(
            JobResult(
                user_id=user.id,
                run_date=date.today(),
                title=job.title,
                company=job.company,
                location=job.location,
                posted_date=job.posted_date,
                salary=job.salary,
                description=job.description,
                requirements=job.requirements,
                tags=job.tags,
                url=job.url,
                source=job.source,
                global_score=job.global_score,
                verdict=job.verdict,
                scores=job.scores,
                red_flags=job.red_flags,
                citations=job.citations,
                summary=job.summary,
                rewrite_token=job.rewrite_token,
            )
        )
    await db.commit()
    email_sent = await send_briefing_email(user, scored)
    return BriefingRunResult(
        jobs_found=len(jobs),
        jobs_after_gates=len(gated),
        jobs_scored=len(scored),
        email_sent=email_sent,
    )
