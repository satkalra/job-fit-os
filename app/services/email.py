import asyncio
import html
import smtplib
import ssl
from datetime import date
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.models.user import User
from app.schemas.job import ScoredJob

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465

_VERDICT_BADGE = {
    "strong-apply": "Strong Match",
    "apply": "Apply",
    "maybe": "Maybe",
}


def _get_smtp_connection() -> smtplib.SMTP_SSL:
    context = ssl.create_default_context()
    conn = smtplib.SMTP_SSL(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, context=context)
    conn.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
    return conn


def _build_job_card_html(job: ScoredJob, base_url: str) -> str:
    flags = ", ".join(html.escape(flag.get("description", "")) for flag in job.red_flags or [])
    red_flags_html = f"<p style='color:#c0392b;'>Flags: {flags}</p>" if flags else ""
    tags_html = ", ".join(html.escape(tag) for tag in job.tags or [])
    rewrite_url = f"{base_url}/rewrite?token={job.rewrite_token}" if job.rewrite_token else "#"
    return f"""
<div style="border:1px solid #ddd;border-radius:8px;padding:16px;margin:16px 0;font-family:sans-serif;">
  <div style="display:flex;justify-content:space-between;">
    <strong style="font-size:18px;">{job.global_score}/100</strong>
    <span style="background:#eaf4ff;padding:4px 8px;border-radius:4px;">{html.escape(_VERDICT_BADGE.get(job.verdict, job.verdict))}</span>
  </div>
  <h3 style="margin:8px 0;">{html.escape(job.title)} - {html.escape(job.company)}</h3>
  <p style="color:#555;">{html.escape(job.location or '')} · {html.escape(job.salary or '')} · {html.escape(job.posted_date or '')}</p>
  <p>{html.escape(job.summary)}</p>
  <p style="color:#888;">Tags: {tags_html}</p>
  {red_flags_html}
  <div style="margin-top:12px;">
    <a href="{html.escape(job.url or '#')}" style="margin-right:12px;padding:8px 16px;background:#3498db;color:white;text-decoration:none;border-radius:4px;">View Job</a>
    <a href="{html.escape(rewrite_url)}" style="padding:8px 16px;background:#2ecc71;color:white;text-decoration:none;border-radius:4px;">Tailor Resume</a>
  </div>
</div>"""


def _build_briefing_html(user: User, jobs: list[ScoredJob], today: date) -> str:
    strong = sum(1 for job in jobs if job.verdict == "strong-apply")
    apply = sum(1 for job in jobs if job.verdict == "apply")
    maybe = sum(1 for job in jobs if job.verdict == "maybe")
    cards = "".join(_build_job_card_html(job, settings.BASE_URL) for job in jobs[:5])
    return f"""<html><body style="font-family:sans-serif;max-width:700px;margin:auto;">
<h1>JobFit OS - {today.strftime('%B %d, %Y')}</h1>
<p>Hi {html.escape(user.name or 'there')},</p>
<p style="background:#f8f8f8;padding:12px;border-radius:6px;">
  {strong} Strong Match &nbsp;|&nbsp; {apply} Apply &nbsp;|&nbsp; {maybe} Maybe
</p>
{cards}
<hr><p style="color:#aaa;font-size:12px;">JobFit OS automated job intelligence</p>
</body></html>"""


def _send_briefing_sync(user: User, jobs: list[ScoredJob]) -> bool:
    today = date.today()
    strong = sum(1 for job in jobs if job.verdict == "strong-apply")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"JobFit OS - Your briefing for {today} ({strong} strong matches)"
    msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.GMAIL_ADDRESS}>"
    msg["To"] = user.email
    msg.attach(MIMEText(_build_briefing_html(user, jobs, today), "html"))
    try:
        with _get_smtp_connection() as conn:
            conn.sendmail(settings.GMAIL_ADDRESS, user.email, msg.as_string())
        return True
    except Exception:
        return False


def _send_rewrite_sync(user: User, job: ScoredJob, docx_bytes: bytes) -> bool:
    today = date.today()
    filename = f"resume_{job.company}_{job.title}_{today}.docx".replace(" ", "_")
    msg = MIMEMultipart()
    msg["Subject"] = f"Your tailored resume - {job.title} at {job.company}"
    msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.GMAIL_ADDRESS}>"
    msg["To"] = user.email
    scores = job.scores or {}
    gaps = [flag.get("description", "") for flag in job.red_flags or []]
    gaps_text = "\n  ".join(f"- {gap}" for gap in gaps[:5]) or "None identified"
    body = f"""Hi {user.name or 'there'},

Here's your Rewacto-tailored resume for {job.title} at {job.company}.

Score breakdown:
  Role Match: {scores.get('roleMatch', '?')}/5
  Skills: {scores.get('skillsMatch', '?')}/5
  Experience: {scores.get('experienceLevel', '?')}/5

Gaps to address in your cover letter:
  {gaps_text}

The full tailored resume is attached as a Word document (.docx).

Apply to {job.company}: {job.url or '#'}
"""
    msg.attach(MIMEText(body, "plain"))
    part = MIMEBase("application", "octet-stream")
    part.set_payload(docx_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)
    try:
        with _get_smtp_connection() as conn:
            conn.sendmail(settings.GMAIL_ADDRESS, user.email, msg.as_string())
        return True
    except Exception:
        return False


async def send_briefing_email(user: User, jobs: list[ScoredJob]) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_briefing_sync, user, jobs)


async def send_rewrite_email(user: User, job: ScoredJob, docx_bytes: bytes) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_rewrite_sync, user, job, docx_bytes)
