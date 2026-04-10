"""Tier decision logic. Boundary semantics per PRD §7."""
from __future__ import annotations


def decide_tier(overall_score: float, thresholds: dict[str, int]) -> str:
    """Returns 'auto_pass' | 'manual_review' | 'auto_fail'.

    Default: 50+ → auto_pass, 49 → manual_review, <49 → auto_fail.
    """
    auto_fail_ceiling = thresholds.get("auto_fail_ceiling", 48)
    auto_pass_floor = thresholds.get("auto_pass_floor", 50)
    if overall_score >= auto_pass_floor:
        return "auto_pass"
    if overall_score <= auto_fail_ceiling:
        return "auto_fail"
    return "manual_review"
