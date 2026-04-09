"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("current_evaluation_id", sa.Integer),
        sa.Column("missing_items", JSONB),
        sa.Column("last_inbound_message_id", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_candidates_email", "candidates", ["email"])
    op.create_index("ix_candidates_status", "candidates", ["status"])

    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("candidate_id", sa.Integer, sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("superseded", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("source_message_id", sa.String(255)),
        sa.Column("raw_resume_text", sa.Text),
        sa.Column("resume_filename", sa.String(512)),
        sa.Column("github_url", sa.String(1024)),
        sa.Column("portfolio_url", sa.String(1024)),
        sa.Column("github_data", JSONB),
        sa.Column("portfolio_data", JSONB),
        sa.Column("structured_profile", JSONB),
        sa.Column("scores", JSONB),
        sa.Column("overall_score", sa.Float),
        sa.Column("tier", sa.String(32)),
        sa.Column("decision_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_evaluations_candidate_id", "evaluations", ["candidate_id"])

    op.create_table(
        "email_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("candidate_id", sa.Integer, sa.ForeignKey("candidates.id")),
        sa.Column("gmail_message_id", sa.String(255)),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("classification", sa.String(64)),
        sa.Column("sender", sa.String(320)),
        sa.Column("subject", sa.String(1024)),
        sa.Column("body_snippet", sa.Text),
        sa.Column("template_used", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("gmail_message_id", "direction", name="uq_email_log_msg_direction"),
    )
    op.create_index("ix_email_logs_candidate_id", "email_logs", ["candidate_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("candidate_id", sa.Integer, sa.ForeignKey("candidates.id")),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("payload", JSONB),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="5"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_jobs_candidate_id", "jobs", ["candidate_id"])
    op.create_index("ix_jobs_type", "jobs", ["type"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_next_run_at", "jobs", ["next_run_at"])

    op.create_table(
        "processing_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("candidate_id", sa.Integer, sa.ForeignKey("candidates.id")),
        sa.Column("step", sa.String(64), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("meta", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_processing_logs_candidate_id", "processing_logs", ["candidate_id"])

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("polling_minutes", sa.Integer, nullable=False, server_default="2"),
        sa.Column("rubric_weights", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("tier_thresholds", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("pass_next_steps_text", sa.Text, nullable=False, server_default=""),
        sa.Column("reminder_hours", sa.Integer, nullable=False, server_default="48"),
        sa.Column("company_name", sa.String(128), nullable=False, server_default="Plum"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Seed singleton settings row
    op.execute("""
        INSERT INTO app_settings (id, polling_minutes, rubric_weights, tier_thresholds, pass_next_steps_text, reminder_hours, company_name)
        VALUES (
            1,
            2,
            '{"technical_depth": 35, "shipped_products": 30, "business_thinking": 20, "speed_of_execution": 15}'::jsonb,
            '{"auto_fail_ceiling": 49, "manual_review_ceiling": 69, "auto_pass_floor": 70}'::jsonb,
            'Here''s where it gets fun — we''d love for you to tackle a take-home.

**The problem.** Every company with customers drowns in support email. A "where''s my order," a refund request, a how-do-I question, an angry rant, a feature request, and a sales pitch all land in the same inbox — and someone has to read each one, figure out what it is, dig up the context (order history, past tickets, the relevant help-doc paragraph), write a reply that sounds like a human wrote it, and decide whether to just send it or escalate to a teammate. It''s repetitive, judgment-heavy, and the cost of getting it wrong is a churned customer or a viral tweet. Almost every answer already lives somewhere — in the docs, in the order system, in a past reply. It''s a near-perfect agent problem.

**The assignment.** Design and build an AI agent that takes an incoming support email and produces (a) a classification of what it is, (b) the context it pulled to answer it, and (c) a drafted reply in the company''s voice. Default to sending — if the agent can confidently answer, it should reply on its own. Escalate to a human only when it genuinely can''t (missing info, sensitive situation, judgment call beyond its reach) — and when it does, it should explain why.

**What we want to see:**
• A working prototype — any stack you like (Claude Agent SDK, LangGraph, n8n, raw Python — your call). A mocked inbox + a tiny fake knowledge base + a fake orders/users table is fine; you don''t need to wire up real systems.
• 8-12 sample emails covering the messy edge cases (clear refund request, vague complaint, angry customer, a question the docs don''t answer, a sales pitch, a "thanks!" that needs no reply — surprise us)
• Your thinking on tone, retrieval, how the agent decides it''s confident enough to send vs. when to escalate (the bar should be "respond whenever you can"), and how you''d keep it from confidently saying something wrong
• A short Loom (≤5 min) walking us through the problem, your design choices, and a live demo

**Timeline:** take up to 5 days. Reply to this email with a link to your repo and the Loom when you''re ready.

No trick questions, no gotchas. We care about how you think about real problems and how you ship.',
            48,
            'Plum'
        )
    """)


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("processing_logs")
    op.drop_table("jobs")
    op.drop_table("email_logs")
    op.drop_table("evaluations")
    op.drop_table("candidates")
