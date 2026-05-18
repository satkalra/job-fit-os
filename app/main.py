from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Base, engine
from app.routers import users
from app.routers.briefing import router as briefing_router
from app.routers.rewrite import router as rewrite_router
from app.services.scheduler import setup_scheduler

_scheduler = None
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    if settings.DATABASE_URL.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    _scheduler = setup_scheduler()
    _scheduler.start()
    yield
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="JobFit OS", lifespan=lifespan)
app.include_router(users.router)
app.include_router(briefing_router)
app.include_router(rewrite_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    status = "running" if (_scheduler and _scheduler.running) else "not_started"
    return {"status": "ok", "scheduler": status, "db": "connected"}
