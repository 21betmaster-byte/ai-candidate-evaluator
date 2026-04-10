from app.pipeline.score import compute_weighted


_RUBRIC = [
    {"key": "shipped_products", "description": "x", "weight": 30},
    {"key": "technical_depth", "description": "x", "weight": 25},
    {"key": "business_and_product_thinking", "description": "x", "weight": 15},
    {"key": "speed_and_bias_to_action", "description": "x", "weight": 15},
    {"key": "pedigree_and_relevance", "description": "x", "weight": 10},
    {"key": "communication_clarity", "description": "x", "weight": 5},
]


def test_compute_weighted_full_marks():
    scores = {d["key"]: {"score": 100, "reasoning": ""} for d in _RUBRIC}
    assert compute_weighted(scores, _RUBRIC) == 100.0


def test_compute_weighted_zero():
    scores = {d["key"]: {"score": 0, "reasoning": ""} for d in _RUBRIC}
    assert compute_weighted(scores, _RUBRIC) == 0.0


def test_compute_weighted_mixed():
    scores = {
        "shipped_products": {"score": 80, "reasoning": ""},              # 80*30 = 2400
        "technical_depth": {"score": 60, "reasoning": ""},               # 60*25 = 1500
        "business_and_product_thinking": {"score": 40, "reasoning": ""}, # 40*15 = 600
        "speed_and_bias_to_action": {"score": 50, "reasoning": ""},      # 50*15 = 750
        "pedigree_and_relevance": {"score": 70, "reasoning": ""},        # 70*10 = 700
        "communication_clarity": {"score": 90, "reasoning": ""},         # 90*5  = 450
    }
    # total = 6400, /100 = 64.0
    assert compute_weighted(scores, _RUBRIC) == 64.0
