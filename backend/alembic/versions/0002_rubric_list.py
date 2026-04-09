"""Move rubric from flat {key: weight} dict to a list of dimensions with descriptions.

Hiring managers now author rubrics in the dashboard: each dimension has a key,
a free-text description (fed to Opus verbatim), and a weight. Keeps the Opus
contract honest when hiring managers invent their own dimensions.

Revision ID: 0002_rubric_list
Revises: 0001
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "0002_rubric_list"
down_revision = "0001"
branch_labels = None
depends_on = None


# Seed descriptions for the four default dimensions so existing deployments
# get a meaningful, editable rubric after the migration (not blank strings).
_DEFAULT_DESCRIPTIONS = {
    "technical_depth": (
        "Depth of hands-on engineering skill: shipping non-trivial systems, "
        "picking appropriate abstractions, and fluency with the tools in the stack."
    ),
    "shipped_products": (
        "Evidence of owning and launching real products end-to-end — from "
        "first line of code to real users — not just contributing to large codebases."
    ),
    "business_thinking": (
        "Ability to connect engineering decisions to product and business outcomes. "
        "Thinks in terms of users, metrics, and trade-offs — not just tickets."
    ),
    "speed_of_execution": (
        "Track record of moving fast without breaking things that matter. "
        "Ships iterations, unblocks self, and converts ambiguity into working software quickly."
    ),
}


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "rubric",
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # Backfill: {key: weight} -> [{key, description, weight}, ...].
    # CROSS JOIN LATERAL on the defaults blob so we can look up a seeded
    # description per key. Unknown keys get an empty description — the
    # hiring manager will fill them in from the dashboard.
    op.execute(
        sa.text(
            """
            UPDATE app_settings
            SET rubric = COALESCE(
                (
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'key', kv.key,
                            'description', COALESCE(d.defaults ->> kv.key, ''),
                            'weight', (kv.value)::int
                        )
                    )
                    FROM jsonb_each(rubric_weights) AS kv
                    CROSS JOIN (SELECT CAST(:defaults AS jsonb) AS defaults) AS d
                ),
                '[]'::jsonb
            )
            """
        ).bindparams(defaults=json.dumps(_DEFAULT_DESCRIPTIONS))
    )

    op.alter_column("app_settings", "rubric", nullable=False)
    op.drop_column("app_settings", "rubric_weights")


def downgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "rubric_weights",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE app_settings
        SET rubric_weights = COALESCE(
            (
                SELECT jsonb_object_agg(elem->>'key', (elem->>'weight')::int)
                FROM jsonb_array_elements(rubric) AS elem
            ),
            '{}'::jsonb
        )
        """
    )
    op.drop_column("app_settings", "rubric")
