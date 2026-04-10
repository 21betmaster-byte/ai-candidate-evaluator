"""Add last_polled_at to app_settings.

Tracks the most recent inbox poll (manual or automatic) so the
dashboard can display when polling last ran.

Revision ID: 0007_last_polled_at
Revises: 0006_candidate_subject_field
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_last_polled_at"
down_revision = "0006_candidate_subject_field"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "last_polled_at")
