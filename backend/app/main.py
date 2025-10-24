from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import create_db_and_tables
from .routers.health import router as health_router
from .routers.articles import router as articles_router
from .scheduler import create_scheduler
from fastapi.staticfiles import StaticFiles
from pathlib import Path

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health_router, prefix="/api")
    app.include_router(articles_router, prefix="/api")

    # serve frontend from project-level /frontend
    static_dir = Path(__file__).resolve().parents[2] / "frontend"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")

    @app.on_event("startup")
    def on_startup() -> None:
        create_db_and_tables()
        # Start scheduler
        scheduler = create_scheduler()
        scheduler.start()

    return app


app = create_app()


