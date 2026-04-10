"""Integration tests for /api/settings.

Covers the full HTTP round-trip that the dashboard settings page depends on:

  - GET returns the current rubric + thresholds + polling etc.
  - PUT with a valid payload persists and the next GET reflects it
  - PUT rejects every invariant violation with a 4xx (not a 500)
  - Custom dimension keys authored by hiring managers survive the round trip
  - Editing the rubric does NOT stomp on unrelated fields (polling, company, etc.)

These are the guardrails that stop the demo from exploding when a hiring
manager saves a rubric in the UI.
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient


def _base_payload() -> dict:
    return {
        "polling_minutes": 5,
        "rubric": [
            {
                "key": "technical_depth",
                "description": "engineering chops, not just credentials",
                "weight": 40,
            },
            {
                "key": "shipped_products",
                "description": "launched real things for real users",
                "weight": 60,
            },
        ],
        "tier_thresholds": {
            "auto_fail_ceiling": 48,
            "manual_review_ceiling": 49,
            "auto_pass_floor": 50,
        },
        "pass_next_steps_text": "Reply with times that work.",
        "reminder_hours": 48,
        "incomplete_expiry_days": 7,
        "company_name": "Curator Test",
    }


class TestSettingsGet:
    def test_returns_200_with_seeded_defaults(self, client: TestClient, settings_row):
        r = client.get("/api/settings")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body["rubric"], list)
        assert len(body["rubric"]) == 6  # matches DEFAULT_RUBRIC
        # Every dimension has the expected keys.
        for dim in body["rubric"]:
            assert set(dim.keys()) == {"key", "description", "weight"}
            assert dim["description"]  # non-blank
        assert sum(d["weight"] for d in body["rubric"]) == 100


class TestSettingsPutHappyPath:
    def test_round_trip_persists(self, client: TestClient, settings_row):
        payload = _base_payload()
        r = client.put("/api/settings", json=payload)
        assert r.status_code == 200, r.text

        # Fresh GET should reflect the PUT in full.
        r2 = client.get("/api/settings")
        got = r2.json()
        assert got["polling_minutes"] == 5
        assert got["company_name"] == "Curator Test"
        assert [d["key"] for d in got["rubric"]] == ["technical_depth", "shipped_products"]
        assert got["rubric"][0]["description"] == "engineering chops, not just credentials"
        assert got["rubric"][0]["weight"] == 40

    def test_custom_dimensions_survive(self, client: TestClient, settings_row):
        # Hiring manager invents a new dimension — this is the whole point.
        payload = _base_payload()
        payload["rubric"] = [
            {"key": "design_taste", "description": "eye for visual craft", "weight": 30},
            {"key": "storytelling", "description": "explains work clearly", "weight": 20},
            {"key": "builder_mindset", "description": "bias to shipping", "weight": 50},
        ]
        r = client.put("/api/settings", json=payload)
        assert r.status_code == 200, r.text

        got = client.get("/api/settings").json()
        assert [d["key"] for d in got["rubric"]] == ["design_taste", "storytelling", "builder_mindset"]
        assert got["rubric"][0]["description"] == "eye for visual craft"

    def test_single_dimension_at_100_allowed(self, client: TestClient, settings_row):
        payload = _base_payload()
        payload["rubric"] = [
            {"key": "overall_fit", "description": "everything matters", "weight": 100}
        ]
        r = client.put("/api/settings", json=payload)
        assert r.status_code == 200

    def test_editing_thresholds_does_not_stomp_rubric(
        self, client: TestClient, settings_row
    ):
        first = _base_payload()
        client.put("/api/settings", json=first).raise_for_status()

        second = copy.deepcopy(first)
        second["tier_thresholds"]["auto_pass_floor"] = 80
        second["tier_thresholds"]["manual_review_ceiling"] = 75
        r = client.put("/api/settings", json=second)
        assert r.status_code == 200

        got = client.get("/api/settings").json()
        assert got["tier_thresholds"]["auto_pass_floor"] == 80
        # Rubric still intact.
        assert [d["key"] for d in got["rubric"]] == ["technical_depth", "shipped_products"]


class TestSettingsPutValidation:
    """Every failure mode must return 4xx with a clear error, never a 500."""

    def _put(self, client: TestClient, **overrides):
        payload = _base_payload()
        payload.update(overrides)
        return client.put("/api/settings", json=payload)

    def test_weights_not_100_rejected(self, client: TestClient, settings_row):
        r = self._put(
            client,
            rubric=[
                {"key": "a", "description": "x", "weight": 30},
                {"key": "b", "description": "x", "weight": 30},
            ],
        )
        assert r.status_code == 422
        assert "sum to 100" in r.text

    def test_duplicate_keys_rejected(self, client: TestClient, settings_row):
        r = self._put(
            client,
            rubric=[
                {"key": "a", "description": "x", "weight": 50},
                {"key": "a", "description": "y", "weight": 50},
            ],
        )
        assert r.status_code == 422
        assert "unique" in r.text

    def test_empty_rubric_rejected(self, client: TestClient, settings_row):
        r = self._put(client, rubric=[])
        assert r.status_code == 422

    def test_blank_description_rejected(self, client: TestClient, settings_row):
        r = self._put(
            client,
            rubric=[
                {"key": "a", "description": "   ", "weight": 50},
                {"key": "b", "description": "x", "weight": 50},
            ],
        )
        assert r.status_code == 422

    @pytest.mark.parametrize("bad_key", ["Capitalized", "has-dash", "with space", "日本"])
    def test_invalid_key_rejected(self, client: TestClient, settings_row, bad_key):
        r = self._put(
            client,
            rubric=[
                {"key": bad_key, "description": "x", "weight": 50},
                {"key": "b", "description": "x", "weight": 50},
            ],
        )
        assert r.status_code == 422

    def test_unordered_thresholds_rejected(self, client: TestClient, settings_row):
        r = self._put(
            client,
            tier_thresholds={
                "auto_fail_ceiling": 70,
                "manual_review_ceiling": 60,  # <-- inverted
                "auto_pass_floor": 80,
            },
        )
        assert r.status_code == 400
        assert "ordered" in r.text

    def test_equal_thresholds_rejected(self, client: TestClient, settings_row):
        r = self._put(
            client,
            tier_thresholds={
                "auto_fail_ceiling": 70,
                "manual_review_ceiling": 70,  # equal is not strictly less
                "auto_pass_floor": 80,
            },
        )
        assert r.status_code == 400

    def test_missing_required_field_rejected(self, client: TestClient, settings_row):
        payload = _base_payload()
        del payload["rubric"]
        r = client.put("/api/settings", json=payload)
        assert r.status_code == 422
