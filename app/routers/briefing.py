import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import JobResult
from app.models.user import User, UserProfile
from app.pipeline.discover import discover_jobs
from app.pipeline.score import score_jobs_debug
from app.schemas.job import BriefingRunResult
from app.routers.users import _verify_management_token
from app.services.email import send_briefing_email

router = APIRouter(prefix="/briefing", tags=["briefing"])
logger = logging.getLogger(__name__)


@router.post("/run/{user_id}", response_model=BriefingRunResult)
async def run_briefing(
    user_id: uuid.UUID,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    logger.info("manual briefing requested user_id=%s", user_id)
    _verify_management_token(authorization.removeprefix("Bearer "), user_id)
    row = (
        await db.execute(
            select(User, UserProfile)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(User.id == user_id)
        )
    ).one_or_none()
    if not row:
        logger.info("manual briefing user_not_found user_id=%s", user_id)
        raise HTTPException(404, "User not found")
    user, profile = row
    if not profile.resume_text:
        logger.info("manual briefing missing_resume user_id=%s", user_id)
        raise HTTPException(422, "User has no resume. Upload via /resume/upload or /resume/text first.")

    logger.info(
        "briefing profile user_id=%s seniority=%s locations=%s countries=%s sponsorship=%s targets=%s",
        user_id, profile.seniority, profile.preferred_locations, profile.countries,
        profile.needs_sponsorship, len(profile.target_companies or []),
    )
    jobs = await discover_jobs(profile)
    logger.info("briefing status=discovered user_id=%s jobs=%s", user_id, len(jobs))
    scored, pipeline = await score_jobs_debug(jobs, profile, profile.resume_text)
    logger.info("briefing status=pipeline user_id=%s %s", user_id, pipeline)
    logger.info("briefing status=scored user_id=%s jobs=%s", user_id, len(scored))
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
    logger.info("manual briefing persisted jobs=%s user_id=%s", len(scored), user_id)
    email_sent = await send_briefing_email(user, scored)
    logger.info("manual briefing email_sent=%s user_id=%s", email_sent, user_id)
    return BriefingRunResult(
        jobs_found=pipeline["discovered"],
        jobs_after_gates=pipeline["after_gates"],
        jobs_scored=pipeline["returned"],
        email_sent=email_sent,
    )
