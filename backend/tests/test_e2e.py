"""End-to-end pipeline tests.

These tests drive the full Gmail→classify→fetch→structure→score→decide→reply
chain against an in-memory sqlite DB with all external I/O (Gmail, GitHub,
portfolio, LLM, PDF parsing) replaced by deterministic fakes in conftest.

They cover the PRD §9 P0 scenarios and, critically, verify the **end-to-end
logging requirement** from the Plum Builders' Residency brief ("Ask the
candidate to walk through the logs and explain what happened") and PRD §3
Logging acceptance criteria:

    - Every processing step is logged with timestamp + duration
    - Edge case triggers are logged
    - Infrastructure failures logged with error type + retry count
    - Each candidate's processing timeline viewable on detail page
"""
from __future__ import annotations

import app.jobs.handlers as handlers_mod
from app.models import Candidate, EmailLog, Evaluation, Job, ProcessingLog
from tests.conftest import _FakeGitHubData, _FakePortfolioData, _fake_score, fake_parse_resume_factory


# ---------------------- helpers ----------------------

def _logs(db, candidate_id):
    return (
        db.query(ProcessingLog)
        .filter(ProcessingLog.candidate_id == candidate_id)
        .order_by(ProcessingLog.id)
        .all()
    )


def _all_steps_for_message(db, candidate_id):
    """Return step names across both (a) pre-candidate logs [classify,
    email_received] and (b) candidate-scoped logs. Dedup, preserve order."""
    pre = (
        db.query(ProcessingLog)
        .filter(ProcessingLog.candidate_id.is_(None))
        .order_by(ProcessingLog.id)
        .all()
    )
    post = _logs(db, candidate_id)
    seen = []
    for l in list(pre) + list(post):
        if l.step not in seen:
            seen.append(l.step)
    return seen


def _steps(db, candidate_id):
    return [l.step for l in _logs(db, candidate_id)]


def _outbound_templates(db):
    return [e.template_used for e in db.query(EmailLog).filter(EmailLog.direction == "out").all()]


# ==================== P0: Happy Path ====================


def test_e2e_happy_path_complete_application(
    db, settings_row, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """PRD §9: Complete application flow. Verifies dashboard state, email
    outputs, and that every PRD-required processing step is logged."""
    email = make_inbound(
        "msg-happy-1",
        "jane@example.com",
        "Jane Doe",
        "Application for Builder in Residence",
        "Hi! Attaching my resume. GitHub: https://github.com/janedoe  Portfolio: https://janedoe.com",
        attachments=[pdf_attachment()],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-happy-1")

    run_pipeline()

    cand = db.query(Candidate).filter(Candidate.email == "jane@example.com").one()
    assert cand.status == "auto_pass"
    assert cand.name == "Jane Doe"

    ev = db.get(Evaluation, cand.current_evaluation_id)
    assert ev.overall_score == 75.5
    assert ev.tier == "auto_pass"
    assert ev.scores and set(ev.scores.keys()) == {
        "shipped_products", "technical_depth", "business_and_product_thinking",
        "speed_and_bias_to_action", "pedigree_and_relevance", "communication_clarity"
    }

    # Outbound emails: acknowledgment + pass_decision
    templates = _outbound_templates(db)
    assert "acknowledgment" in templates
    assert "pass_decision" in templates

    # Full log sequence per PRD §3 "Logging"
    steps = _all_steps_for_message(db, cand.id)
    for required in (
        "email_received",
        "classify",
        "ingest",
        "parse_resume",
        "fetch_github",
        "fetch_portfolio",
        "structure_profile",
        "score",
        "decide",
        "send_email",
    ):
        assert required in steps, f"missing step '{required}' in log timeline: {steps}"

    # Every wrapped step emits started+completed with duration_ms
    score_logs = [l for l in _logs(db, cand.id) if l.step == "score"]
    assert any(l.message == "started" for l in score_logs)
    completed = [l for l in score_logs if l.message == "completed"]
    assert completed and completed[0].meta.get("duration_ms") is not None
    assert completed[0].meta.get("overall_score") == 75.5


# ==================== P0: Dashboard visibility ====================


def test_dashboard_candidate_detail_exposes_full_timeline(
    db, settings_row, client, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """Plum brief: 'Ask the candidate to walk through the logs and explain
    what happened'. Verify GET /api/candidates/{id} returns the full processing
    timeline + scores."""
    email = make_inbound(
        "msg-dash",
        "alex@example.com",
        "Alex",
        "Application",
        "Applying. https://github.com/alex  https://alex.dev",
        attachments=[pdf_attachment()],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-dash")
    run_pipeline()

    cand = db.query(Candidate).filter(Candidate.email == "alex@example.com").one()
    resp = client.get(f"/api/candidates/{cand.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "alex@example.com"
    assert body["current_evaluation"]["overall_score"] == 75.5
    assert body["current_evaluation"]["tier"] == "auto_pass"
    log_steps = [l["step"] for l in body["logs"]]
    for required in ("ingest", "classify", "fetch_github", "score", "decide", "send_email"):
        assert required in log_steps

    # list endpoint
    resp = client.get("/api/candidates")
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["email"] == "alex@example.com" for r in rows)


# ==================== P0: Incomplete → missing_items ====================


def test_e2e_missing_github_and_portfolio(
    db, settings_row, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    email = make_inbound(
        "msg-miss",
        "sam@example.com",
        "Sam",
        "Application",
        "Applying with just my resume.",
        attachments=[pdf_attachment()],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-miss")
    run_pipeline()

    cand = db.query(Candidate).filter(Candidate.email == "sam@example.com").one()
    assert cand.status == "incomplete"
    assert cand.missing_items and any("GitHub" in m for m in cand.missing_items)

    templates = _outbound_templates(db)
    assert "missing_items" in templates
    # A reminder job should be scheduled but not yet executed (delay 48h)
    reminder_jobs = db.query(Job).filter(Job.type == "send_reminder").all()
    assert reminder_jobs, "reminder job should be scheduled"


# ==================== P0: DOCX resume accepted ====================


def test_e2e_docx_resume_accepted(
    db, settings_row, gmail_fake, make_inbound, docx_attachment, enqueue_ingest, run_pipeline
):
    email = make_inbound(
        "msg-docx",
        "chris@example.com",
        "Chris",
        "Application",
        "Attached my resume",
        attachments=[docx_attachment()],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-docx")
    run_pipeline()

    cand = db.query(Candidate).filter(Candidate.email == "chris@example.com").one()
    # DOCX is a supported resume format — should not trigger the rejection template.
    assert "non_pdf_attachment" not in _outbound_templates(db)
    parse_logs = [l for l in _logs(db, cand.id) if l.step == "parse_resume"]
    assert any(l.meta and l.meta.get("resume_present") for l in parse_logs)


def test_e2e_unsupported_attachment_rejected(
    db, settings_row, gmail_fake, make_inbound, enqueue_ingest, run_pipeline
):
    from app.gmail.client import Attachment

    bogus = Attachment(filename="resume.txt", mime_type="text/plain", data=b"hello")
    email = make_inbound(
        "msg-txt",
        "dana@example.com",
        "Dana",
        "Application",
        "Attached my resume",
        attachments=[bogus],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-txt")
    run_pipeline()

    cand = db.query(Candidate).filter(Candidate.email == "dana@example.com").one()
    assert cand.status == "incomplete"
    assert "non_pdf_attachment" in _outbound_templates(db)
    assert cand.missing_items and any("PDF or DOCX" in m for m in cand.missing_items)


# ==================== P0: Gibberish ====================


def test_e2e_gibberish_no_candidate_created(
    db, settings_row, gmail_fake, make_inbound, enqueue_ingest, run_pipeline
):
    email = make_inbound(
        "msg-gib",
        "weird@example.com",
        None,
        "hello",
        "asdfasdf qwerty lorem ipsum random",
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-gib")
    run_pipeline()

    assert db.query(Candidate).filter(Candidate.email == "weird@example.com").first() is None
    assert "gibberish" in _outbound_templates(db)
    inbound_log = db.query(EmailLog).filter(EmailLog.direction == "in").one()
    assert inbound_log.classification == "gibberish"


# ==================== P0: Duplicate application ====================


def test_e2e_duplicate_application_supersedes_old_evaluation(
    db, settings_row, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    def _send(mid: str):
        email = make_inbound(
            mid, "dup@example.com", "Dup",
            "Application",
            "https://github.com/dup  https://dup.dev",
            attachments=[pdf_attachment()],
        )
        gmail_fake.deliver(email)
        enqueue_ingest(mid)
        run_pipeline()

    _send("msg-dup-1")
    _send("msg-dup-2")

    cand = db.query(Candidate).filter(Candidate.email == "dup@example.com").one()
    evs = db.query(Evaluation).filter(Evaluation.candidate_id == cand.id).order_by(Evaluation.id).all()
    assert len(evs) == 2
    assert evs[0].superseded is True
    assert evs[1].superseded is False
    assert cand.current_evaluation_id == evs[1].id
    assert "duplicate_update" not in _outbound_templates(db)


# ==================== P0: GitHub 404 (candidate-side error) ====================


def test_e2e_github_candidate_error(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    from app.pipeline.github import GitHubCandidateError

    def _boom(url):
        raise GitHubCandidateError("profile 404")

    monkeypatch.setattr(handlers_mod, "fetch_github", _boom)

    email = make_inbound(
        "msg-gh404", "gh@example.com", "GH",
        "Application",
        "https://github.com/missing  https://gh.dev",
        attachments=[pdf_attachment()],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-gh404")
    run_pipeline()

    cand = db.query(Candidate).filter(Candidate.email == "gh@example.com").one()
    assert cand.status == "incomplete"
    assert "github_unreachable" in _outbound_templates(db)
    fail_logs = [l for l in _logs(db, cand.id) if l.step == "fetch_github" and l.level == "warn"]
    assert fail_logs, "should have a warn-level fetch_github log"


# ==================== P1: GitHub infra retry → success ====================


def test_e2e_github_infra_retry_then_success(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """PRD §9 P1: GitHub API returns 5xx for first 2 attempts, then succeeds.
    Verifies retry logs + ultimate success without penalizing the candidate."""
    from app.pipeline.github import GitHubInfraError

    state = {"calls": 0}

    def _flaky(url):
        state["calls"] += 1
        if state["calls"] < 3:
            raise GitHubInfraError("502")
        return _FakeGitHubData()

    monkeypatch.setattr(handlers_mod, "fetch_github", _flaky)

    email = make_inbound(
        "msg-retry", "retry@example.com", "Retry",
        "Application",
        "https://github.com/retry  https://retry.dev",
        attachments=[pdf_attachment()],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-retry")
    run_pipeline()

    assert state["calls"] == 3
    cand = db.query(Candidate).filter(Candidate.email == "retry@example.com").one()
    assert cand.status == "auto_pass"

    # Retry log entries exist on the timeline
    retry_logs = [l for l in _logs(db, cand.id) if l.step == "fetch_github" and l.level == "warn"]
    assert len(retry_logs) >= 2, f"expected ≥2 retry warnings, got {[l.message for l in retry_logs]}"
    assert any("retry scheduled" in l.message for l in retry_logs)


# ==================== P1: Infra retries exhausted → processing_error ====================


def test_e2e_infra_retries_exhausted_escalates(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    from app.pipeline.github import GitHubInfraError

    def _always_fail(url):
        raise GitHubInfraError("502 forever")

    monkeypatch.setattr(handlers_mod, "fetch_github", _always_fail)

    email = make_inbound(
        "msg-dead", "dead@example.com", "Dead",
        "Application",
        "https://github.com/dead  https://dead.dev",
        attachments=[pdf_attachment()],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-dead")
    run_pipeline(max_iterations=200)

    cand = db.query(Candidate).filter(Candidate.email == "dead@example.com").one()
    assert cand.status == "processing_error"
    error_logs = [l for l in _logs(db, cand.id) if l.level == "error"]
    assert error_logs, "should log an error-level entry on exhaustion"


# ==================== P1: Secondary discovery — GitHub in portfolio ====================


def test_e2e_secondary_discovery_github_in_portfolio(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """Email has resume + portfolio but NO GitHub. Portfolio page exposes a
    GitHub link, which the agent discovers and uses without flagging missing."""
    def _portfolio_with_gh(url):
        return _FakePortfolioData(discovered_github="https://github.com/found")

    monkeypatch.setattr(handlers_mod, "fetch_portfolio", _portfolio_with_gh)

    email = make_inbound(
        "msg-sec", "sec@example.com", "Sec",
        "Application",
        "Applying! Portfolio: https://sec.dev",
        attachments=[pdf_attachment()],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-sec")
    run_pipeline()

    cand = db.query(Candidate).filter(Candidate.email == "sec@example.com").one()
    assert cand.status == "auto_pass"
    assert "missing_items" not in _outbound_templates(db)
    steps = _steps(db, cand.id)
    assert "discover_secondary" in steps


# ==================== P0: Concurrent applications, no cross-contamination ====================


def test_e2e_concurrent_applications_no_cross_contamination(
    db, settings_row, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    emails = [
        ("a@ex.com", "A", "msg-a"),
        ("b@ex.com", "B", "msg-b"),
        ("c@ex.com", "C", "msg-c"),
    ]
    for addr, name, mid in emails:
        gmail_fake.deliver(make_inbound(
            mid, addr, name, "Application",
            f"https://github.com/{name.lower()}  https://{name.lower()}.dev",
            attachments=[pdf_attachment()],
        ))
        enqueue_ingest(mid)

    run_pipeline(max_iterations=200)

    for addr, _, _ in emails:
        cand = db.query(Candidate).filter(Candidate.email == addr).one()
        assert cand.status == "auto_pass"
        logs = _logs(db, cand.id)
        # Every log row for this candidate must belong to this candidate — no
        # cross-contamination of candidate_id.
        assert all(l.candidate_id == cand.id for l in logs)
        assert any(l.step == "score" and l.message == "completed" for l in logs)


# ==================== P0: Manual review → dashboard pass action ====================


def test_dashboard_manual_review_pass_action(
    db, settings_row, monkeypatch, client, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """Force a manual_review tier and drive the dashboard POST /decision endpoint."""
    def _mid_score(profile, rubric, **kwargs):
        return {
            "scores": {k: {"score": 49, "reasoning": ""} for k in ("shipped_products","technical_depth","business_and_product_thinking","speed_and_bias_to_action","pedigree_and_relevance","communication_clarity")},
            "overall_score": 49.0,
            "decision_reason": "borderline",
        }

    monkeypatch.setattr(handlers_mod, "score_candidate", _mid_score)

    email = make_inbound(
        "msg-mr", "mr@example.com", "MR",
        "Application",
        "https://github.com/mr  https://mr.dev",
        attachments=[pdf_attachment()],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("msg-mr")
    run_pipeline()

    cand = db.query(Candidate).filter(Candidate.email == "mr@example.com").one()
    assert cand.status == "manual_review"

    resp = client.post(f"/api/candidates/{cand.id}/decision", json={"decision": "pass"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "passed_manual"

    run_pipeline()
    assert "pass_decision" in _outbound_templates(db)


# ==================== P0: Poll Now endpoint ====================


def test_poll_now_enqueues_pending_messages(
    db, settings_row, monkeypatch, client, gmail_fake, make_inbound, pdf_attachment, run_pipeline
):
    """POST /api/poll should discover new messages via the Gmail client."""
    # app.gmail.poller.poll_inbox uses list_unprocessed_messages + enqueues
    # an ingest_email job per message. We pre-deliver a message and hit /api/poll.
    gmail_fake.deliver(make_inbound(
        "msg-poll", "poll@example.com", "Poll", "Application",
        "https://github.com/poll  https://poll.dev",
        attachments=[pdf_attachment()],
    ))

    resp = client.post("/api/poll")
    assert resp.status_code == 200
    # Drive whatever jobs the poll enqueued
    run_pipeline()
    assert db.query(Candidate).filter(Candidate.email == "poll@example.com").first() is not None


# ==================== Duplicate emails: merge prior data ====================
#
# Brief edge case: "duplicate applications". Behavior the team agreed on:
# the LATEST email always wins for any field it provides, but missing fields
# are filled in from the candidate's prior evaluation. So a candidate who
# first sent only a resume and then replies with a GitHub link should end up
# with a complete application — not get nagged for the resume again.
#
# Each test starts the candidate in a known partial state and then sends a
# follow-up that should merge with it.


def _setup_candidate_with(
    *,
    monkeypatch, db, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline,
    message_id, sender_email, sender_name, body, attachments,
):
    """First-email helper: drives a candidate through ingest with the given inputs."""
    gmail_fake.deliver(make_inbound(message_id, sender_email, sender_name, "Application", body, attachments=attachments))
    enqueue_ingest(message_id)
    run_pipeline()


def test_duplicate_resume_then_links_merges_into_complete_application(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """Resume only first → links-only follow-up should produce a complete pipeline run."""
    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="dup-1a", sender_email="dup1@example.com", sender_name="Dup One",
        body="Applying — see resume",
        attachments=[pdf_attachment()],
    )
    cand = db.query(Candidate).filter(Candidate.email == "dup1@example.com").one()
    assert cand.status == "incomplete"
    prior_ev_id = cand.current_evaluation_id
    prior_resume = db.get(Evaluation, prior_ev_id).raw_resume_text
    assert prior_resume

    # Second email: only the missing links, no attachment.
    import app.jobs.handlers as h
    monkeypatch.setattr(h, "parse_resume", fake_parse_resume_factory(text=""))
    gmail_fake.deliver(make_inbound(
        "dup-1b", "dup1@example.com", "Dup One", "Re: Application",
        "Following up on my application — forgot the links: https://github.com/dup1  https://dup1.dev",
        attachments=[],
    ))
    enqueue_ingest("dup-1b")
    run_pipeline()

    db.expire_all()
    cand = db.query(Candidate).filter(Candidate.email == "dup1@example.com").one()
    new_ev = db.get(Evaluation, cand.current_evaluation_id)
    assert new_ev.id != prior_ev_id, "a new evaluation row should be created"
    # Resume merged from prior
    assert new_ev.raw_resume_text == prior_resume
    # New links populated from this email
    assert new_ev.github_url and "dup1" in new_ev.github_url
    assert new_ev.portfolio_url and "dup1.dev" in new_ev.portfolio_url
    # Pipeline ran to completion against the merged data
    assert cand.status in ("auto_pass", "auto_fail", "manual_review")
    assert new_ev.tier is not None
    # No duplicate-update or acknowledgment for re-applications
    assert "duplicate_update" not in _outbound_templates(db)


def test_duplicate_full_resend_overwrites_all_fields(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """Complete app, then a second complete app — new values fully replace old ones."""
    import app.jobs.handlers as h

    monkeypatch.setattr(h, "parse_resume", fake_parse_resume_factory(text="OLD resume text v1"))
    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="dup-2a", sender_email="dup2@example.com", sender_name="Dup Two",
        body="https://github.com/old  https://old.dev",
        attachments=[pdf_attachment("old.pdf")],
    )
    cand = db.query(Candidate).filter(Candidate.email == "dup2@example.com").one()
    old_ev = db.get(Evaluation, cand.current_evaluation_id)
    assert old_ev.github_url and "old" in old_ev.github_url
    assert old_ev.raw_resume_text == "OLD resume text v1"

    # Resend everything updated.
    monkeypatch.setattr(h, "parse_resume", fake_parse_resume_factory(text="NEW resume text v2"))
    gmail_fake.deliver(make_inbound(
        "dup-2b", "dup2@example.com", "Dup Two", "Updated application",
        "Refreshed links: https://github.com/new  https://new.dev",
        attachments=[pdf_attachment("new.pdf")],
    ))
    enqueue_ingest("dup-2b")
    run_pipeline()

    db.expire_all()
    cand = db.query(Candidate).filter(Candidate.email == "dup2@example.com").one()
    new_ev = db.get(Evaluation, cand.current_evaluation_id)
    assert new_ev.id != old_ev.id
    # New values fully replace old ones
    assert new_ev.raw_resume_text == "NEW resume text v2"
    assert new_ev.resume_filename == "new.pdf"
    assert "new" in new_ev.github_url and "old" not in new_ev.github_url
    assert "new.dev" in new_ev.portfolio_url
    # The prior evaluation must be marked superseded so it's not shown as current
    db.refresh(old_ev)
    assert old_ev.superseded is True
    assert "duplicate_update" not in _outbound_templates(db)


def test_duplicate_partial_resend_only_overrides_provided_field(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """Resume + github + portfolio first, then a follow-up with ONLY a new
    portfolio link → portfolio updates, resume + github carried over."""
    import app.jobs.handlers as h

    monkeypatch.setattr(h, "parse_resume", fake_parse_resume_factory(text="resume v1"))
    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="dup-3a", sender_email="dup3@example.com", sender_name="Dup Three",
        body="https://github.com/dup3  https://oldsite.dev",
        attachments=[pdf_attachment()],
    )
    cand = db.query(Candidate).filter(Candidate.email == "dup3@example.com").one()
    old_ev = db.get(Evaluation, cand.current_evaluation_id)
    assert old_ev.portfolio_url and "oldsite" in old_ev.portfolio_url

    # Follow-up: just a new portfolio. No resume attachment, no github link.
    monkeypatch.setattr(h, "parse_resume", fake_parse_resume_factory(text=""))
    gmail_fake.deliver(make_inbound(
        "dup-3b", "dup3@example.com", "Dup Three", "Updated portfolio",
        "Updating my application — new portfolio link: https://newsite.dev",
        attachments=[],
    ))
    enqueue_ingest("dup-3b")
    run_pipeline()

    db.expire_all()
    cand = db.query(Candidate).filter(Candidate.email == "dup3@example.com").one()
    new_ev = db.get(Evaluation, cand.current_evaluation_id)
    # Portfolio overridden by latest email
    assert "newsite" in new_ev.portfolio_url
    # Resume + github carried over from prior
    assert new_ev.raw_resume_text == "resume v1"
    assert new_ev.github_url and "dup3" in new_ev.github_url


def test_duplicate_merge_logged_with_merged_fields(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """Merge events should be visible in the processing log so a hiring
    manager can see exactly what was carried over."""
    import app.jobs.handlers as h

    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="dup-4a", sender_email="dup4@example.com", sender_name="Dup Four",
        body="Resume only please",
        attachments=[pdf_attachment()],
    )

    monkeypatch.setattr(h, "parse_resume", fake_parse_resume_factory(text=""))
    gmail_fake.deliver(make_inbound(
        "dup-4b", "dup4@example.com", "Dup Four", "Re: Application",
        "Following up on my application — links: https://github.com/dup4  https://dup4.dev",
        attachments=[],
    ))
    enqueue_ingest("dup-4b")
    run_pipeline()

    cand = db.query(Candidate).filter(Candidate.email == "dup4@example.com").one()
    merge_logs = [
        l for l in _logs(db, cand.id)
        if l.step == "ingest" and "merged" in (l.message or "")
    ]
    assert merge_logs, "expected an ingest log entry recording the merge"
    assert "resume" in merge_logs[-1].meta.get("merged", [])


# ==================== Regression: quoted-text URL extraction ====================
#
# Bugs 2 & 3: replies include the entire conversation history in body_text.
# The system was extracting URLs from quoted text (old portfolio links) instead
# of the new ones the candidate intended. These tests ensure strip_quoted_text
# is applied so only URLs from the *new* portion of the reply are used.


def test_reply_with_quoted_old_url_uses_new_url_only(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """Candidate applies with resume only (incomplete), then replies with a new
    portfolio link. The quoted text contains an old URL from the system email.
    The pipeline must use the NEW URL from the fresh reply text, not the OLD
    one from the quoted section."""
    import app.jobs.handlers as h

    # First email: resume only, no URLs → incomplete
    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="qt-1a", sender_email="quoted@example.com", sender_name="Quoted",
        body="Here is my application",
        attachments=[pdf_attachment()],
    )
    cand = db.query(Candidate).filter(Candidate.email == "quoted@example.com").one()
    assert cand.status == "incomplete"

    # Reply whose body includes the new links at the top and an old URL inside
    # a quoted "On DATE, NAME wrote:" block.
    reply_body = (
        "Here are my links: https://github.com/quoted  https://new-portfolio.dev\n"
        "\n"
        "On Tue, Apr 8, 2026 at 10:00 AM Plum <hiring@plum.com> wrote:\n"
        "> Thanks for applying. We noticed some items are missing.\n"
        "> Check out https://old-portfolio.dev for reference.\n"
    )
    monkeypatch.setattr(h, "parse_resume", fake_parse_resume_factory(text=""))
    gmail_fake.deliver(make_inbound(
        "qt-1b", "quoted@example.com", "Quoted", "Re: Application",
        reply_body,
        attachments=[],
    ))
    enqueue_ingest("qt-1b")
    run_pipeline()

    db.expire_all()
    cand = db.query(Candidate).filter(Candidate.email == "quoted@example.com").one()
    new_ev = db.get(Evaluation, cand.current_evaluation_id)
    # The new evaluation must use the NEW portfolio URL, not the old one.
    assert "new-portfolio.dev" in new_ev.portfolio_url
    assert "old-portfolio.dev" not in (new_ev.portfolio_url or "")


def test_reply_with_angle_bracket_quoting_strips_old_urls(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """Standard '>' quoting should be stripped so old URLs are not extracted."""
    import app.jobs.handlers as h

    # First email: resume only → incomplete
    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="ab-1a", sender_email="angle@example.com", sender_name="Angle",
        body="Here is my application",
        attachments=[pdf_attachment()],
    )
    cand = db.query(Candidate).filter(Candidate.email == "angle@example.com").one()
    assert cand.status == "incomplete"

    # Reply with new links + '>' quoted old URL.
    reply_body = (
        "Updated links: https://github.com/angle  https://fixed.dev\n"
        "\n"
        "> On Apr 8, 2026, Plum wrote:\n"
        "> Please provide a working portfolio link.\n"
        "> The link https://broken.dev did not load.\n"
    )
    monkeypatch.setattr(h, "parse_resume", fake_parse_resume_factory(text=""))
    gmail_fake.deliver(make_inbound(
        "ab-1b", "angle@example.com", "Angle", "Re: Application",
        reply_body,
        attachments=[],
    ))
    enqueue_ingest("ab-1b")
    run_pipeline()

    db.expire_all()
    cand = db.query(Candidate).filter(Candidate.email == "angle@example.com").one()
    new_ev = db.get(Evaluation, cand.current_evaluation_id)
    assert "fixed.dev" in new_ev.portfolio_url
    assert "broken.dev" not in (new_ev.portfolio_url or "")


# ==================== Regression: classification override for replies ====================
#
# Bug 3 continuation: a short reply like "here's my portfolio: URL" from a
# known incomplete candidate was classified as "question" or "other", causing
# the pipeline to never run with the new data. The override forces
# reclassification to "application" when an incomplete/auto_fail candidate
# sends URLs.


def test_short_reply_from_incomplete_candidate_reclassified_as_application(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """A known incomplete candidate sends a short reply with a portfolio link.
    The classifier returns 'other' but the override should reclassify it as
    'application' and run the full pipeline."""
    import app.jobs.handlers as h

    # First email: application with resume only → incomplete (no github/portfolio)
    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="ovr-1a", sender_email="override@example.com", sender_name="Override",
        body="Here is my application",
        attachments=[pdf_attachment()],
    )
    cand = db.query(Candidate).filter(Candidate.email == "override@example.com").one()
    assert cand.status == "incomplete"

    # Short reply with just a couple of URLs. The fake classifier will return
    # "other" because the body doesn't match any application keywords.
    # The override should kick in because the candidate is "incomplete" + has URLs.
    gmail_fake.deliver(make_inbound(
        "ovr-1b", "override@example.com", "Override", "Re: Missing items",
        "https://github.com/override  https://override.dev",
        attachments=[],
    ))
    enqueue_ingest("ovr-1b")
    run_pipeline()

    db.expire_all()
    cand = db.query(Candidate).filter(Candidate.email == "override@example.com").one()
    # Should have progressed past "incomplete" — the pipeline re-ran
    assert cand.status != "incomplete", (
        f"expected pipeline to re-run and change status from 'incomplete', got '{cand.status}'"
    )
    new_ev = db.get(Evaluation, cand.current_evaluation_id)
    assert new_ev.github_url and "override" in new_ev.github_url
    assert new_ev.portfolio_url and "override.dev" in new_ev.portfolio_url

    # The classify.override log should exist
    override_logs = [
        l for l in _logs(db, cand.id)
        if l.step == "classify.override"
    ]
    assert override_logs, "expected a classify.override log entry"


def test_short_reply_from_auto_fail_candidate_reclassified_as_application(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """A candidate whose prior application was auto-rejected sends a new email
    with correct details. Even if classified as 'other', the override should
    kick in and re-run the pipeline."""
    import app.jobs.handlers as h

    # First email: full application that scores low → auto_fail
    low_scorer = lambda profile, rubric, **kwargs: {
        "scores": {
            "shipped_products": {"score": 15, "reasoning": "none"},
            "technical_depth": {"score": 20, "reasoning": "weak"},
            "business_and_product_thinking": {"score": 10, "reasoning": "none"},
            "speed_and_bias_to_action": {"score": 12, "reasoning": "none"},
            "pedigree_and_relevance": {"score": 10, "reasoning": "none"},
            "communication_clarity": {"score": 10, "reasoning": "none"},
        },
        "overall_score": 15.0,
        "decision_reason": "Does not meet threshold.",
        "_llm_meta": {"llm_model": "test", "llm_input_tokens": 0, "llm_output_tokens": 0,
                      "llm_cache_read_tokens": 0, "llm_cache_creation_tokens": 0, "llm_duration_ms": 0},
        "_clamped_dimensions": [],
    }
    monkeypatch.setattr(h, "score_candidate", low_scorer)
    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="af-1a", sender_email="autofail@example.com", sender_name="AutoFail",
        body="https://github.com/autofail  https://autofail.dev",
        attachments=[pdf_attachment()],
    )
    cand = db.query(Candidate).filter(Candidate.email == "autofail@example.com").one()
    assert cand.status == "auto_fail"

    # Second email: the candidate sends new links. Body doesn't match
    # application keywords, so the classifier returns "other".
    monkeypatch.setattr(h, "score_candidate", _fake_score)  # restore good scorer
    gmail_fake.deliver(make_inbound(
        "af-1b", "autofail@example.com", "AutoFail", "Re: Application",
        "https://github.com/autofail-v2  https://autofail-v2.dev",
        attachments=[],
    ))
    enqueue_ingest("af-1b")
    run_pipeline()

    db.expire_all()
    cand = db.query(Candidate).filter(Candidate.email == "autofail@example.com").one()
    assert cand.status != "auto_fail", (
        f"expected pipeline re-run to change status from 'auto_fail', got '{cand.status}'"
    )
    new_ev = db.get(Evaluation, cand.current_evaluation_id)
    assert "autofail-v2" in (new_ev.github_url or "")
    assert "autofail-v2.dev" in (new_ev.portfolio_url or "")


def test_question_from_new_sender_not_overridden(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, enqueue_ingest, run_pipeline
):
    """A genuine question from a brand-new sender must NOT be reclassified as
    'application'. The override should only apply to known candidates."""
    # Send a question-like email from a brand-new sender.
    # The fake classifier returns "question" when body ends with "?" and contains "salary".
    gmail_fake.deliver(make_inbound(
        "q-new-1", "newperson@example.com", "New Person", "Quick question",
        "What is the salary range?",
        attachments=[],
    ))
    enqueue_ingest("q-new-1")
    run_pipeline()

    # Should be treated as a question — no candidate created, question_response sent.
    cand = db.query(Candidate).filter(Candidate.email == "newperson@example.com").first()
    assert cand is None, "a genuine question from a new sender should not create a candidate"
    templates = _outbound_templates(db)
    assert "question_response" in templates


def test_question_from_passed_candidate_not_overridden(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """A question from a candidate who already passed should NOT be reclassified.
    The override only triggers for 'incomplete' or 'auto_fail' status."""
    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="pass-q-1a", sender_email="passed@example.com", sender_name="Passed",
        body="https://github.com/passed  https://passed.dev",
        attachments=[pdf_attachment()],
    )
    cand = db.query(Candidate).filter(Candidate.email == "passed@example.com").one()
    assert cand.status == "auto_pass"

    # Now they send a question — should stay as question, not be overridden.
    # The fake classifier returns "question" when body ends with "?" and contains "salary".
    gmail_fake.deliver(make_inbound(
        "pass-q-1b", "passed@example.com", "Passed", "Quick question",
        "What is the salary range?",
        attachments=[],
    ))
    enqueue_ingest("pass-q-1b")
    run_pipeline()

    templates = _outbound_templates(db)
    assert "question_response" in templates
    # The classify.override log should NOT exist for this candidate
    override_logs = [
        l for l in _logs(db, cand.id)
        if l.step == "classify.override"
    ]
    assert not override_logs, "should not override classification for auto_pass candidates"


# ==================== Regression: email threading ====================
#
# Bug 4: outbound emails were not sent as replies to the original thread.
# These tests verify that send_email is called with the correct thread_id
# and in_reply_to from the candidate's inbound email.


def test_outbound_emails_include_thread_id_and_in_reply_to(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """All outbound emails for a candidate must include the Gmail thread_id
    and the RFC 822 Message-ID from the candidate's inbound email."""
    from app.gmail.client import InboundEmail

    rfc_msg_id = "<abc123@mail.gmail.com>"
    email = InboundEmail(
        message_id="thr-1",
        thread_id="thread-abc",
        sender="Thread <thread@example.com>",
        sender_email="thread@example.com",
        sender_name="Thread",
        subject="Application",
        body_text="https://github.com/thread  https://thread.dev",
        rfc822_message_id=rfc_msg_id,
        attachments=[pdf_attachment()],
        label_ids=[],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("thr-1")
    run_pipeline()

    # Every outbound email should carry thread_id, in_reply_to, and subject
    assert len(gmail_fake.sent) > 0, "expected at least one outbound email"
    for sent_msg in gmail_fake.sent:
        assert sent_msg["thread_id"] == "thread-abc", (
            f"outbound email missing thread_id: {sent_msg}"
        )
        assert sent_msg["in_reply_to"] == rfc_msg_id, (
            f"outbound email missing in_reply_to: {sent_msg}"
        )
        assert sent_msg["subject"] == "Application", (
            f"outbound email missing or wrong subject: {sent_msg}"
        )


def test_thread_id_persisted_on_candidate(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """The gmail_thread_id and rfc822_message_id must be stored on the
    candidate record for use by all subsequent outbound emails."""
    from app.gmail.client import InboundEmail

    email = InboundEmail(
        message_id="persist-1",
        thread_id="thread-persist",
        sender="Persist <persist@example.com>",
        sender_email="persist@example.com",
        sender_name="Persist",
        subject="Application",
        body_text="https://github.com/persist  https://persist.dev",
        rfc822_message_id="<persist@mail.gmail.com>",
        attachments=[pdf_attachment()],
        label_ids=[],
    )
    gmail_fake.deliver(email)
    enqueue_ingest("persist-1")
    run_pipeline()

    cand = db.query(Candidate).filter(Candidate.email == "persist@example.com").one()
    assert cand.gmail_thread_id == "thread-persist"
    assert cand.rfc822_message_id == "<persist@mail.gmail.com>"
    assert cand.last_inbound_subject == "Application"


# ==================== Regression: duplicate acknowledgement emails ====================
#
# Bug 5: re-applications were getting both "acknowledgment" and
# "duplicate_update" emails. Now neither should be sent for re-applications.


def test_first_application_gets_exactly_one_acknowledgment(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """A first-time application must receive exactly one acknowledgment email."""
    gmail_fake.deliver(make_inbound(
        "ack-1", "firsttime@example.com", "First", "Application",
        "https://github.com/first  https://first.dev",
        attachments=[pdf_attachment()],
    ))
    enqueue_ingest("ack-1")
    run_pipeline()

    ack_count = sum(1 for t in _outbound_templates(db) if t == "acknowledgment")
    assert ack_count == 1, f"expected exactly 1 acknowledgment, got {ack_count}"


def test_reapplication_gets_no_acknowledgment_or_duplicate_update(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """A re-application must NOT produce any acknowledgment or duplicate_update
    email. The pipeline processes silently and sends only the decision/missing
    items email as appropriate."""
    # First application
    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="noack-1a", sender_email="noack@example.com", sender_name="NoAck",
        body="https://github.com/noack  https://noack.dev",
        attachments=[pdf_attachment()],
    )
    # Count templates after first application
    first_templates = list(_outbound_templates(db))
    ack_count_before = sum(1 for t in first_templates if t == "acknowledgment")
    dup_count_before = sum(1 for t in first_templates if t == "duplicate_update")
    assert ack_count_before == 1  # first app gets one ack

    # Second application
    gmail_fake.deliver(make_inbound(
        "noack-1b", "noack@example.com", "NoAck", "Updated application",
        "Updated links: https://github.com/noack2  https://noack2.dev",
        attachments=[pdf_attachment()],
    ))
    enqueue_ingest("noack-1b")
    run_pipeline()

    all_templates = _outbound_templates(db)
    ack_count_after = sum(1 for t in all_templates if t == "acknowledgment")
    dup_count_after = sum(1 for t in all_templates if t == "duplicate_update")

    # Should still be exactly 1 acknowledgment (from the first email) and 0 duplicate_update
    assert ack_count_after == 1, (
        f"expected no additional acknowledgment for re-application, got {ack_count_after} total"
    )
    assert dup_count_after == 0, (
        f"expected 0 duplicate_update emails, got {dup_count_after}"
    )


def test_reply_to_missing_items_gets_no_acknowledgment(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline
):
    """When a candidate replies to a missing_items email with the required
    links, they should NOT receive any acknowledgment — only the pipeline
    result email (decision or further missing items)."""
    import app.jobs.handlers as h

    # First email: resume only → incomplete
    _setup_candidate_with(
        monkeypatch=monkeypatch, db=db, gmail_fake=gmail_fake, make_inbound=make_inbound,
        pdf_attachment=pdf_attachment, enqueue_ingest=enqueue_ingest, run_pipeline=run_pipeline,
        message_id="mi-reply-1a", sender_email="mireply@example.com", sender_name="MiReply",
        body="Here is my application",
        attachments=[pdf_attachment()],
    )
    cand = db.query(Candidate).filter(Candidate.email == "mireply@example.com").one()
    assert cand.status == "incomplete"
    templates_before = list(_outbound_templates(db))

    # Reply with the missing links
    monkeypatch.setattr(h, "parse_resume", fake_parse_resume_factory(text=""))
    gmail_fake.deliver(make_inbound(
        "mi-reply-1b", "mireply@example.com", "MiReply", "Re: Missing items",
        "Here are my links: https://github.com/mireply  https://mireply.dev",
        attachments=[],
    ))
    enqueue_ingest("mi-reply-1b")
    run_pipeline()

    all_templates = _outbound_templates(db)
    # Count new acknowledgments and duplicate_updates added by the reply
    new_acks = sum(1 for t in all_templates if t == "acknowledgment") - sum(1 for t in templates_before if t == "acknowledgment")
    new_dups = sum(1 for t in all_templates if t == "duplicate_update")

    assert new_acks == 0, f"reply to missing_items should not trigger acknowledgment, got {new_acks} new"
    assert new_dups == 0, f"reply to missing_items should not trigger duplicate_update, got {new_dups}"


# ==================== Regression: logs grouped by candidate ====================
#
# Bug 1: logs were not sorted/grouped by candidate. The API now returns logs
# grouped by candidate (most-recent-activity first, chronological within group).


def test_logs_api_groups_by_candidate(
    db, settings_row, monkeypatch, gmail_fake, make_inbound, pdf_attachment, enqueue_ingest, run_pipeline, client
):
    """The /api/logs endpoint must return logs grouped by candidate, with the
    most recently active candidate's group first, and chronological order
    within each group."""
    # Process two candidates so their logs interleave in created_at
    gmail_fake.deliver(make_inbound(
        "log-a", "alice@example.com", "Alice", "Application",
        "https://github.com/alice  https://alice.dev",
        attachments=[pdf_attachment()],
    ))
    enqueue_ingest("log-a")
    run_pipeline()

    gmail_fake.deliver(make_inbound(
        "log-b", "bob@example.com", "Bob", "Application",
        "https://github.com/bob  https://bob.dev",
        attachments=[pdf_attachment()],
    ))
    enqueue_ingest("log-b")
    run_pipeline()

    resp = client.get("/api/logs?limit=500")
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) > 0

    # Extract the sequence of candidate_ids (including nulls for system logs)
    cand_ids = [l.get("candidate_id") for l in logs]

    # Verify grouping: once we leave a candidate's group, we should not return to it.
    seen_groups: list[int | None] = []
    for cid in cand_ids:
        if not seen_groups or seen_groups[-1] != cid:
            assert cid not in seen_groups, (
                f"candidate_id {cid} appears in a non-contiguous block — logs are not grouped"
            )
            seen_groups.append(cid)

    # Verify within-group chronological order
    for cid in set(cand_ids):
        group_logs = [l for l in logs if l.get("candidate_id") == cid]
        timestamps = [l["created_at"] for l in group_logs]
        assert timestamps == sorted(timestamps), (
            f"logs for candidate {cid} are not in chronological order"
        )
