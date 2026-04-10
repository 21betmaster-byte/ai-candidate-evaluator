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
    last_inbound_subject: Mapped[str | None] = mapped_column(String(1024), nullable=True)
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
        "key": "shipped_products",
        "description": (
            "Evidence of owning and launching real products end-to-end — from zero to live users. "
            "Looks for: founding/co-founding products, solo-building MVPs, taking features from idea "
            "to production with measurable adoption. Contributions to large codebases count only if "
            "the candidate owned a distinct surface area (e.g., built a new service, launched a new "
            "product line). Side projects with real users count. Hackathon prototypes and coursework "
            "do not. Also values product management signals: defining roadmaps, writing PRDs, "
            "conducting user research, prioritizing features based on impact vs. effort, and "
            "coordinating cross-functional teams. Rewards relevant domain experience and career "
            "trajectory — candidates who have leveled up (IC to lead, lead to founder) or have "
            "direct domain overlap with the hiring company's space."
        ),
        "weight": 30,
    },
    {
        "key": "technical_depth",
        "description": (
            "Depth of hands-on engineering ability: designing non-trivial systems, choosing "
            "appropriate abstractions, debugging hard problems, and fluency across the stack. "
            "Signals include: system design decisions with clear trade-off reasoning, experience "
            "with infrastructure at scale (databases, queues, caching, CI/CD), low-level debugging "
            "war stories, and breadth across frontend/backend/infra. Certifications and course "
            "completions are weak signals — prioritize evidence of solving real technical challenges."
        ),
        "weight": 25,
    },
    {
        "key": "business_and_product_thinking",
        "description": (
            "Ability to connect work to user value and business outcomes. Thinks in terms of "
            "customers, metrics, retention, and ROI — not just technical elegance. Signals include: "
            "referencing user feedback or data in decisions, understanding unit economics or growth "
            "levers, and articulating why a feature matters beyond the spec. Especially valuable: "
            "evidence of killing features that weren't working or pivoting based on data."
        ),
        "weight": 15,
    },
    {
        "key": "speed_and_bias_to_action",
        "description": (
            "Track record of moving fast under ambiguity and constraint. Signals include: shipping "
            "MVPs in days/weeks not months, rapid iteration cadence, unblocking themselves without "
            "waiting for permission, compressing timelines on tight deadlines, and converting vague "
            "requirements into working software. Hackathon wins, startup velocity, and 'built X in "
            "Y days' narratives are strong signals. Penalize candidates who only describe long "
            "multi-quarter projects with no evidence of urgency."
        ),
        "weight": 15,
    },
    {
        "key": "pedigree_and_relevance",
        "description": (
            "Background signals from education, employers, and community standing. Tier 1 "
            "institutions and companies (per the allow-list in the scoring prompt) are positive "
            "signals. However, a strong builder from an unknown school or company should never be "
            "heavily penalized — this dimension is context, not a filter. Apply the company pedigree "
            "rule: non-Tier-1 companies get a neutral 40."
        ),
        "weight": 10,
    },
    {
        "key": "communication_clarity",
        "description": (
            "Ability to explain complex ideas simply and structure thoughts clearly — in writing "
            "and in presentation. Signals include: well-written README/docs, clear blog posts or "
            "technical writing, structured resume with concrete specifics rather than buzzword soup, "
            "portfolio that tells a coherent story, and any evidence of presenting to non-technical "
            "stakeholders. Penalize vague, jargon-heavy, or disorganized communication. The resume "
            "itself is a data point."
        ),
        "weight": 5,
    },
]

DEFAULT_THRESHOLDS = {
    "auto_fail_ceiling": 48,
    "manual_review_ceiling": 49,
    "auto_pass_floor": 50,
}
