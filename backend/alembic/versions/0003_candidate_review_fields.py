"""Add review_source / review_reason columns to candidates.

Lets the intake pipeline route contextual applications (Sonnet-flagged
"application_needs_review") to manual_review while keeping them distinguishable
from score-band manual_review at the UI layer.

Revision ID: 0003_candidate_review_fields
Revises: 0002_rubric_list
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_candidate_review_fields"
down_revision = "0002_rubric_list"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("candidates", sa.Column("review_source", sa.String(length=32), nullable=True))
    op.add_column("candidates", sa.Column("review_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("candidates", "review_reason")
    op.drop_column("candidates", "review_source")
