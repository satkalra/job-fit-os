import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.job import JobResult
from app.models.user import User, UserProfile
from app.pipeline.rewacto import rewacto_rewrite
from app.schemas.job import ScoredJob
from app.services.docx_builder import build_resume_docx
from app.services.email import send_rewrite_email
from app.utils.token import verify_token

router = APIRouter(tags=["rewrite"])


@router.get("/rewrite", response_class=HTMLResponse)
async def rewrite_from_token(token: str):
    try:
        payload = verify_token(token)
        user_id = uuid.UUID(payload["user_id"])
    except ValueError as exc:
        raise HTTPException(400, "Invalid or expired token.") from exc

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
        user, profile = row
        job_row = (await db.execute(select(JobResult).where(JobResult.rewrite_token == token))).scalar_one_or_none()
        if not job_row:
            raise HTTPException(404, "Job not found.")
        if job_row.rewrite_sent_at:
            return HTMLResponse(
                f"""<html><body style="font-family:sans-serif;max-width:600px;margin:auto;padding:40px;">
<h2>Already sent</h2><p>Your tailored resume for <strong>{job_row.title} at {job_row.company}</strong> was already sent to {user.email}.</p>
</body></html>"""
            )
        if not profile.resume_text:
            raise HTTPException(422, "No resume on file.")

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
        await send_rewrite_email(user, job, docx_bytes)
        job_row.rewrite_sent_at = datetime.now(timezone.utc)
        await db.commit()

    return HTMLResponse(
        f"""<html><body style="font-family:sans-serif;max-width:600px;margin:auto;padding:40px;">
<h2>Your tailored resume is on its way</h2>
<p>We've sent your Rewacto-tailored resume for <strong>{job.title} at {job.company}</strong> to <strong>{user.email}</strong>.</p>
</body></html>"""
    )
