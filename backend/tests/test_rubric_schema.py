"""Pydantic-level tests for RubricDimension + SettingsModel validation.

These run in <1s without any database. They lock down the invariants the
hiring manager's dashboard depends on:

  1. Weights sum to exactly 100
  2. Keys are unique
  3. Keys are valid slugs
  4. Descriptions are non-blank and length-bounded
  5. Custom dimension names (e.g. "design_taste") are accepted

If any of these break, the settings form in the dashboard silently accepts
garbage that the backend later rejects — or worse, quietly feeds malformed
rubrics to Opus. Both are demo-disaster scenarios, so keep this file green.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import RubricDimension, SettingsModel


DEFAULT_THRESHOLDS = {
    "auto_fail_ceiling": 49,
    "manual_review_ceiling": 69,
    "auto_pass_floor": 70,
}


def _valid_settings(**overrides):
    base = dict(
        polling_minutes=2,
        rubric=[
            {"key": "technical_depth", "description": "engineering chops", "weight": 50},
            {"key": "shipped_products", "description": "track record of launches", "weight": 50},
        ],
        tier_thresholds=DEFAULT_THRESHOLDS,
        pass_next_steps_text="Reply with times.",
        reminder_hours=48,
        incomplete_expiry_days=7,
        company_name="Curator",
    )
    base.update(overrides)
    return base


# ---------------------------- RubricDimension ----------------------------


class TestRubricDimension:
    def test_valid_default_shape(self):
        d = RubricDimension(key="technical_depth", description="engineering chops", weight=35)
        assert d.key == "technical_depth"
        assert d.weight == 35

    def test_custom_dimension_name_is_accepted(self):
        # Hiring managers must be able to invent dimensions the code has never heard of.
        d = RubricDimension(key="design_taste", description="eye for visual craft", weight=20)
        assert d.key == "design_taste"

    @pytest.mark.parametrize(
        "bad_key",
        [
            "Technical_Depth",   # uppercase
            "technical-depth",   # hyphen
            "technical depth",   # whitespace
            "_leading",          # leading underscore
            "x" * 65,            # too long
            "",                  # empty
            "日本語",            # non-ascii
            "tech@depth",        # special char
        ],
    )
    def test_invalid_key_rejected(self, bad_key):
        with pytest.raises(ValidationError):
            RubricDimension(key=bad_key, description="x", weight=10)

    @pytest.mark.parametrize("bad_weight", [-1, 101, 1000])
    def test_weight_out_of_range_rejected(self, bad_weight):
        with pytest.raises(ValidationError):
            RubricDimension(key="technical_depth", description="x", weight=bad_weight)

    def test_blank_description_rejected(self):
        with pytest.raises(ValidationError):
            RubricDimension(key="technical_depth", description="   ", weight=10)

    def test_description_length_cap(self):
        with pytest.raises(ValidationError):
            RubricDimension(
                key="technical_depth",
                description="x" * 2001,
                weight=10,
            )

    def test_description_and_key_are_stripped(self):
        d = RubricDimension(
            key="technical_depth",
            description="  engineering chops  ",
            weight=35,
        )
        assert d.description == "engineering chops"


# ---------------------------- SettingsModel ----------------------------


class TestSettingsModel:
    def test_valid_round_trip(self):
        m = SettingsModel(**_valid_settings())
        assert len(m.rubric) == 2
        assert m.rubric[0].key == "technical_depth"

    def test_weights_must_sum_to_100(self):
        for total_fail in [0, 50, 99, 101, 150, 200]:
            with pytest.raises(ValidationError, match="sum to 100"):
                SettingsModel(
                    **_valid_settings(
                        rubric=[
                            {"key": "technical_depth", "description": "x", "weight": total_fail // 2},
                            {"key": "shipped_products", "description": "x", "weight": total_fail - total_fail // 2},
                        ]
                    )
                )

    def test_duplicate_keys_rejected(self):
        with pytest.raises(ValidationError, match="unique"):
            SettingsModel(
                **_valid_settings(
                    rubric=[
                        {"key": "technical_depth", "description": "x", "weight": 50},
                        {"key": "technical_depth", "description": "y", "weight": 50},
                    ]
                )
            )

    def test_empty_rubric_rejected(self):
        with pytest.raises(ValidationError, match="at least one"):
            SettingsModel(**_valid_settings(rubric=[]))

    def test_single_dimension_at_100_percent_allowed(self):
        m = SettingsModel(
            **_valid_settings(
                rubric=[{"key": "builder_mindset", "description": "x", "weight": 100}]
            )
        )
        assert len(m.rubric) == 1
        assert m.rubric[0].weight == 100

    def test_many_custom_dimensions(self):
        # Hiring managers can go wide — 10 custom dimensions, all at 10%.
        rubric = [
            {"key": f"dim_{i}", "description": f"custom dimension {i}", "weight": 10}
            for i in range(10)
        ]
        m = SettingsModel(**_valid_settings(rubric=rubric))
        assert sum(d.weight for d in m.rubric) == 100

    @pytest.mark.parametrize("polling", [0, -1, 121, 1000])
    def test_polling_minutes_out_of_range_rejected(self, polling):
        with pytest.raises(ValidationError):
            SettingsModel(**_valid_settings(polling_minutes=polling))

    def test_preserves_dimension_order(self):
        rubric = [
            {"key": "dim_c", "description": "c", "weight": 10},
            {"key": "dim_a", "description": "a", "weight": 30},
            {"key": "dim_b", "description": "b", "weight": 60},
        ]
        m = SettingsModel(**_valid_settings(rubric=rubric))
        assert [d.key for d in m.rubric] == ["dim_c", "dim_a", "dim_b"]
