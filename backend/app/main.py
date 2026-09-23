"""Точка входа FastAPI-приложения."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import __version__
from .api import admin, analysis, auth, projects
from .config import get_settings
from .db import SessionLocal, get_db, init_db
from .docgen.report import soffice_available
from .parsing.ocr import tesseract_available
from .parsing.parse import SUPPORTED
from .services.llm import LLMClient
from .services.seed import seed
from .services.settings_store import get_setting

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title=f"{settings.app_name} API",
    version=__version__,
    description="ИИ-агент анализа организационной структуры и функционала. Документация API: /api/docs",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (auth.router, projects.router, analysis.router, admin.router):
    app.include_router(r)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/api/meta")
def meta(db: Session = Depends(get_db)) -> dict:
    """Возможности текущей установки (для интерфейса)."""
    from .services.demo import available_sets

    llm = LLMClient(get_setting(db, "llm"))
    demo_sets = available_sets()
    return {
        "app_name": settings.app_name,
        "version": __version__,
        "llm": {"enabled": llm.enabled, "model": llm.model if llm.enabled else "", "vision": llm.vision_enabled,
                "embeddings": llm.embeddings_enabled, "provider": llm.provider},
        "ocr": tesseract_available(),
        "pdf_export": soffice_available(),
        "formats": sorted(SUPPORTED),
        "demo_available": bool(demo_sets),
        "demo_sets": demo_sets,
        "max_upload_mb": settings.max_upload_mb,
    }


# Собранный фронтенд (одноконтейнерный режим): SPA + fallback на index.html
dist = settings.frontend_dist
if dist.exists():
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        target = dist / full_path
        if full_path and target.is_file() and dist in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(dist / "index.html")
