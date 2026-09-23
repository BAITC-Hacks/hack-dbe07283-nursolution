"""Публичный JSON-контракт API подбора подрядчиков (Pydantic v2)."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.validation import iso_date


Text = Annotated[str, Field(min_length=1, max_length=200)]
Count = Annotated[int, Field(ge=0)]


class MatchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, strict=True,
        json_schema_extra={"examples": [{
            "city": "Алматы", "date": "2026-09-26", "event_type": "корпоратив",
            "category": "Ведущий", "budget": 1000000, "language": "русский", "duration": 4,
        }]},
    )

    city: Text
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Дата мероприятия, YYYY-MM-DD")
    event_type: Text
    category: Text
    budget: float = Field(ge=0, allow_inf_nan=False, description="Бюджет в тенге; JSON-число")
    language: Text | None = None
    duration: float | None = Field(default=None, gt=0, allow_inf_nan=False, description="Часы на площадке")

    @field_validator("date")
    @classmethod
    def valid_calendar_date(cls, value: str) -> str:
        return iso_date(value)


class Evidence(BaseModel):
    field: Literal["description"]
    quote: str


class ContractorCard(BaseModel):
    id: str
    anon_name: str
    category: str
    categories: list[str]
    city: str
    price_from_kzt: Count
    explanation: str
    explanation_source: Literal["python", "openai"]
    evidence: Evidence | None


class RejectionCounts(BaseModel):
    city: Count
    category: Count
    budget: Count
    date: Count
    event_type: Count
    language: Count
    duration: Count
    duration_unknown: Count


class Suggestion(BaseModel):
    field: Literal["budget", "date", "event_type", "language", "duration"]
    value: int | float | str
    candidate_count: Annotated[int, Field(gt=0)]
    candidate_ids: list[str]
    message: str


class MatchResponse(BaseModel):
    status: Literal["matched", "no_category_in_city", "no_matches"]
    cards: Annotated[list[ContractorCard], Field(max_length=3)]
    message: str
    total_profiles: Count
    scope_count: Count
    eligible_count: Count
    rejection_counts: RejectionCounts
    suggestions: list[Suggestion]
    warning: str | None = None


class FieldError(BaseModel):
    field: str
    message: str
    type: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: list[FieldError] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    total_profiles: Count
