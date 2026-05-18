import asyncio
from datetime import date, datetime, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.job import JobResult
from app.models.user import User, UserProfile

scheduler = AsyncIOScheduler()


def is_user_due(profile: UserProfile, now_utc: datetime) -> bool:
    try:
        user_tz = pytz.timezone(profile.timezone)
        hour_str, minute_str = profile.briefing_time.split(":")
        now_local = now_utc.astimezone(user_tz)
        return now_local.hour == int(hour_str) and now_local.minute == int(minute_str)
    except Exception:
        return False


async def _run_briefing_for_user(user: User, profile: UserProfile) -> None:
    from app.pipeline.discover import discover_jobs
    from app.pipeline.score import score_jobs
    from app.services.email import send_briefing_email

    if not profile.resume_text:
        return
    jobs = await discover_jobs(profile)
    scored = await score_jobs(jobs, profile, profile.resume_text)
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
    await send_briefing_email(user, scored)


async def check_and_run_due_briefings() -> None:
    now_utc = datetime.now(timezone.utc)
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

    async def run_with_sem(user: User, profile: UserProfile) -> None:
        async with sem:
            await _run_briefing_for_user(user, profile)

    tasks = [
        run_with_sem(user, profile)
        for user, profile in rows
        if is_user_due(profile, now_utc) and user.id not in already_ran
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def setup_scheduler() -> AsyncIOScheduler:
    if not scheduler.get_jobs():
        scheduler.add_job(check_and_run_due_briefings, "cron", minute="*")
    return scheduler
