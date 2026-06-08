import html
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.job import JobResult
from app.models.user import User, UserProfile
from app.pipeline.rewacto import rewacto_rewrite
from app.schemas.job import ScoredJob
from app.services.email import send_rewrite_email
from app.utils.token import verify_token

router = APIRouter(tags=["rewrite"])
logger = logging.getLogger(__name__)

_STYLES = "font-family:sans-serif;max-width:600px;margin:auto;padding:40px;"


def _confirm_page(token: str, title: str, company: str) -> str:
    return f"""<html><body style="{_STYLES}">
<h2>Tailor Resume for {html.escape(title)} at {html.escape(company)}</h2>
<p>Click the button below to generate your tailored resume and receive it via email.</p>
<form method="post" action="/rewrite">
  <input type="hidden" name="token" value="{html.escape(token)}">
  <button type="submit" style="padding:10px 24px;background:#2ecc71;color:white;border:none;border-radius:4px;font-size:16px;cursor:pointer;">
    Generate My Tailored Resume
  </button>
</form>
</body></html>"""


@router.get("/rewrite", response_class=HTMLResponse)
async def rewrite_confirm(token: str):
    """Show confirmation page only — safe for email link scanners."""
    logger.info("rewrite confirm token_prefix=%s", token[:8] if token else "")
    try:
        payload = verify_token(token)
        user_id = uuid.UUID(payload["user_id"])
    except ValueError as exc:
        raise HTTPException(400, "Invalid or expired token.") from exc

    async with AsyncSessionLocal() as db:
        job_row = (await db.execute(select(JobResult).where(JobResult.rewrite_token == token))).scalar_one_or_none()
        if not job_row:
            logger.info("rewrite confirm job_not_found user_id=%s token_prefix=%s", user_id, token[:8])
            raise HTTPException(404, "Job not found.")
        if job_row.rewrite_sent_at:
            row = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            email = html.escape(row.email if row else "your email")
            return HTMLResponse(f"""<html><body style="{_STYLES}">
<h2>Already sent</h2>
<p>Your tailored resume for <strong>{html.escape(job_row.title or '')} at {html.escape(job_row.company or '')}</strong> was already sent to {email}.</p>
</body></html>""")

    return HTMLResponse(_confirm_page(token, job_row.title or "", job_row.company or ""))


@router.post("/rewrite", response_class=HTMLResponse)
async def rewrite_execute(token: str = Form(...)):
    """Run rewacto pipeline and email tailored resume — only triggered by explicit user action."""
    logger.info("rewrite execute token_prefix=%s", token[:8] if token else "")
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
            logger.info("rewrite execute user_not_found user_id=%s", user_id)
            raise HTTPException(404, "User not found.")
        user, profile = row
        job_row = (await db.execute(select(JobResult).where(JobResult.rewrite_token == token))).scalar_one_or_none()
        if not job_row:
            logger.info("rewrite execute job_not_found user_id=%s token_prefix=%s", user_id, token[:8])
            raise HTTPException(404, "Job not found.")
        if job_row.rewrite_sent_at:
            logger.info("rewrite execute already_sent user_id=%s job_id=%s sent_at=%s", user_id, job_row.id, job_row.rewrite_sent_at)
            return HTMLResponse(f"""<html><body style="{_STYLES}">
<h2>Already sent</h2>
<p>Your tailored resume for <strong>{html.escape(job_row.title or '')} at {html.escape(job_row.company or '')}</strong> was already sent to {html.escape(user.email)}.</p>
</body></html>""")
        if not profile.resume_text:
            logger.info("rewrite execute missing_resume user_id=%s job_id=%s", user_id, job_row.id)
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
        logger.info("rewrite execute pipeline_start user_id=%s job=%s company=%s", user_id, job.title, job.company)
        result = await rewacto_rewrite(profile.resume_text, job)
        logger.info("rewrite execute pipeline_complete user_id=%s markdown_chars=%s docx_bytes=%s gaps=%s", user_id, len(result.markdown), len(result.docx_bytes), len(result.gaps))
        await send_rewrite_email(user, job, result.docx_bytes)
        job_row.rewrite_sent_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info("rewrite execute sent user_id=%s job_id=%s email=%s", user_id, job_row.id, user.email)

    return HTMLResponse(f"""<html><body style="{_STYLES}">
<h2>Your tailored resume is on its way</h2>
<p>We've sent your tailored resume for <strong>{html.escape(job.title)} at {html.escape(job.company)}</strong> to <strong>{html.escape(user.email)}</strong>.</p>
</body></html>""")
