import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.job import JobResult

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    job_results: Mapped[list["JobResult"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    profile_type: Mapped[str] = mapped_column(Text, nullable=False)
    resume_text: Mapped[str | None] = mapped_column(Text)
    resume_pdf_name: Mapped[str | None] = mapped_column(Text)
    domains: Mapped[list[str] | None] = mapped_column(JSON().with_variant(ARRAY(Text), "postgresql"))
    keywords: Mapped[str | None] = mapped_column(Text)
    seniority: Mapped[str | None] = mapped_column(Text)
    min_salary: Mapped[int | None] = mapped_column(Integer)
    target_companies: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    preferred_locations: Mapped[list[str] | None] = mapped_column(
        JSON().with_variant(ARRAY(Text), "postgresql"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    briefing_time: Mapped[str] = mapped_column(Text, default="07:00")
    timezone: Mapped[str] = mapped_column(Text, default="America/New_York")
    weight_role_match: Mapped[float] = mapped_column(Float, default=0.30)
    weight_skills_match: Mapped[float] = mapped_column(Float, default=0.30)
    weight_experience_level: Mapped[float] = mapped_column(Float, default=0.20)
    weight_compensation: Mapped[float] = mapped_column(Float, default=0.10)
    weight_cultural: Mapped[float] = mapped_column(Float, default=0.10)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="profile")
