import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"


def generate_rewrite_token(user_id: uuid.UUID | str, job_id: uuid.UUID | str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRY_DAYS)
    payload = {
        "user_id": str(user_id),
        "job_id": str(job_id),
        "exp": expire,
        "type": "rewrite",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
        if payload.get("type") != "rewrite":
            raise JWTError("wrong token type")
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}") from e
