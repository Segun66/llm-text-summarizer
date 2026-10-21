import json
import logging
import math
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")

_EVENTS = {
    "request_started",
    "request_finished",
    "pipeline_started",
    "pipeline_finished",
    "pipeline_failed",
    "cache_lookup",
    "cache_written",
    "stage_finished",
    "llm_retry",
    "api_error",
    "validation_error",
    "app_started",
}
_STAGES = {
    "http",
    "validation",
    "pipeline",
    "cache",
    "prompt",
    "llm",
    "postprocessing",
    "oauth",
    "completion",
    "startup",
}


class JsonFormatter(logging.Formatter):
    """Allowlist-only output: never render messages, args, headers or traceback."""

    def __init__(self, app_env: str = "dev") -> None:
        super().__init__()
        self.app_env = app_env if app_env in {"dev", "prod"} else "dev"

    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", request_id_context.get())
        try:
            request_id = str(UUID(request_id)) if isinstance(request_id, str) else "-"
        except ValueError:
            request_id = "-"
        event = getattr(record, "event", None)
        stage = getattr(record, "stage", None)
        data = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": logging.getLevelName(record.levelno),
            "app_env": self.app_env,
            "request_id": request_id,
            "event": event if isinstance(event, str) and event in _EVENTS else "external_log",
        }
        if isinstance(stage, str) and stage in _STAGES:
            data["stage"] = stage
        for field in ("duration_ms", "retry_in_seconds"):
            value = getattr(record, field, None)
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                data[field] = round(value, 3)
        for field in ("attempt", "next_attempt", "status_code"):
            value = getattr(record, field, None)
            if type(value) is int:
                data[field] = value
        cache_status = getattr(record, "cache_status", None)
        if cache_status in ("hit", "miss", "expired"):
            data["cache_status"] = cache_status
        result_status = getattr(record, "result_status", None)
        if result_status in ("success", "fallback"):
            data["result_status"] = result_status
        error_type = getattr(record, "error_type", None)
        if record.exc_info and record.exc_info[0] is not None:
            error_type = record.exc_info[0].__name__
        if isinstance(error_type, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", error_type):
            data["error_type"] = error_type
        return json.dumps(data, ensure_ascii=False)


def log_event(event: str, stage: str, *, level: int = logging.INFO, **fields: object) -> None:
    logging.getLogger("app").log(level, event, extra={"event": event, "stage": stage, **fields})


def configure_logging(level: str, app_env: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(app_env))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Framework/HTTP logs go through the same formatter, including exception records.
    for name in ("app", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.NOTSET)


@contextmanager
def log_stage(stage: str):
    started = perf_counter()
    try:
        yield
    except Exception as error:
        log_event(
            "stage_finished",
            stage,
            level=logging.ERROR,
            duration_ms=(perf_counter() - started) * 1000,
            error_type=type(error).__name__,
        )
        raise
    else:
        log_event("stage_finished", stage, duration_ms=(perf_counter() - started) * 1000)
