"""HTTP API. Запуск: python -m uvicorn api:app --reload."""
from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.schemas import ErrorResponse, HealthResponse, MatchRequest, MatchResponse
from app.config import DEFAULT_CSV, ROOT
from app.services.matcher import EventMatcher
from app.api.deadline import RequestClockMiddleware
from app.api.errors import install_error_handlers


DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"


def create_app(*, csv_path: str | Path | None = None, use_llm: bool | None = None,
               matcher: EventMatcher | None = None, cors_origins: list[str] | None = None) -> FastAPI:
    """Фабрика приложения. Внедрённый matcher принадлежит вызывающему коду.

    CSV читается только при lifespan startup, один раз на процесс/worker.
    Ошибка CSV останавливает запуск, а не маскируется под пустой каталог.
    """
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        enabled = use_llm
        if enabled is None:
            mode = os.getenv("MATCHER_USE_LLM", "true").strip().lower()
            if mode not in {"true", "false", "1", "0"}:
                raise ValueError("MATCHER_USE_LLM должен быть true/false или 1/0")
            enabled = mode in {"true", "1"}
        instance = matcher if matcher is not None else EventMatcher(
            csv_path if csv_path is not None else os.getenv("MATCHER_CSV_PATH") or DEFAULT_CSV,
            use_llm=enabled,
        )
        application.state.matcher = instance
        try:
            yield
        finally:
            if matcher is None:
                instance.close()
            del application.state.matcher

    application = FastAPI(
        title="NurSolution — подбор event-подрядчиков", version="1.0.0",
        description="До трёх подрядчиков с проверяемыми объяснениями и аналитикой отказов.",
        lifespan=lifespan,
    )
    origins = cors_origins if cors_origins is not None else [
        origin.strip() for origin in os.getenv("CORS_ORIGINS", DEFAULT_ORIGINS).split(",") if origin.strip()]
    application.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=False,
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )
    application.add_middleware(RequestClockMiddleware)

    install_error_handlers(application)

    @application.get("/health", response_model=HealthResponse, summary="Проверить готовность каталога")
    def health(request: Request):
        return {"status": "ok", "total_profiles": len(request.app.state.matcher.contractors)}

    @application.get("/catalog", summary="Варианты для формы подбора")
    def catalog(request: Request) -> dict[str, object]:
        profiles = request.app.state.matcher.contractors
        return {
            "total_profiles": len(profiles),
            "cities": sorted({p.city for p in profiles}),
            "categories": sorted({v for p in profiles for v in p.categories}),
            "event_types": sorted({v for p in profiles for v in p.event_formats}),
            "languages": sorted({v for p in profiles for v in p.languages}),
        }

    @application.post(
        "/match", response_model=MatchResponse, summary="Подобрать подрядчиков",
        responses={422: {"model": ErrorResponse, "description": "Ошибка параметров запроса"},
                   500: {"model": ErrorResponse, "description": "Внутренняя ошибка"}},
    )
    async def match(payload: MatchRequest, request: Request):
        instance = request.app.state.matcher
        return await instance.amatch(
            deadline=request.state.request_started + instance.settings.request_timeout,
            **payload.model_dump())

    frontend = ROOT / "frontend"
    application.mount("/assets", StaticFiles(directory=frontend), name="assets")

    @application.get("/", include_in_schema=False)
    def index():
        return FileResponse(frontend / "index.html")

    return application


app = create_app()
