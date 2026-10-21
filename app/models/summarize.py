from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Character limit bounds request size, but does not guarantee fitting a model's token context.
InputText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class SummarizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: InputText
    max_length: int = Field(default=300, ge=50, le=1000, strict=True)


class SummarizeResponse(BaseModel):
    summary: str
    status: Literal["success", "fallback"]
    cached: bool


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ErrorResponse(BaseModel):
    detail: str


class ValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ValidationErrorResponse(BaseModel):
    detail: list[ValidationIssue]
