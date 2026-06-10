import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.usage import UsageEvent
from app.models.user import User

router = APIRouter(tags=["ops"])
logger = logging.getLogger(__name__)


def _require_admin(x_ops_token: str | None) -> None:
    if not settings.ADMIN_TOKEN or x_ops_token != settings.ADMIN_TOKEN:
        raise HTTPException(404)


@router.get("/ops/cost")
async def ops_cost_summary(
    days: int = 30,
    x_ops_token: str | None = Header(default=None),
):
    _require_admin(x_ops_token)
    if days < 1 or days > 366:
        raise HTTPException(422, "days must be 1–366")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(UsageEvent)
                .where(UsageEvent.created_at >= cutoff)
                .order_by(UsageEvent.created_at.asc())
            )
        ).scalars().all()

        users = {u.id: u for u in (await db.execute(select(User))).scalars().all()}

    total_cost = round(sum(r.cost_usd for r in rows), 6)
    total_in = sum(r.input_tokens for r in rows)
    total_out = sum(r.output_tokens for r in rows)
    total_searches = sum(r.web_searches for r in rows)
    total_calls = len(rows)

    by_user: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    by_stage: dict[str, dict] = {}
    by_day: dict[str, dict] = {}

    for row in rows:
        uid = str(row.user_id)
        u = users.get(row.user_id)
        label = f"{u.email} ({uid[:8]})" if u else uid[:8]
        bucket = by_user.setdefault(uid, {"email": label, "cost_usd": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0})
        bucket["cost_usd"] += row.cost_usd
        bucket["calls"] += 1
        bucket["input_tokens"] += row.input_tokens
        bucket["output_tokens"] += row.output_tokens

        m = by_model.setdefault(row.model, {"cost_usd": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0})
        m["cost_usd"] += row.cost_usd
        m["calls"] += 1
        m["input_tokens"] += row.input_tokens
        m["output_tokens"] += row.output_tokens

        s = by_stage.setdefault(row.stage, {"cost_usd": 0.0, "calls": 0})
        s["cost_usd"] += row.cost_usd
        s["calls"] += 1

        day_key = row.created_at.date().isoformat()
        d = by_day.setdefault(day_key, {"cost_usd": 0.0, "calls": 0})
        d["cost_usd"] += row.cost_usd
        d["calls"] += 1

    for bucket in by_user.values():
        bucket["cost_usd"] = round(bucket["cost_usd"], 6)
    for bucket in by_model.values():
        bucket["cost_usd"] = round(bucket["cost_usd"], 6)
    for bucket in by_stage.values():
        bucket["cost_usd"] = round(bucket["cost_usd"], 6)
    for bucket in by_day.values():
        bucket["cost_usd"] = round(bucket["cost_usd"], 6)

    return {
        "period_days": days,
        "total_cost_usd": total_cost,
        "total_calls": total_calls,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_web_searches": total_searches,
        "by_user": by_user,
        "by_model": by_model,
        "by_stage": by_stage,
        "by_day": dict(sorted(by_day.items())),
    }
