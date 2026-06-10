import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLM_PRICING, WEB_SEARCH_COST_USD
from app.models.usage import UsageEvent

logger = logging.getLogger(__name__)


def compute_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    web_searches: int,
) -> float:
    pricing = LLM_PRICING.get(model)
    if not pricing:
        logger.warning("usage compute_cost unknown model=%s", model)
        return 0.0

    input_price, output_price = pricing
    token_cost = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
    search_cost = web_searches * WEB_SEARCH_COST_USD
    return round(token_cost + search_cost, 8)


def _extract_anthropic_tokens(usage: object) -> tuple[int, int, int]:
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    web_searches = 0
    server_tool_use = getattr(usage, "server_tool_use", None)
    if server_tool_use:
        web_searches = getattr(server_tool_use, "web_search_requests", 0) or 0
    return input_tokens, output_tokens, web_searches


def _extract_openai_tokens(usage: object) -> tuple[int, int, int]:
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    return input_tokens, output_tokens, 0


async def record_usage(
    response: object,
    user_id: uuid.UUID,
    stage: str,
    provider: str,
    model: str,
    db: AsyncSession,
) -> None:
    try:
        usage = getattr(response, "usage", None)
        if not usage:
            return

        if provider == "anthropic":
            input_tokens, output_tokens, web_searches = _extract_anthropic_tokens(usage)
        else:
            input_tokens, output_tokens, web_searches = _extract_openai_tokens(usage)

        cost = compute_cost_usd(model, input_tokens, output_tokens, web_searches)
        db.add(
            UsageEvent(
                user_id=user_id,
                stage=stage,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                web_searches=web_searches,
                cost_usd=cost,
            )
        )
        await db.flush()
        logger.info(
            "usage stage=%s model=%s in=%s out=%s searches=%s cost_usd=%.6f user_id=%s",
            stage,
            model,
            input_tokens,
            output_tokens,
            web_searches,
            cost,
            user_id,
        )
    except Exception:
        logger.exception("record_usage failed silently stage=%s user_id=%s", stage, user_id)


async def record_usage_in_new_session(
    response: object,
    user_id: uuid.UUID,
    stage: str,
    provider: str,
    model: str,
) -> None:
    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await record_usage(
                response=response,
                user_id=user_id,
                stage=stage,
                provider=provider,
                model=model,
                db=db,
            )
            await db.commit()
    except Exception:
        logger.exception("record_usage commit failed silently stage=%s user_id=%s", stage, user_id)
