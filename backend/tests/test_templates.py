from app.emails import templates as tpl


def test_acknowledgment_renders():
    e = tpl.acknowledgment("Alice", "Plum")
    assert "Alice" in e.body
    assert "Plum" in e.body
    assert e.subject


def test_acknowledgment_does_not_claim_received_items():
    e = tpl.acknowledgment("Alice", "Plum")
    assert "your resume" not in e.body
    assert "your GitHub" not in e.body
    assert "your portfolio" not in e.body


def test_fail_decision_no_scores_in_body():
    e = tpl.fail_decision("Bob", "We're looking for a bit more depth.", "Plum")
    assert "score" not in e.body.lower()
    assert "rubric" not in e.body.lower()
    assert "Bob" in e.body


def test_missing_items_lists_items():
    e = tpl.missing_items("Carol", ["a resume PDF", "a GitHub link"], "Plum")
    assert "resume PDF" in e.body
    assert "GitHub link" in e.body


def test_pass_decision_includes_next_steps():
    e = tpl.pass_decision("Dan", "Reply with availability for a 30 min call.", "Plum")
    assert "30 min call" in e.body
