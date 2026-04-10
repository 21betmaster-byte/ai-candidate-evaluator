"""Add incomplete_expiry_days column to app_settings.

Configurable number of days after the reminder before an incomplete
application is auto-rejected.

Revision ID: 0004_incomplete_expiry_days
Revises: 0003_candidate_review_fields
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_incomplete_expiry_days"
down_revision = "0003_candidate_review_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("incomplete_expiry_days", sa.Integer(), nullable=False, server_default="7"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "incomplete_expiry_days")
