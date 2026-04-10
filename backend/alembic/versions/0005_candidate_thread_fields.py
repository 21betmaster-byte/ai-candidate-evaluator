"""Add gmail_thread_id and rfc822_message_id to candidates.

Stores the Gmail thread ID and RFC 822 Message-ID header from inbound
emails so outbound replies can be threaded into the same conversation.

Revision ID: 0005_candidate_thread_fields
Revises: 0004_incomplete_expiry_days
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_candidate_thread_fields"
down_revision = "0004_incomplete_expiry_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("gmail_thread_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "candidates",
        sa.Column("rfc822_message_id", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidates", "rfc822_message_id")
    op.drop_column("candidates", "gmail_thread_id")
