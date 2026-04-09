from app.pipeline.score import compute_weighted


_RUBRIC = [
    {"key": "technical_depth", "description": "x", "weight": 35},
    {"key": "shipped_products", "description": "x", "weight": 30},
    {"key": "business_thinking", "description": "x", "weight": 20},
    {"key": "speed_of_execution", "description": "x", "weight": 15},
]


def test_compute_weighted_full_marks():
    scores = {d["key"]: {"score": 100, "reasoning": ""} for d in _RUBRIC}
    assert compute_weighted(scores, _RUBRIC) == 100.0


def test_compute_weighted_zero():
    scores = {d["key"]: {"score": 0, "reasoning": ""} for d in _RUBRIC}
    assert compute_weighted(scores, _RUBRIC) == 0.0


def test_compute_weighted_mixed():
    scores = {
        "technical_depth": {"score": 80, "reasoning": ""},   # 80*35 = 2800
        "shipped_products": {"score": 60, "reasoning": ""},  # 60*30 = 1800
        "business_thinking": {"score": 40, "reasoning": ""}, # 40*20 = 800
        "speed_of_execution": {"score": 50, "reasoning": ""},# 50*15 = 750
    }
    # total = 6150, /100 = 61.5
    assert compute_weighted(scores, _RUBRIC) == 61.5
