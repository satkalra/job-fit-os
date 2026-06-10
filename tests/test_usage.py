import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.usage import UsageEvent
from app.utils.usage import compute_cost_usd, record_usage


def test_compute_cost_haiku():
    cost = compute_cost_usd(
        model="claude-haiku-4-5-20251001",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        web_searches=0,
    )
    assert abs(cost - 4.80) < 0.001


def test_compute_cost_sonnet():
    cost = compute_cost_usd(
        model="claude-sonnet-4-6",
        input_tokens=500_000,
        output_tokens=200_000,
        web_searches=0,
    )
    assert abs(cost - 4.50) < 0.001


def test_compute_cost_web_search():
    cost = compute_cost_usd(
        model="claude-haiku-4-5-20251001",
        input_tokens=0,
        output_tokens=0,
        web_searches=5,
    )
    assert abs(cost - 0.05) < 0.0001


def test_compute_cost_unknown_model_returns_zero():
    cost = compute_cost_usd(model="unknown-model", input_tokens=1000, output_tokens=1000, web_searches=0)
    assert cost == 0.0


@pytest.mark.asyncio
async def test_record_usage_anthropic(db_session):
    user_id = uuid.uuid4()

    mock_usage = MagicMock()
    mock_usage.input_tokens = 1000
    mock_usage.output_tokens = 500
    mock_usage.server_tool_use = MagicMock()
    mock_usage.server_tool_use.web_search_requests = 2

    mock_response = MagicMock()
    mock_response.usage = mock_usage

    await record_usage(
        response=mock_response,
        user_id=user_id,
        stage="discover",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        db=db_session,
    )

    rows = (await db_session.execute(select(UsageEvent).where(UsageEvent.user_id == user_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].stage == "discover"
    assert rows[0].input_tokens == 1000
    assert rows[0].output_tokens == 500
    assert rows[0].web_searches == 2
    assert rows[0].cost_usd > 0


@pytest.mark.asyncio
async def test_record_usage_openai(db_session):
    user_id = uuid.uuid4()

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 2000
    mock_usage.completion_tokens = 800

    mock_response = MagicMock(spec=["usage"])
    mock_response.usage = mock_usage

    await record_usage(
        response=mock_response,
        user_id=user_id,
        stage="rewacto",
        provider="openai",
        model="gpt-5.5",
        db=db_session,
    )

    rows = (await db_session.execute(select(UsageEvent).where(UsageEvent.user_id == user_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].provider == "openai"
    assert rows[0].input_tokens == 2000
    assert rows[0].output_tokens == 800


@pytest.mark.asyncio
async def test_usage_endpoint(client, created_user, db_session):
    user_id, management_token = created_user
    event = UsageEvent(
        user_id=uuid.UUID(user_id),
        stage="score",
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=5000,
        output_tokens=1000,
        web_searches=0,
        cost_usd=0.03,
    )
    db_session.add(event)
    await db_session.commit()

    resp = await client.get(
        f"/users/{user_id}/usage",
        headers={"Authorization": f"Bearer {management_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost_usd"] == 0.03
    assert data["total_input_tokens"] == 5000
    assert data["total_output_tokens"] == 1000
    assert data["by_stage"][0]["stage"] == "score"
    assert data["by_stage"][0]["calls"] == 1
    assert data["by_day"][0]["cost_usd"] == 0.03
