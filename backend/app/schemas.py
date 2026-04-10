from datetime import datetime
from typing import Any
import re

from pydantic import BaseModel, Field, field_validator


class CandidateRow(BaseModel):
    id: int
    email: str
    name: str | None
    status: str
    overall_score: float | None
    created_at: datetime

    class Config:
        from_attributes = True


class ScoreEntry(BaseModel):
    score: int
    reasoning: str


class EvaluationDetail(BaseModel):
    id: int
    superseded: bool
    github_url: str | None
    portfolio_url: str | None
    resume_filename: str | None
    structured_profile: dict | None
    scores: dict[str, ScoreEntry] | None
    overall_score: float | None
    tier: str | None
    decision_reason: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ProcessingLogEntry(BaseModel):
    id: int
    step: str
    level: str
    message: str
    meta: dict | None
    created_at: datetime

    class Config:
        from_attributes = True


class LogEntryWithCandidate(ProcessingLogEntry):
    candidate_id: int | None
    candidate_name: str | None
    candidate_email: str | None


class EmailHistoryEntry(BaseModel):
    """One row of the email conversation between us and the candidate.

    Bodies are fetched from Gmail on demand at request time. If Gmail can't
    return the body (transient outage, deleted message, missing message id for
    an outbound row), `body` is None and `body_error` explains why — the UI
    renders a placeholder rather than crashing the page.
    """

    id: int
    direction: str  # "in" | "out"
    sender: str | None
    subject: str | None
    classification: str | None
    template_used: str | None
    created_at: datetime
    body: str | None
    body_error: str | None


class CandidateDetail(BaseModel):
    id: int
    email: str
    name: str | None
    status: str
    missing_items: list[str] | None
    review_source: str | None
    review_reason: str | None
    created_at: datetime
    updated_at: datetime
    current_evaluation: EvaluationDetail | None
    logs: list[ProcessingLogEntry]
    email_history: list[EmailHistoryEntry]


class ManualDecisionRequest(BaseModel):
    decision: str  # "pass" | "fail"


_RUBRIC_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")


class RubricDimension(BaseModel):
    """One line of the hiring rubric.

    `key` is the stable identifier Opus echoes back in its scores dict. It must
    be a slug so it stays valid as a JSON key and so two dimensions can't
    collide via whitespace or casing tricks. `description` is passed verbatim
    to Opus and acts as the authoritative definition of what the dimension
    measures — hiring managers author it.
    """

    key: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1, max_length=2000)
    weight: int = Field(..., ge=0, le=100)

    @field_validator("key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        v = v.strip()
        if not _RUBRIC_KEY_RE.match(v):
            raise ValueError(
                "key must be lowercase letters, digits, and underscores "
                "(e.g. 'technical_depth'), 1–64 chars, starting with a letter or digit"
            )
        return v

    @field_validator("description")
    @classmethod
    def _strip_description(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("description must not be blank")
        return v


class SettingsModel(BaseModel):
    polling_minutes: int = Field(..., ge=1, le=120)
    rubric: list[RubricDimension]
    tier_thresholds: dict[str, int]
    pass_next_steps_text: str = ""
    reminder_hours: int = Field(..., ge=1, le=336)
    incomplete_expiry_days: int = Field(..., ge=1, le=30)
    company_name: str = Field(..., min_length=1, max_length=128)
    last_polled_at: datetime | None = None

    class Config:
        from_attributes = True

    @field_validator("rubric")
    @classmethod
    def _validate_rubric(cls, v: list[RubricDimension]) -> list[RubricDimension]:
        if not v:
            raise ValueError("rubric must have at least one dimension")
        keys = [d.key for d in v]
        if len(keys) != len(set(keys)):
            raise ValueError("rubric dimension keys must be unique")
        total = sum(d.weight for d in v)
        if total != 100:
            raise ValueError(f"rubric weights must sum to 100 (got {total})")
        return v


# ── Metrics ──────────────────────────────────────────────────────────


class NotTrackedMetric(BaseModel):
    value: None = None
    reason: str


class TechnicalMetrics(BaseModel):
    first_response_latency_seconds: float | None
    evaluation_latency_seconds: float | None
    decision_email_latency_seconds: float | None
    processing_error_rate: float | None
    retry_success_rate: float | None
    override_rate: float | None
    edge_case_classification_accuracy: NotTrackedMetric
    duplicate_detection_accuracy: NotTrackedMetric
    email_bounce_rate: NotTrackedMetric
    agent_uptime: NotTrackedMetric
    dashboard_load_time: NotTrackedMetric


class FunnelEntry(BaseModel):
    status: str
    count: int


class DailyCount(BaseModel):
    date: str
    count: int


class BusinessMetrics(BaseModel):
    funnel: list[FunnelEntry]
    avg_time_to_decision_seconds: float | None
    pass_rate: float | None
    avg_score: float | None
    candidates_per_day: list[DailyCount]
    total_llm_input_tokens: int
    total_llm_output_tokens: int


class MetricsResponse(BaseModel):
    technical: TechnicalMetrics
    business: BusinessMetrics
