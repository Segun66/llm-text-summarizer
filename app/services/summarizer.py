import hashlib
import json
import logging
from time import perf_counter

from app.llm.base import LLMClient
from app.llm.prompts import PROMPT_VERSION, summary_messages
from app.models.summarize import SummarizeRequest, SummarizeResponse
from app.services.cache import SummaryCache
from app.utils.errors import LLMUnavailableError
from app.utils.logging import log_event, log_stage
from app.utils.postprocessing import limit_summary
from app.utils.text import normalize_text


class SummarizationService:
    def __init__(
        self, llm: LLMClient, cache: SummaryCache, *, model_name: str = "GigaChat"
    ) -> None:
        self._llm = llm
        self._cache = cache
        self._model_name = model_name

    def _cache_key(self, request: SummarizeRequest) -> str:
        data = json.dumps(
            [
                self._model_name,
                PROMPT_VERSION,
                normalize_text(request.text),
                request.max_length,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    async def summarize(self, request: SummarizeRequest) -> SummarizeResponse:
        started = perf_counter()
        log_event("pipeline_started", "pipeline")
        try:
            result = await self._summarize(request)
        except Exception as error:
            log_event(
                "pipeline_failed",
                "pipeline",
                level=logging.ERROR,
                error_type=type(error).__name__,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise
        log_event(
            "pipeline_finished",
            "pipeline",
            result_status=result.status,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return result

    async def _summarize(self, request: SummarizeRequest) -> SummarizeResponse:
        key = self._cache_key(request)
        with log_stage("cache"):
            cached = await self._cache.get(key)
        log_event("cache_lookup", "cache", cache_status="hit" if cached is not None else "miss")
        if cached is not None:
            return SummarizeResponse(summary=cached, status="success", cached=True)

        with log_stage("prompt"):
            messages = summary_messages(normalize_text(request.text), request.max_length)
        try:
            with log_stage("llm"):
                generated = await self._llm.generate(messages)
        except LLMUnavailableError:
            return SummarizeResponse(
                summary=limit_summary(request.text, request.max_length),
                status="fallback",
                cached=False,
            )
        with log_stage("postprocessing"):
            summary = limit_summary(generated, request.max_length)
        with log_stage("cache"):
            await self._cache.set(key, summary)
        log_event("cache_written", "cache")
        return SummarizeResponse(summary=summary, status="success", cached=False)
