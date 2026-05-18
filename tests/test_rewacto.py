from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipeline.rewacto import _default_plan, rewacto_rewrite
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


@pytest.mark.asyncio
async def test_rewacto_rewrite_returns_string():
    mock_haiku_resp = MagicMock()
    mock_haiku_resp.content = [MagicMock(text='{"result": "test output", "verified": true, "rejectWaves": []}')]
    mock_sonnet_resp = MagicMock()
    mock_sonnet_resp.content = [
        MagicMock(
            text='{"verified": true, "rejectWaves": [], "finalSummary": "AI Engineer with ML expertise.", "finalBullets": ["Built RAG pipeline"], "finalSkills": ["Python", "LLMs"], "gaps": []}'
        )
    ]
    with patch("app.pipeline.rewacto._anthropic") as mock_ant:
        mock_ant.messages.create = AsyncMock(
            side_effect=[
                mock_haiku_resp,
                mock_haiku_resp,
                mock_haiku_resp,
                mock_haiku_resp,
                mock_haiku_resp,
                mock_haiku_resp,
                mock_haiku_resp,
                mock_haiku_resp,
                mock_haiku_resp,
                mock_sonnet_resp,
                mock_haiku_resp,
            ]
        )
        result = await rewacto_rewrite(
            "Python engineer with 5 years experience in ML and LLMs. Built RAG systems. " * 20,
            make_job(),
        )
    assert isinstance(result, str)
    assert len(result) > 50
