"""Tests for pipeline/score.py — the Opus-facing scorer.

The whole "hiring managers author their own rubric" story hinges on Opus
receiving the hiring manager's dimension *descriptions* verbatim in the
prompt. If that stops happening — a refactor strips descriptions, or a
rename breaks the rendering helper — the product silently regresses to
"Opus guesses what 'design_taste' means" and nobody notices until scores
start looking weird.

These tests pin the contract down:
  1. The prompt text contains every dimension's key, weight, AND description.
  2. Opus responses with custom keys are mapped back correctly.
  3. Missing/invalid Opus responses degrade to zero scores, not 500s.
  4. compute_weighted respects the rubric weights exactly.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.pipeline import score as score_mod
from app.pipeline.score import compute_weighted, score_candidate


CUSTOM_RUBRIC = [
    {
        "key": "design_taste",
        "description": "Eye for visual craft, proportion, and restraint.",
        "weight": 40,
    },
    {
        "key": "storytelling",
        "description": "Explains their work like a PM pitching a narrative.",
        "weight": 35,
    },
    {
        "key": "builder_mindset",
        "description": "Strong bias to shipping over perfect planning.",
        "weight": 25,
    },
]


class TestRenderRubric:
    def test_prompt_contains_every_key_weight_and_description(self):
        """The hiring manager's descriptions must reach Opus verbatim."""
        rendered = score_mod._render_rubric(CUSTOM_RUBRIC)
        for dim in CUSTOM_RUBRIC:
            assert dim["key"] in rendered
            assert f"{dim['weight']}%" in rendered
            assert dim["description"] in rendered

    def test_prompt_order_matches_rubric_order(self):
        rendered = score_mod._render_rubric(CUSTOM_RUBRIC)
        positions = [rendered.index(d["key"]) for d in CUSTOM_RUBRIC]
        assert positions == sorted(positions), "dimensions must render in rubric order"


class TestScoreCandidateCustomDimensions:
    def _opus_response_for(self, rubric, value: int = 80) -> str:
        import json
        return json.dumps(
            {
                "scores": {d["key"]: {"score": value, "reasoning": f"ok for {d['key']}"} for d in rubric},
                "decision_reason": "Looks like a builder.",
            }
        )

    def test_custom_dimensions_round_trip(self):
        opus_raw = self._opus_response_for(CUSTOM_RUBRIC, value=80)

        with patch.object(score_mod, "call_opus", return_value=opus_raw):
            result = score_candidate(profile={"name": "Test"}, rubric=CUSTOM_RUBRIC)

        assert set(result["scores"].keys()) == {"design_taste", "storytelling", "builder_mindset"}
        for key in result["scores"]:
            assert result["scores"][key]["score"] == 80
            assert f"ok for {key}" in result["scores"][key]["reasoning"]
        assert result["overall_score"] == 80.0  # all 80s, weighted, = 80
        assert result["decision_reason"] == "Looks like a builder."

    def test_opus_prompt_includes_descriptions(self):
        """Spot-check the actual call_opus(user, ...) argument."""
        captured = {}

        def _fake(system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return '{"scores":{},"decision_reason":""}'

        with patch.object(score_mod, "call_opus", side_effect=_fake):
            score_candidate(profile={}, rubric=CUSTOM_RUBRIC)

        for dim in CUSTOM_RUBRIC:
            assert dim["description"] in captured["user"], (
                f"description for {dim['key']} was not sent to Opus"
            )
        # System prompt must tell Opus to honor descriptions.
        assert "description" in captured["system"].lower()

    def test_missing_keys_in_opus_response_become_zero(self):
        """Opus can forget a key under load; we must not 500."""
        partial = '{"scores":{"design_taste":{"score":90,"reasoning":"great"}},"decision_reason":""}'
        with patch.object(score_mod, "call_opus", return_value=partial):
            result = score_candidate(profile={}, rubric=CUSTOM_RUBRIC)

        assert result["scores"]["design_taste"]["score"] == 90
        assert result["scores"]["storytelling"]["score"] == 0
        assert result["scores"]["builder_mindset"]["score"] == 0
        # overall = 90*40/100 = 36
        assert result["overall_score"] == 36.0

    def test_out_of_range_scores_clamped(self):
        bad = '{"scores":{"design_taste":{"score":9999,"reasoning":""},"storytelling":{"score":-5,"reasoning":""},"builder_mindset":{"score":50,"reasoning":""}},"decision_reason":""}'
        with patch.object(score_mod, "call_opus", return_value=bad):
            result = score_candidate(profile={}, rubric=CUSTOM_RUBRIC)
        assert result["scores"]["design_taste"]["score"] == 100
        assert result["scores"]["storytelling"]["score"] == 0
        assert result["scores"]["builder_mindset"]["score"] == 50

    def test_non_integer_score_from_opus_becomes_zero(self):
        weird = '{"scores":{"design_taste":{"score":"eighty","reasoning":""},"storytelling":{"score":50,"reasoning":""},"builder_mindset":{"score":50,"reasoning":""}},"decision_reason":""}'
        with patch.object(score_mod, "call_opus", return_value=weird):
            result = score_candidate(profile={}, rubric=CUSTOM_RUBRIC)
        assert result["scores"]["design_taste"]["score"] == 0

    def test_decision_reason_length_capped(self):
        long_reason = "x" * 1000
        payload = (
            '{"scores":{"design_taste":{"score":50,"reasoning":""},'
            '"storytelling":{"score":50,"reasoning":""},'
            '"builder_mindset":{"score":50,"reasoning":""}},'
            f'"decision_reason":"{long_reason}"' + "}"
        )
        with patch.object(score_mod, "call_opus", return_value=payload):
            result = score_candidate(profile={}, rubric=CUSTOM_RUBRIC)
        assert len(result["decision_reason"]) <= 500


class TestComputeWeighted:
    def test_custom_rubric_math(self):
        scores = {
            "design_taste": {"score": 100, "reasoning": ""},   # 100*40 = 4000
            "storytelling": {"score": 50, "reasoning": ""},    #  50*35 = 1750
            "builder_mindset": {"score": 20, "reasoning": ""}, #  20*25 =  500
        }
        # total = 6250, /100 = 62.5
        assert compute_weighted(scores, CUSTOM_RUBRIC) == 62.5

    def test_missing_score_counts_as_zero(self):
        scores = {"design_taste": {"score": 100, "reasoning": ""}}
        # design_taste only: 100*40 = 4000 / 100 = 40
        assert compute_weighted(scores, CUSTOM_RUBRIC) == 40.0
