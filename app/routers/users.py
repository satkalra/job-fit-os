import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User, UserProfile
from app.schemas.user import ProfilePatch, ResumeTextUpload, UserCreate, WeightsUpdate
from app.services.pdf_extractor import extract_resume_text

router = APIRouter(prefix="/users", tags=["users"])


def _make_management_token(user_id: str | uuid.UUID) -> str:
    payload = {"user_id": str(user_id), "type": "management"}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def _verify_management_token(token: str, user_id: uuid.UUID | None = None) -> str:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") != "management":
            raise ValueError("wrong type")
        token_user_id = payload["user_id"]
        if user_id is not None and token_user_id != str(user_id):
            raise ValueError("wrong user")
        return token_user_id
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid management token") from exc


@router.post("")
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    user = User(email=body.email, name=body.name, created_at=datetime.now(timezone.utc))
    db.add(user)
    await db.flush()
    profile = UserProfile(
        user_id=user.id,
        profile_type=body.profile_type,
        domains=body.domains,
        keywords=body.keywords,
        seniority=body.seniority,
        min_salary=body.min_salary,
        target_companies=body.target_companies,
        preferred_locations=body.preferred_locations,
        briefing_time=body.briefing_time,
        timezone=body.timezone,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(profile)
    await db.commit()
    return {
        "user_id": str(user.id),
        "management_token": _make_management_token(user.id),
        "message": "Welcome email sent",
    }


@router.get("/{user_id}")
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    await db.refresh(user, ["profile"])
    profile = user.profile
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "profile_type": profile.profile_type if profile else None,
        "domains": profile.domains if profile else None,
        "keywords": profile.keywords if profile else None,
        "seniority": profile.seniority if profile else None,
        "min_salary": profile.min_salary if profile else None,
        "preferred_locations": profile.preferred_locations if profile else None,
        "briefing_time": profile.briefing_time if profile else "07:00",
        "timezone": profile.timezone if profile else "America/New_York",
        "weight_role_match": profile.weight_role_match if profile else 0.30,
        "weight_skills_match": profile.weight_skills_match if profile else 0.30,
        "weight_experience_level": profile.weight_experience_level if profile else 0.20,
        "weight_compensation": profile.weight_compensation if profile else 0.10,
        "weight_cultural": profile.weight_cultural if profile else 0.10,
    }


@router.patch("/{user_id}")
async def patch_user(
    user_id: uuid.UUID,
    body: ProfilePatch,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    _verify_management_token(authorization.removeprefix("Bearer "), user_id)
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "User not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(profile, field, value)
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"updated": True}


@router.patch("/{user_id}/weights")
async def update_weights(
    user_id: uuid.UUID,
    body: WeightsUpdate,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    _verify_management_token(authorization.removeprefix("Bearer "), user_id)
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "User not found")
    for field, value in body.model_dump().items():
        setattr(profile, field, value)
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"weights_updated": True, "new_weights": body.model_dump()}


@router.post("/{user_id}/resume/upload")
async def upload_resume_pdf(
    user_id: uuid.UUID,
    resume: UploadFile = File(...),
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    _verify_management_token(authorization.removeprefix("Bearer "), user_id)
    content = await resume.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "File too large. Max 5MB.")
    if resume.content_type != "application/pdf" and not content.startswith(b"%PDF"):
        raise HTTPException(422, "File must be a PDF.")
    if not content.startswith(b"%PDF"):
        raise HTTPException(422, "File must be a PDF.")
    try:
        extracted = extract_resume_text(content)
    except ValueError as exc:
        raise HTTPException(422, detail={"error": str(exc), "fallback": "paste_text"}) from exc
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "User not found")
    profile.resume_text = extracted
    profile.resume_pdf_name = resume.filename
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"extracted_word_count": len(extracted.split()), "resume_preview": extracted[:200]}


@router.post("/{user_id}/resume/text")
async def upload_resume_text(
    user_id: uuid.UUID,
    body: ResumeTextUpload,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    _verify_management_token(authorization.removeprefix("Bearer "), user_id)
    if len(body.resume_text.split()) < 100:
        raise HTTPException(422, "Resume must be at least 100 words.")
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "User not found")
    profile.resume_text = body.resume_text
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"word_count": len(body.resume_text.split())}
