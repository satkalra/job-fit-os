import uuid
from typing import Any

from pydantic import BaseModel, field_validator


class UserCreate(BaseModel):
    email: str
    name: str | None = None
    profile_type: str
    domains: list[str] | None = None
    keywords: str | None = None
    seniority: str | None = None
    min_salary: int | None = None
    remote_only: bool = False
    target_companies: list[dict[str, Any]] | None = None
    briefing_time: str = "07:00"
    timezone: str = "America/New_York"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    profile_type: str
    domains: list[str] | None
    keywords: str | None
    seniority: str | None
    min_salary: int | None
    remote_only: bool
    briefing_time: str
    timezone: str
    weight_role_match: float
    weight_skills_match: float
    weight_experience_level: float
    weight_compensation: float
    weight_cultural: float

    model_config = {"from_attributes": True}


class ProfilePatch(BaseModel):
    domains: list[str] | None = None
    keywords: str | None = None
    seniority: str | None = None
    min_salary: int | None = None
    remote_only: bool | None = None
    target_companies: list[dict[str, Any]] | None = None
    briefing_time: str | None = None
    timezone: str | None = None


class ResumeTextUpload(BaseModel):
    resume_text: str


class WeightsUpdate(BaseModel):
    weight_role_match: float
    weight_skills_match: float
    weight_experience_level: float
    weight_compensation: float
    weight_cultural: float

    @field_validator("weight_cultural")
    @classmethod
    def weights_sum_to_one(cls, v, info):
        weights = [
            info.data.get("weight_role_match", 0),
            info.data.get("weight_skills_match", 0),
            info.data.get("weight_experience_level", 0),
            info.data.get("weight_compensation", 0),
            v,
        ]
        total = sum(weights)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total:.4f}")
        return v
