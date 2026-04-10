from app.pipeline.decide import decide_tier

T = {"auto_fail_ceiling": 48, "manual_review_ceiling": 49, "auto_pass_floor": 50}


def test_boundary_50_is_auto_pass():
    assert decide_tier(50, T) == "auto_pass"


def test_boundary_49_is_manual_review():
    assert decide_tier(49, T) == "manual_review"


def test_boundary_48_is_auto_fail():
    assert decide_tier(48, T) == "auto_fail"


def test_high_score():
    assert decide_tier(95.5, T) == "auto_pass"


def test_low_score():
    assert decide_tier(0, T) == "auto_fail"
