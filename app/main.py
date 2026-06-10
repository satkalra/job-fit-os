from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Base, engine
from app.logging_config import configure_logging, redact_url
from app.routers import users
from app.routers.briefing import router as briefing_router
from app.routers.dev import router as dev_router
from app.routers.jobs import router as jobs_router
from app.routers.ops import router as ops_router
from app.routers.rewrite import router as rewrite_router
from app.services.scheduler import setup_scheduler

configure_logging()
logger = logging.getLogger(__name__)
_scheduler = None
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    logger.info("app startup environment=%s database=%s", settings.ENVIRONMENT, redact_url(settings.DATABASE_URL))
    if settings.DATABASE_URL.startswith("sqlite"):
        logger.debug("creating sqlite database tables")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    _scheduler = setup_scheduler()
    _scheduler.start()
    logger.info("scheduler started running=%s jobs=%s", _scheduler.running, len(_scheduler.get_jobs()))
    yield
    if _scheduler and _scheduler.running:
        logger.info("scheduler shutdown requested")
        _scheduler.shutdown(wait=False)


app = FastAPI(title="JobFit OS", lifespan=lifespan)
app.include_router(users.router)
app.include_router(briefing_router)
app.include_router(jobs_router)
app.include_router(ops_router)
app.include_router(rewrite_router)
if settings.ENVIRONMENT != "production":
    app.include_router(dev_router)
    logger.info("dev router mounted (environment=%s)", settings.ENVIRONMENT)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/signup")
async def signup_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    status = "running" if (_scheduler and _scheduler.running) else "not_started"
    return {"status": "ok", "scheduler": status, "db": "connected"}
