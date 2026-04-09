"""Tier decision logic. Boundary semantics per PRD §7."""
from __future__ import annotations


def decide_tier(overall_score: float, thresholds: dict[str, int]) -> str:
    """Returns 'auto_pass' | 'manual_review' | 'auto_fail'.

    Boundaries (PRD §7): 50 → manual_review, 70 → auto_pass.
    """
    auto_fail_ceiling = thresholds.get("auto_fail_ceiling", 49)
    auto_pass_floor = thresholds.get("auto_pass_floor", 70)
    if overall_score >= auto_pass_floor:
        return "auto_pass"
    if overall_score <= auto_fail_ceiling:
        return "auto_fail"
    return "manual_review"
