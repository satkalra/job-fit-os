import asyncio
import logging
from datetime import date, datetime, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.job import JobResult
from app.models.user import User, UserProfile

scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)


def is_user_due(profile: UserProfile, now_utc: datetime) -> bool:
    try:
        user_tz = pytz.timezone(profile.timezone)
        hour_str, minute_str = profile.briefing_time.split(":")
        now_local = now_utc.astimezone(user_tz)
        due = now_local.hour == int(hour_str) and now_local.minute == int(minute_str)
        logger.debug("is_user_due user_id=%s timezone=%s local=%s briefing_time=%s due=%s", profile.user_id, profile.timezone, now_local.isoformat(), profile.briefing_time, due)
        return due
    except Exception:
        logger.exception("is_user_due failed user_id=%s timezone=%s briefing_time=%s", getattr(profile, "user_id", None), getattr(profile, "timezone", None), getattr(profile, "briefing_time", None))
        return False


async def _run_briefing_for_user(user: User, profile: UserProfile) -> None:
    from app.pipeline.discover import discover_jobs
    from app.pipeline.score import score_jobs
    from app.services.email import send_briefing_email

    if not profile.resume_text:
        logger.info("scheduled briefing skipped missing_resume user_id=%s", user.id)
        return
    logger.info("scheduled briefing start user_id=%s email=%s", user.id, user.email)
    jobs = await discover_jobs(profile)
    logger.debug("scheduled briefing discovered user_id=%s jobs=%s", user.id, len(jobs))
    scored = await score_jobs(jobs, profile, profile.resume_text)
    logger.debug("scheduled briefing scored user_id=%s jobs=%s", user.id, len(scored))
    async with AsyncSessionLocal() as db:
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
    logger.info("scheduled briefing persisted user_id=%s jobs=%s", user.id, len(scored))
    await send_briefing_email(user, scored)
    logger.info("scheduled briefing complete user_id=%s", user.id)


async def check_and_run_due_briefings() -> None:
    now_utc = datetime.now(timezone.utc)
    logger.debug("scheduler tick now_utc=%s", now_utc.isoformat())
    sem = asyncio.Semaphore(5)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(User, UserProfile)
                .join(UserProfile, UserProfile.user_id == User.id)
                .where(UserProfile.active == True)
            )
        ).all()
        already_ran = {
            row[0]
            for row in (
                await db.execute(select(JobResult.user_id).where(JobResult.run_date == date.today()))
            ).all()
        }
    logger.debug("scheduler loaded active_users=%s already_ran=%s", len(rows), len(already_ran))

    async def run_with_sem(user: User, profile: UserProfile) -> None:
        async with sem:
            await _run_briefing_for_user(user, profile)

    tasks = [
        run_with_sem(user, profile)
        for user, profile in rows
        if is_user_due(profile, now_utc) and user.id not in already_ran
    ]
    if tasks:
        logger.info("scheduler running due briefings count=%s", len(tasks))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("scheduled briefing task failed", exc_info=(type(result), result, result.__traceback__))
    else:
        logger.debug("scheduler no due briefings")


def setup_scheduler() -> AsyncIOScheduler:
    if not scheduler.get_jobs():
        logger.debug("adding scheduler job check_and_run_due_briefings")
        scheduler.add_job(check_and_run_due_briefings, "cron", minute="*")
    else:
        logger.debug("scheduler already configured jobs=%s", len(scheduler.get_jobs()))
    return scheduler
