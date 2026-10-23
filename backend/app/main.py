import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.agents.graph import build_graph, set_graph
from app.api.chat import router as chat_router
from app.api.documents import router as document_router
from app.api.system import router as system_router
from app.config import get_settings
from app.db import session_scope
from app.errors import AppError
from app.ingestion.jobs import start_worker, stop_worker
from app.logging_config import configure_logging
from app.seed.seed import seed_demo

logger = logging.getLogger(__name__)


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    problems = settings.production_problems()
    if problems and settings.app_env == "production":
        raise RuntimeError("Production configuration is incomplete: " + "; ".join(problems))
    if settings.auto_migrate and settings.app_env != "production":
        _migrate()
    async with AsyncPostgresSaver.from_conn_string(settings.psycopg_url()) as saver:
        await saver.setup()
        set_graph(build_graph(saver))
        if settings.seed_demo_data:
            with session_scope() as db:
                summary = seed_demo(db)
            logger.info("demo seed %s", summary.get("seeded"))
        if settings.embed_worker:
            start_worker()
        yield
        stop_worker()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ManualMind API",
        version="1.0.0",
        summary="Hybrid manual retrieval and read-only manufacturer tools for fictional demo equipment.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins(),
        allow_origin_regex=r"https://[a-zA-Z0-9-]+\.vercel\.app" if settings.cors_allow_vercel_previews else None,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Tenant-Id", "X-User-Id", "X-Request-Id"],
    )
    app.include_router(document_router)
    app.include_router(chat_router)
    app.include_router(system_router)

    @app.exception_handler(AppError)
    async def app_error(_request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    return app


app = create_app()
