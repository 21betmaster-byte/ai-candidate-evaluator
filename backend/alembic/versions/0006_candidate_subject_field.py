"""Add last_inbound_subject to candidates.

Gmail requires a matching Subject header to thread replies into a
conversation. This stores the original inbound subject so outbound
replies can set ``Re: <subject>``.

Revision ID: 0006_candidate_subject_field
Revises: 0005_candidate_thread_fields
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_candidate_subject_field"
down_revision = "0005_candidate_thread_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("last_inbound_subject", sa.String(1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidates", "last_inbound_subject")
