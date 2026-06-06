import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings
from app.logging_config import redact_url

logger = logging.getLogger(__name__)

_db_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
engine = create_async_engine(_db_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
logger.debug("database engine configured url=%s", redact_url(settings.DATABASE_URL))


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
