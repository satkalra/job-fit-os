from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipeline.rewacto import _default_plan, rewacto_rewrite
from app.schemas.resume import RewriteResult
from app.schemas.job import ScoredJob


def make_job():
    return ScoredJob(
        title="Senior ML Engineer",
        company="Anthropic",
        source="ats",
        global_score=82,
        verdict="apply",
        scores={"roleMatch": 4, "skillsMatch": 4, "experienceLevel": 4, "compensation": 3, "cultural": 4},
        red_flags=[],
        citations=[],
        summary="Great fit for ML work.",
    )


def test_default_plan_has_four_waves():
    plan = _default_plan()
    assert len(plan) == 4
    assert all("tasks" in wave for wave in plan)


def _make_openai_text_resp(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None
    resp = MagicMock()
    resp.choices = [MagicMock(message=msg)]
    return resp


def _make_openai_tool_resp(tool_input: dict) -> MagicMock:
    import json
    fn = MagicMock()
    fn.arguments = json.dumps(tool_input)
    tc = MagicMock()
    tc.function = fn
    msg = MagicMock()
    msg.tool_calls = [tc]
    resp = MagicMock()
    resp.choices = [MagicMock(message=msg)]
    return resp


@pytest.mark.asyncio
async def test_rewacto_rewrite_returns_result():
    wave_resp = _make_openai_text_resp('{"result": "test output"}')
    verifier_resp = _make_openai_tool_resp({
        "summary": "AI Engineer with ML expertise.",
        "jobs": [
            {
                "title": "Software Engineer",
                "company": "Acme",
                "location": "Remote",
                "dates": "2021 - Present",
                "bullets": ["Built RAG pipeline"],
            }
        ],
        "projects": [],
        "skills": ["Python", "LLMs"],
        "education": [],
        "gaps": [],
    })
    with patch("app.pipeline.rewacto._openai_client") as mock_oai:
        mock_oai.chat.completions.create = AsyncMock(
            side_effect=[
                wave_resp,  # wave 1 x3
                wave_resp,
                wave_resp,
                wave_resp,  # wave 2 x3
                wave_resp,
                wave_resp,
                wave_resp,  # wave 3 workers (1 job + summary + skills)
                wave_resp,
                wave_resp,
                verifier_resp,  # wave 4 verifier
            ]
        )
        result = await rewacto_rewrite(
            """Jane Doe
jane@example.com

Experience
Software Engineer | Acme | Remote | 2021 - Present
- Built RAG systems.

Skills
Python, LLMs
""",
            make_job(),
        )
    assert isinstance(result, RewriteResult)
    assert "Software Engineer" in result.markdown
    assert len(result.docx_bytes) > 100
