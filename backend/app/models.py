from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Boolean, JSON, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base


# Status values for candidate
CANDIDATE_STATUSES = (
    "pending",
    "incomplete",
    "manual_review",
    "auto_pass",
    "auto_fail",
    "passed_manual",
    "failed_manual",
    "processing_error",
)

# Job types
JOB_TYPES = (
    "ingest_email",
    "classify",
    "ack_email",
    "parse_resume",
    "fetch_github",
    "fetch_portfolio",
    "discover_secondary",
    "structure_profile",
    "score",
    "decide",
    "send_decision_email",
    "send_template_email",
    "send_reminder",
    "auto_reject_incomplete",
)

JOB_STATUSES = ("pending", "running", "done", "failed")


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    current_evaluation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Manual-review provenance: "intake_review" (Sonnet flagged contextual application)
    # vs "score" (rubric landed in middle band). NULL for non-manual-review candidates.
    review_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_inbound_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gmail_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rfc822_message_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    evaluations: Mapped[list["Evaluation"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    email_logs: Mapped[list["EmailLog"]] = relationship(back_populates="candidate")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)

    # Raw inputs
    source_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Discovered metadata
    github_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    portfolio_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    structured_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Scoring
    scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {dim: {score, reasoning}}
    overall_score: Mapped[float | None] = mapped_column(nullable=True)
    tier: Mapped[str | None] = mapped_column(String(32), nullable=True)  # auto_pass | manual_review | auto_fail
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    candidate: Mapped[Candidate] = relationship(back_populates="evaluations")


class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True, index=True)
    gmail_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direction: Mapped[str] = mapped_column(String(8))  # "in" | "out"
    classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sender: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    body_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    candidate: Mapped[Candidate | None] = relationship(back_populates="email_logs")

    __table_args__ = (
        UniqueConstraint("gmail_message_id", "direction", name="uq_email_log_msg_direction"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProcessingLog(Base):
    """Per-candidate processing timeline rendered on the dashboard detail page."""
    __tablename__ = "processing_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True, index=True)
    step: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(16), default="info")  # info|warn|error
    message: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSettings(Base):
    """Singleton row (id=1) holding configurable settings."""
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    polling_minutes: Mapped[int] = mapped_column(Integer, default=2)
    # Rubric is a list of dimensions: [{"key": str, "description": str, "weight": int}, ...]
    # Weights must sum to 100. Descriptions are fed verbatim to Opus so hiring
    # managers can invent custom dimensions (e.g. "design_taste") and still get
    # calibrated scoring.
    rubric: Mapped[list] = mapped_column(JSONB, default=list)
    tier_thresholds: Mapped[dict] = mapped_column(JSONB, default=dict)
    pass_next_steps_text: Mapped[str] = mapped_column(Text, default="")
    reminder_hours: Mapped[int] = mapped_column(Integer, default=48)
    incomplete_expiry_days: Mapped[int] = mapped_column(Integer, default=7)
    company_name: Mapped[str] = mapped_column(String(128), default="Plum")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


DEFAULT_RUBRIC: list[dict] = [
    {
        "key": "technical_depth",
        "description": (
            "Depth of hands-on engineering skill: shipping non-trivial systems, "
            "picking appropriate abstractions, and fluency with the tools in the stack."
        ),
        "weight": 35,
    },
    {
        "key": "shipped_products",
        "description": (
            "Evidence of owning and launching real products end-to-end — from "
            "first line of code to real users — not just contributing to large codebases."
        ),
        "weight": 30,
    },
    {
        "key": "business_thinking",
        "description": (
            "Ability to connect engineering decisions to product and business outcomes. "
            "Thinks in terms of users, metrics, and trade-offs — not just tickets."
        ),
        "weight": 20,
    },
    {
        "key": "speed_of_execution",
        "description": (
            "Track record of moving fast without breaking things that matter. "
            "Ships iterations, unblocks self, and converts ambiguity into working software quickly."
        ),
        "weight": 15,
    },
]

DEFAULT_THRESHOLDS = {
    "auto_fail_ceiling": 49,
    "manual_review_ceiling": 69,
    "auto_pass_floor": 70,
}
