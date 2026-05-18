import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.user import User

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class JobResult(Base):
    __tablename__ = "job_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    posted_date: Mapped[str | None] = mapped_column(Text)
    salary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[list[str] | None] = mapped_column(JSON().with_variant(ARRAY(Text), "postgresql"))
    tags: Mapped[list[str] | None] = mapped_column(JSON().with_variant(ARRAY(Text), "postgresql"))
    url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    global_score: Mapped[int | None] = mapped_column(Integer)
    verdict: Mapped[str | None] = mapped_column(Text)
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    red_flags: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    citations: Mapped[list[str] | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    summary: Mapped[str | None] = mapped_column(Text)
    rewrite_token: Mapped[str | None] = mapped_column(Text, unique=True)
    rewrite_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="job_results")
