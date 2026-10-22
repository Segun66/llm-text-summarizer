from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.models.summarize import (
    ErrorResponse,
    HealthResponse,
    SummarizeRequest,
    SummarizeResponse,
    ValidationErrorResponse,
)
from app.services.summarizer import SummarizationService

router = APIRouter()


def get_summarizer(request: Request) -> SummarizationService:
    return request.app.state.summarizer


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.post(
    "/summarize",
    response_model=SummarizeResponse,
    responses={
        422: {"model": ErrorResponse | ValidationErrorResponse},
        502: {"model": ErrorResponse},
        503: {
            "model": SummarizeResponse | ErrorResponse,
            "description": "Model unavailable; fallback or dependency error returned",
        },
    },
)
async def summarize(
    payload: SummarizeRequest,
    response: Response,
    service: Annotated[SummarizationService, Depends(get_summarizer)],
) -> SummarizeResponse:
    result = await service.summarize(payload)
    if result.status == "fallback":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
