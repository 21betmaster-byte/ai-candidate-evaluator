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
from tests.conftest import _FakeGitHubData, _FakePortfolioData, fake_parse_resume_factory


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
        "technical_depth", "shipped_products", "business_thinking", "speed_of_execution"
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
    assert "duplicate_update" in _outbound_templates(db)


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
    # Pipeline now continues through scoring even when GitHub is unreachable
    assert cand.status in ("auto_pass", "auto_fail", "manual_review"), f"expected scored status, got {cand.status}"
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
    def _mid_score(profile, rubric):
        return {
            "scores": {k: {"score": 55, "reasoning": ""} for k in ("technical_depth","shipped_products","business_thinking","speed_of_execution")},
            "overall_score": 55.0,
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
    # And the candidate got the duplicate-update notice
    assert "duplicate_update" in _outbound_templates(db)


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
    assert "duplicate_update" in _outbound_templates(db)


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
