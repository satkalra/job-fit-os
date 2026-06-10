import asyncio
import json
import logging
from typing import Callable

from pydantic import ValidationError

from app.config import settings
from app.schemas.job import ScoredJob
from app.schemas.resume import RewriteError, RewriteResult, RewrittenResume, ResumeStructure
from app.services.docx_builder import build_resume_docx
from app.utils.resume_parser import parse_resume
from app.utils.usage import record_usage_in_new_session

logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI

    _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None
except Exception:
    _openai_client = None


def _default_plan() -> list[dict]:
    return [
        {
            "wave": 1,
            "tasks": [
                {"id": "extract_proof_bank", "desc": "Extract quantifiable achievements and proof points from resume"},
                {"id": "extract_jd_requirements", "desc": "Extract key requirements from job description"},
                {"id": "extract_ats_keywords", "desc": "Extract ATS-critical keywords from job description"},
            ],
        },
        {
            "wave": 2,
            "tasks": [
                {"id": "match_proofs_to_requirements", "desc": "Map resume proof points to JD requirements"},
                {"id": "identify_gaps", "desc": "Identify requirements not covered by resume"},
                {"id": "rank_bullets", "desc": "Rank and select strongest bullet points for this role"},
            ],
        },
        {"wave": 3, "tasks": []},
        {
            "wave": 4,
            "tasks": [
                {"id": "verify_and_assemble", "desc": "Assemble final resume and verify all claims trace to original"},
            ],
        },
    ]


def _wave3_tasks(resume_structure: ResumeStructure) -> list[dict]:
    tasks = [
        {
            "id": f"rewrite_job_{i}",
            "desc": f"Rewrite bullets for: {job.title} at {job.company}. Emphasize JD keywords. Return only new bullets list.",
            "job": job.model_dump(),
        }
        for i, job in enumerate(resume_structure.jobs)
    ]
    tasks.extend(
        [
            {"id": "rewrite_summary", "desc": "Write tailored professional summary targeting this role"},
            {"id": "rewrite_skills", "desc": "Rewrite skills section prioritizing JD keywords, most relevant first"},
        ]
    )
    logger.info("rewacto status=planned_wave3 jobs=%s tasks=%s", len(resume_structure.jobs), [task["id"] for task in tasks])
    return tasks


_BULLET_PATTERNS = """
BULLET WRITING RULES:
- Lead with a strong action verb (Architected, Designed, Built, Led, Drove, Scaled, Launched, Reduced, Increased, Automated, Streamlined, Delivered, Owned, Partnered, Integrated)
- STAR format: Action + What + How + Result (metric when possible)
- Include at least one metric per bullet where the original has one (%, $, x faster, N users, N ms)
- Weave in JD keywords naturally — do not keyword-stuff
- Max 2 lines per bullet; prefer 1
- Do NOT add claims not traceable to the original resume
""".strip()


def _section_context_for_task(task: dict, context: dict) -> str:
    """Return only the resume section(s) relevant to this task — avoids full-resume truncation."""
    rs: dict = context.get("resume_structure_json", {})
    tid = task.get("id", "")
    if tid.startswith("rewrite_job_"):
        job = task.get("job") or {}
        return f"JOB ENTRY:\n{json.dumps(job, indent=2)}"
    if tid == "rewrite_summary":
        return f"CURRENT SUMMARY:\n{rs.get('summary', '')}\n\nSKILLS:\n{', '.join(rs.get('skills', [])[:20])}"
    if tid == "rewrite_skills":
        return f"CURRENT SKILLS:\n{', '.join(rs.get('skills', []))}"
    if tid in ("extract_proof_bank", "rank_bullets"):
        jobs_block = "\n\n".join(
            f"{j['title']} @ {j['company']} ({j['dates']}):\n" + "\n".join(f"- {b}" for b in j.get("bullets", []))
            for j in rs.get("jobs", [])
        )
        projects_block = "\n\n".join(
            f"{p['name']} ({p['dates']}):\n" + "\n".join(f"- {b}" for b in p.get("bullets", []))
            for p in rs.get("projects", [])
        )
        return f"EXPERIENCE:\n{jobs_block}\n\nPROJECTS:\n{projects_block}"
    if tid in ("extract_jd_requirements", "extract_ats_keywords"):
        return ""  # JD is already in the prompt; no extra resume context needed
    if tid == "match_proofs_to_requirements":
        return f"PROOF BANK:\n{json.dumps(context.get('wave_outputs', {}).get('extract_proof_bank', {}).get('result', ''), indent=2)}"
    if tid == "identify_gaps":
        return f"SKILLS:\n{', '.join(rs.get('skills', []))}"
    # fallback: compact parsed structure
    return json.dumps(rs, indent=2)[:3000]


async def _run_task(task: dict, context: dict) -> dict:
    logger.info("rewacto tool_call=openai model=gpt-5.5 task=%s", task["id"])
    if not _openai_client:
        raise RewriteError("OPENAI_API_KEY not set.", raw_output={})

    section_ctx = _section_context_for_task(task, context)

    wave_outputs = context.get("wave_outputs", {})
    ats_keywords = wave_outputs.get("extract_ats_keywords", {}).get("result", "")
    proof_map = wave_outputs.get("match_proofs_to_requirements", {}).get("result", "")
    prior_context = (
        f"ATS KEYWORDS TO TARGET:\n{ats_keywords}\n\nPROOF-TO-REQUIREMENT MAP:\n{proof_map}"
        if ats_keywords
        else json.dumps(wave_outputs, indent=2)[:2000]
    )

    prompt = f"""Task: {task["desc"]}

{_BULLET_PATTERNS}

RESUME SECTION:
{section_ctx}

JOB TITLE: {context.get("job_title", "")}
JOB COMPANY: {context.get("job_company", "")}
JOB DESCRIPTION: {context.get("job_description", "")[:3000]}

PRIOR WAVE OUTPUTS:
{prior_context}

Return ONLY a JSON object: {{"result": <your output as string or structured data>}}"""
    resp = await _openai_client.chat.completions.create(
        model="gpt-5.5",
        max_completion_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    user_id = context.get("user_id")
    if user_id:
        await record_usage_in_new_session(
            response=resp,
            user_id=user_id,
            stage="rewacto",
            provider="openai",
            model="gpt-5.5",
        )
    text = (resp.choices[0].message.content or "").strip()
    try:
        result = json.loads(text[text.find("{") : text.rfind("}") + 1])
        logger.info("rewacto status=task_complete task=%s output=json keys=%s", task["id"], list(result.keys()))
        return result
    except Exception:
        logger.info("rewacto status=task_complete task=%s output=text chars=%s", task["id"], len(text))
        return {"result": text}


async def _run_wave(wave: dict, context: dict) -> dict:
    tasks = wave["tasks"]
    logger.info("rewacto status=wave_start wave=%s tasks=%s", wave["wave"], [task["id"] for task in tasks])
    results = await asyncio.gather(*[_run_task(task, context) for task in tasks])
    output = {tasks[i]["id"]: results[i] for i in range(len(tasks))}
    logger.info("rewacto status=wave_complete wave=%s results=%s", wave["wave"], list(output.keys()))
    return output


async def _verify_with_openai(
    original_resume: str,
    resume_structure: ResumeStructure,
    wave_outputs: dict,
    job: ScoredJob,
    user_id: object | None = None,
) -> RewrittenResume:
    if not _openai_client:
        raise RewriteError("OPENAI_API_KEY not set.", raw_output={})
    logger.info(
        "rewacto status=verifier_start tool_call=openai model=gpt-5.5 jobs=%s projects=%s education=%s wave_outputs=%s",
        len(resume_structure.jobs),
        len(resume_structure.projects),
        len(resume_structure.education),
        list(wave_outputs.keys()),
    )
    prompt = f"""You are assembling the final tailored resume. Use the wave outputs as your rewrite material.

FIELD DEFINITIONS — read carefully before filling the tool:
- `summary`: the rewritten 2-3 sentence professional summary paragraph FOR THE RESUME (not your integrity notes).
- `jobs`: preserve title/company/location/dates EXACTLY from PARSED STRUCTURE; only change bullets.
- `projects`: preserve name/dates EXACTLY; only change bullets.
- `skills`: reordered list, most JD-relevant first.
- `education`: copy EXACTLY from PARSED STRUCTURE, do not modify.
- `gaps`: list of plain strings (NOT dicts), each a 1-sentence cover letter note about a missing requirement.

INTEGRITY RULE: every bullet must trace to a fact in the original resume. Do not fabricate metrics or claims.

{_BULLET_PATTERNS}

ORIGINAL RESUME:
{original_resume[:6000]}

PARSED STRUCTURE TO PRESERVE (copy title/company/location/dates/degree/school verbatim):
{resume_structure.model_dump_json(indent=2)}

JOB TITLE: {job.title}
JOB COMPANY: {job.company}
JOB DESCRIPTION:
{(job.description or "")[:3000]}

WAVE OUTPUTS (use these rewrites):
{json.dumps(wave_outputs, indent=2)[:3000]}

Now submit the complete rewritten resume using the tool."""
    resp = await _openai_client.chat.completions.create(
        model="gpt-5.5",
        max_completion_tokens=4000,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "submit_rewritten_resume",
                    "description": "Submit the fully rewritten and verified resume",
                    "parameters": RewrittenResume.model_json_schema(),
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": "submit_rewritten_resume"}},
        messages=[{"role": "user", "content": prompt}],
    )
    if user_id:
        await record_usage_in_new_session(
            response=resp,
            user_id=user_id,
            stage="rewacto",
            provider="openai",
            model="gpt-5.5",
        )
    raw = _extract_tool_input(resp)
    try:
        result = RewrittenResume.model_validate(raw)
        logger.info(
            "rewacto status=verifier_complete jobs=%s projects=%s skills=%s gaps=%s",
            len(result.jobs),
            len(result.projects),
            len(result.skills),
            len(result.gaps),
        )
        return result
    except ValidationError as exc:
        logger.exception("rewacto verifier malformed output")
        raise RewriteError("Verifier returned malformed rewritten resume.", raw_output=raw) from exc


def _extract_tool_input(resp) -> dict:
    message = resp.choices[0].message
    if message.tool_calls:
        raw = message.tool_calls[0].function.arguments
        logger.debug("rewacto verifier tool_input received chars=%s", len(raw))
        try:
            return json.loads(raw)
        except Exception as exc:
            raise RewriteError("Verifier returned malformed JSON.", raw_output=raw) from exc
    text = (message.content or "").strip()
    if not text:
        raise RewriteError("Verifier returned no output.", raw_output=resp)
    try:
        return json.loads(text[text.find("{") : text.rfind("}") + 1])
    except Exception as exc:
        raise RewriteError("Verifier returned malformed JSON.", raw_output=text) from exc


async def rewacto_rewrite(
    resume: str,
    job: ScoredJob,
    on_log: Callable[[str], None] | None = None,
) -> RewriteResult:
    def log(message: str) -> None:
        if on_log:
            on_log(message)

    resume_structure = parse_resume(resume)
    logger.info(
        "rewacto status=start job=%s company=%s resume_chars=%s parsed_jobs=%s parsed_projects=%s parsed_education=%s",
        job.title,
        job.company,
        len(resume),
        len(resume_structure.jobs),
        len(resume_structure.projects),
        len(resume_structure.education),
    )
    plan = _default_plan()
    plan[2]["tasks"] = _wave3_tasks(resume_structure)
    context = {
        "resume": resume,
        "resume_structure_json": resume_structure.model_dump(),
        "job_title": job.title,
        "job_company": job.company,
        "job_description": job.description or "",
        "user_id": getattr(job, "user_id", None),
        "wave_outputs": {},
    }

    for wave in plan[:3]:
        if not wave["tasks"]:
            continue
        log(f"Wave {wave['wave']} start")
        context["wave_outputs"].update(await _run_wave(wave, context))

    rewritten = await _verify_with_openai(resume, resume_structure, context["wave_outputs"], job, context["user_id"])
    rewritten = _preserve_original_structure(resume_structure, rewritten)
    docx_bytes = build_resume_docx(rewritten, resume_structure.name, resume_structure.contact)
    markdown = markdown_from_rewritten(rewritten, resume_structure.name, resume_structure.contact)
    logger.info("rewacto status=complete markdown_chars=%s docx_bytes=%s gaps=%s", len(markdown), len(docx_bytes), len(rewritten.gaps))
    return RewriteResult(markdown=markdown, docx_bytes=docx_bytes, gaps=rewritten.gaps)


def _preserve_original_structure(original: ResumeStructure, rewritten: RewrittenResume) -> RewrittenResume:
    logger.debug(
        "rewacto preserve_structure original_jobs=%s rewritten_jobs=%s original_projects=%s rewritten_projects=%s",
        len(original.jobs),
        len(rewritten.jobs),
        len(original.projects),
        len(rewritten.projects),
    )
    jobs = []
    for index, original_job in enumerate(original.jobs):
        rewritten_job = rewritten.jobs[index] if index < len(rewritten.jobs) else None
        jobs.append(original_job.model_copy(update={"bullets": (rewritten_job.bullets if rewritten_job else original_job.bullets)}))

    projects = []
    for index, original_project in enumerate(original.projects):
        rewritten_project = rewritten.projects[index] if index < len(rewritten.projects) else None
        projects.append(
            original_project.model_copy(update={"bullets": (rewritten_project.bullets if rewritten_project else original_project.bullets)})
        )

    return RewrittenResume(
        summary=rewritten.summary,
        jobs=jobs or rewritten.jobs,
        projects=projects or rewritten.projects,
        skills=rewritten.skills,
        education=original.education or rewritten.education,
        gaps=rewritten.gaps,
    )


def markdown_from_rewritten(resume: RewrittenResume, name: str = "", contact: str = "") -> str:
    lines: list[str] = []
    if name:
        lines.extend([f"# {name}", ""])
    if contact:
        lines.extend([contact, ""])
    lines.extend(["## Summary", "", resume.summary, "", "## Experience", ""])
    for job in resume.jobs:
        lines.extend([f"**{job.title} | {job.company} | {job.location} | {job.dates}**"])
        lines.extend(f"- {bullet}" for bullet in job.bullets)
        lines.append("")
    if resume.projects:
        lines.extend(["## Projects", ""])
        for project in resume.projects:
            lines.extend([f"**{project.name} | {project.dates}**"])
            lines.extend(f"- {bullet}" for bullet in project.bullets)
            lines.append("")
    lines.extend(["## Skills", "", ", ".join(resume.skills), "", "## Education", ""])
    for education in resume.education:
        lines.append(f"**{education.degree} | {education.school} | {education.location} | {education.dates}**")
    if resume.gaps:
        lines.extend(["", "---", "", "## Gap Analysis (Cover Letter Notes)", ""])
        lines.extend(f"- {gap}" for gap in resume.gaps)
    return "\n".join(lines).strip()
