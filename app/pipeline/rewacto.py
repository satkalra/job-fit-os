import asyncio
import json
from typing import Callable

from anthropic import AsyncAnthropic

from app.config import settings
from app.schemas.job import ScoredJob

_anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY or "not-set")

try:
    from openai import AsyncOpenAI

    _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None
except Exception:
    _openai_client = None


def _default_plan() -> list[dict]:
    return [
        {"wave": 1, "tasks": [
            {"id": "extract_proof_bank", "desc": "Extract quantifiable achievements and proof points from resume"},
            {"id": "extract_jd_requirements", "desc": "Extract key requirements from job description"},
            {"id": "extract_ats_keywords", "desc": "Extract ATS-critical keywords from job description"},
        ]},
        {"wave": 2, "tasks": [
            {"id": "match_proofs_to_requirements", "desc": "Map resume proof points to JD requirements"},
            {"id": "identify_gaps", "desc": "Identify requirements not covered by resume"},
            {"id": "rank_bullets", "desc": "Rank and select strongest bullet points for this role"},
        ]},
        {"wave": 3, "tasks": [
            {"id": "rewrite_summary", "desc": "Write tailored professional summary targeting this role"},
            {"id": "rewrite_experience", "desc": "Rewrite experience bullets emphasizing relevant proof points"},
            {"id": "rewrite_skills", "desc": "Rewrite skills section prioritizing JD keywords"},
        ]},
        {"wave": 4, "tasks": [
            {"id": "verify_and_assemble", "desc": "Assemble final resume and verify all claims trace to original"},
        ]},
    ]


async def _run_task(task_id: str, task_desc: str, context: dict) -> dict:
    prompt = f"""Task: {task_desc}

RESUME:
{context.get('resume', '')[:2000]}

JOB TITLE: {context.get('job_title', '')}
JOB COMPANY: {context.get('job_company', '')}
JOB DESCRIPTION: {context.get('job_description', '')[:1500]}

PRIOR WAVE OUTPUTS:
{json.dumps(context.get('wave_outputs', {}), indent=2)[:1000]}

Return ONLY a JSON object: {{"result": <your output as string or structured data>}}"""
    resp = await _anthropic.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    try:
        return json.loads(text[text.find("{") : text.rfind("}") + 1])
    except Exception:
        return {"result": text}


async def _run_wave(wave: dict, context: dict) -> dict:
    tasks = wave["tasks"]
    results = await asyncio.gather(*[_run_task(task["id"], task["desc"], context) for task in tasks])
    return {tasks[i]["id"]: results[i] for i in range(len(tasks))}


async def _verify_with_sonnet(resume: str, wave_outputs: dict, job: ScoredJob) -> dict:
    prompt = f"""You are a resume integrity verifier.

ORIGINAL RESUME:
{resume[:2000]}

REWRITTEN CONTENT:
{json.dumps(wave_outputs, indent=2)[:2000]}

Verify every claim traces to proof in the original resume. Return ONLY JSON with verified, rejectWaves, finalSummary, finalBullets, finalSkills, gaps."""
    resp = await _anthropic.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    return json.loads(text[text.find("{") : text.rfind("}") + 1])


async def rewacto_rewrite(
    resume: str,
    job: ScoredJob,
    on_log: Callable[[str], None] | None = None,
) -> str:
    def log(message: str) -> None:
        if on_log:
            on_log(message)

    plan = _default_plan()
    context = {
        "resume": resume,
        "job_title": job.title,
        "job_company": job.company,
        "job_description": job.description or "",
        "wave_outputs": {},
    }

    for wave in plan[:3]:
        log(f"Wave {wave['wave']} start")
        context["wave_outputs"].update(await _run_wave(wave, context))

    verify = await _verify_with_sonnet(resume, context["wave_outputs"], job)
    if not verify.get("verified") and verify.get("rejectWaves"):
        for wave_num in verify["rejectWaves"]:
            wave = next((candidate for candidate in plan if candidate["wave"] == wave_num), None)
            if wave:
                context["wave_outputs"].update(await _run_wave(wave, context))

    await _run_wave(plan[3], context)

    bullets_md = "\n".join(f"- {bullet}" for bullet in verify.get("finalBullets", []))
    skills_md = ", ".join(verify.get("finalSkills", []))
    gaps_md = "\n".join(f"- {gap}" for gap in verify.get("gaps", []))
    return f"""## Summary

{verify.get('finalSummary', '')}

## Experience

{bullets_md}

## Skills

{skills_md}

---

## Gap Analysis (Cover Letter Notes)

{gaps_md}
""".strip()
