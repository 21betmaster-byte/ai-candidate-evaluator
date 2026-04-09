from app.pipeline.decide import decide_tier

T = {"auto_fail_ceiling": 49, "manual_review_ceiling": 69, "auto_pass_floor": 70}


def test_boundary_50_is_manual_review():
    assert decide_tier(50, T) == "manual_review"


def test_boundary_49_is_auto_fail():
    assert decide_tier(49, T) == "auto_fail"


def test_boundary_70_is_auto_pass():
    assert decide_tier(70, T) == "auto_pass"


def test_high_score():
    assert decide_tier(95.5, T) == "auto_pass"


def test_low_score():
    assert decide_tier(0, T) == "auto_fail"
