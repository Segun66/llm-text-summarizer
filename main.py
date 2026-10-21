from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.middleware import RequestLoggingMiddleware
from app.api.routes import router
from app.config.settings import Settings
from app.llm.factory import open_gigachat
from app.services.cache import MemorySummaryCache
from app.services.summarizer import SummarizationService
from app.utils.errors import (
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMRequestError,
    LLMServiceError,
    LLMUnavailableError,
)
from app.utils.logging import configure_logging, log_event


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        config = settings if settings is not None else Settings()
        configure_logging(config.log_level, config.app_env)
        log_event("app_started", "startup")
        async with open_gigachat(config) as llm:
            application.state.summarizer = SummarizationService(
                llm,
                MemorySummaryCache(
                    max_entries=config.cache_max_entries, ttl_seconds=config.cache_ttl_seconds
                ),
                model_name=config.model,
            )
            yield

    application = FastAPI(title="LLM Text Summarizer", version="0.1.0", lifespan=lifespan)
    application.add_middleware(RequestLoggingMiddleware)
    application.include_router(router)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, error: RequestValidationError):
        log_event("validation_error", "validation", error_type=type(error).__name__)
        return await request_validation_exception_handler(request, error)

    @application.exception_handler(LLMServiceError)
    async def summarization_error_handler(request: Request, error: LLMServiceError) -> JSONResponse:
        log_event("api_error", "http", error_type=type(error).__name__)
        if isinstance(error, LLMAuthenticationError):
            status, detail = 502, "Ошибка авторизации сервиса в LLM."
        elif isinstance(error, LLMInvalidResponseError):
            status, detail = 502, "LLM вернула некорректное краткое содержание."
        elif isinstance(error, LLMRequestError):
            status, detail = 422, "LLM отклонила текст: проверьте его размер и содержание."
        elif isinstance(error, LLMUnavailableError):
            status, detail = 503, "LLM временно недоступна."
        else:
            status, detail = 502, "Не удалось получить краткое содержание."
        return JSONResponse(status_code=status, content={"detail": detail})

    return application


app = create_app()
