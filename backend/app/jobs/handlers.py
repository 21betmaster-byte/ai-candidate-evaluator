"""Job handlers — one function per pipeline step.

Each handler accepts (db: Session, job: Job) and either:
  - completes successfully (worker marks job done)
  - raises an exception (worker reschedules with backoff)
  - enqueues the next job(s) in the chain

Pipeline chain for a complete application:
  ingest_email → (acknowledgment + parse_resume) → fetch_github → fetch_portfolio
  → discover_secondary → structure_profile → score → decide → send_decision_email

For incomplete / non-application emails, ingest_email enqueues a single
send_template_email job and stops.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.gmail import client as gmail
from app.gmail.client import InboundEmail, Attachment
from app.jobs import queue
from app.logging_setup import log_event, log_step
from app.models import (
    AppSettings,
    Candidate,
    EmailLog,
    Evaluation,
    Job,
    ProcessingLog,
)
from app.pipeline.classify import classify_email
from app.pipeline.decide import decide_tier
from app.pipeline.extract import classify_urls, find_urls, is_linkedin
from app.pipeline.github import fetch_github, GitHubCandidateError, GitHubInfraError
from app.pipeline.portfolio import fetch_portfolio, PortfolioCandidateError, PortfolioInfraError
from app.pipeline.resume import parse_resume, parse_pdf_bytes
from app.pipeline.score import score_candidate
from app.pipeline.structure import structure_profile
from app.emails import templates as tpl

log = logging.getLogger(__name__)


# ---------------------------- Helpers ----------------------------


def _settings_row(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _log_step(db: Session, candidate_id: int | None, step: str, message: str, level: str = "info", meta: dict | None = None) -> None:
    """Back-compat shim: delegates to `log_event` which writes both stdout + DB."""
    log_event(db, candidate_id, step, message, level=level, meta=meta)


def _get_or_create_candidate(db: Session, email_addr: str, name: str | None) -> Candidate:
    cand = db.query(Candidate).filter(Candidate.email == email_addr).first()
    if cand:
        return cand
    cand = Candidate(email=email_addr, name=name, status="pending")
    db.add(cand)
    db.flush()
    return cand


def _new_evaluation(db: Session, candidate: Candidate, source_message_id: str) -> Evaluation:
    # Mark previous as superseded
    for ev in candidate.evaluations:
        if not ev.superseded:
            ev.superseded = True
            db.add(ev)
    ev = Evaluation(candidate_id=candidate.id, source_message_id=source_message_id)
    db.add(ev)
    db.flush()
    candidate.current_evaluation_id = ev.id
    db.add(candidate)
    return ev


def _adopt_orphan_logs(db: Session, message_id: str, candidate_id: int) -> None:
    """Back-fill candidate_id on pre-candidate logs (email_received, classify)
    so the dashboard detail page shows the complete timeline. Matches by
    meta->>message_id which is set at the top of handle_ingest_email."""
    orphans = (
        db.query(ProcessingLog)
        .filter(ProcessingLog.candidate_id.is_(None))
        .all()
    )
    for row in orphans:
        if (row.meta or {}).get("message_id") == message_id:
            row.candidate_id = candidate_id
            db.add(row)
    db.flush()


def _log_inbound(db: Session, email: InboundEmail, candidate: Candidate | None, classification: str | None) -> None:
    db.add(EmailLog(
        candidate_id=candidate.id if candidate else None,
        gmail_message_id=email.message_id,
        direction="in",
        classification=classification,
        sender=email.sender_email,
        subject=email.subject,
        body_snippet=(email.body_text or "")[:1000],
    ))
    db.flush()


def _enqueue_send_template(db: Session, candidate_id: int | None, template_key: str, payload: dict) -> None:
    queue.enqueue(
        db,
        type="send_template_email",
        candidate_id=candidate_id,
        payload={"template": template_key, **payload},
    )


def _render_template(template_key: str, payload: dict, company: str) -> tpl.RenderedEmail:
    name = payload.get("name")
    if template_key == "acknowledgment":
        return tpl.acknowledgment(name, company)
    if template_key == "pass_decision":
        return tpl.pass_decision(name, payload.get("next_steps", ""), company)
    if template_key == "fail_decision":
        return tpl.fail_decision(name, payload.get("reason", ""), company)
    if template_key == "missing_items":
        return tpl.missing_items(name, payload.get("missing", []), company)
    if template_key == "non_pdf_attachment":
        return tpl.non_pdf_attachment(name, company)
    if template_key == "duplicate_update":
        return tpl.duplicate_update(name, company)
    if template_key == "gibberish":
        return tpl.gibberish(name, company)
    if template_key == "spam_sales":
        return tpl.spam_sales(name, company)
    if template_key == "question_response":
        return tpl.question_response(name, company)
    if template_key == "empty_email":
        return tpl.empty_email(name, company)
    if template_key == "portfolio_is_linkedin":
        return tpl.portfolio_is_linkedin(name, company)
    if template_key == "github_unreachable":
        return tpl.github_unreachable(name, company)
    if template_key == "portfolio_unreachable":
        return tpl.portfolio_unreachable(name, company)
    if template_key == "reminder":
        return tpl.reminder(name, payload.get("missing", []), company)
    if template_key == "rapid_emails":
        return tpl.rapid_emails(name, company)
    if template_key == "unclassifiable":
        return tpl.unclassifiable(name, company)
    if template_key == "caveat_acknowledgment":
        return tpl.caveat_acknowledgment(name, company)
    if template_key == "processing_error_notice":
        return tpl.processing_error_notice(name, company)
    raise ValueError(f"unknown template: {template_key}")


# ---------------------------- ingest_email ----------------------------


def handle_ingest_email(db: Session, job: Job) -> None:
    """Pull a Gmail message, classify it, and either enqueue a one-shot
    template email (non-application path) or kick off the full pipeline.
    """
    settings = _settings_row(db)
    company = settings.company_name or get_settings().company_name
    message_id = (job.payload or {}).get("message_id")
    if not message_id:
        raise ValueError("ingest_email job missing message_id")

    # Idempotency: if we already have an inbound log for this message, skip.
    existing = db.query(EmailLog).filter(
        EmailLog.gmail_message_id == message_id, EmailLog.direction == "in"
    ).first()
    if existing:
        gmail.mark_processed(message_id)
        return

    email = gmail.fetch_email(message_id)
    log_event(
        db, None, "email_received",
        f"inbound message {message_id} from {email.sender_email}",
        meta={
            "message_id": message_id,
            "sender": email.sender_email,
            "subject": (email.subject or "")[:200],
            "attachment_count": len(email.attachments),
        },
    )

    with log_step(db, None, "classify", meta={"message_id": message_id}) as ctx:
        cls = classify_email(email)
        ctx["category"] = cls["category"]
    category = cls["category"]

    # Auto-reply: log + ignore. Never email back.
    if category == "auto_reply":
        db.add(EmailLog(
            gmail_message_id=email.message_id,
            direction="in",
            classification="auto_reply",
            sender=email.sender_email,
            subject=email.subject,
            body_snippet=(email.body_text or "")[:500],
        ))
        gmail.mark_processed(message_id)
        return

    if category == "spam_sales":
        cand = None
        _log_inbound(db, email, cand, "spam_sales")
        _enqueue_send_template(db, None, "spam_sales", {"name": email.sender_name, "to": email.sender_email})
        gmail.mark_processed(message_id)
        return

    if category == "gibberish":
        _log_inbound(db, email, None, "gibberish")
        _enqueue_send_template(db, None, "gibberish", {"name": email.sender_name, "to": email.sender_email})
        gmail.mark_processed(message_id)
        return

    if category == "question":
        _log_inbound(db, email, None, "question")
        _enqueue_send_template(db, None, "question_response", {
            "name": email.sender_name, "to": email.sender_email,
        })
        gmail.mark_processed(message_id)
        return

    if category == "other":
        _log_inbound(db, email, None, "other")
        _enqueue_send_template(db, None, "unclassifiable", {"name": email.sender_name, "to": email.sender_email})
        gmail.mark_processed(message_id)
        return

    # ---- application path ----
    # Detect duplicate (existing candidate). We capture the prior evaluation's
    # resume / github / portfolio so that if the new email only contains a
    # subset (e.g. just a missing GitHub link), we can merge it with what the
    # candidate already sent instead of dropping prior context.
    existing_cand = db.query(Candidate).filter(Candidate.email == email.sender_email).first()
    is_duplicate = existing_cand is not None and existing_cand.current_evaluation_id is not None
    prior_ev = (
        db.get(Evaluation, existing_cand.current_evaluation_id)
        if is_duplicate else None
    )
    prior_resume_text = prior_ev.raw_resume_text if prior_ev else None
    prior_resume_filename = prior_ev.resume_filename if prior_ev else None
    prior_github_url = prior_ev.github_url if prior_ev else None
    prior_portfolio_url = prior_ev.portfolio_url if prior_ev else None

    cand = _get_or_create_candidate(db, email.sender_email, email.sender_name)
    _adopt_orphan_logs(db, message_id, cand.id)
    _log_inbound(db, email, cand, "application")
    cand.last_inbound_message_id = email.message_id
    db.add(cand)

    _log_step(db, cand.id, "ingest", "email ingested", meta={"message_id": message_id, "duplicate": is_duplicate})

    # Re-apply guard: if this candidate is already flagged for human intake review,
    # don't restart the pipeline or send another acknowledgment. The new inbound
    # is already logged above; the hiring manager will see it in email history.
    if (
        existing_cand is not None
        and existing_cand.status == "manual_review"
        and existing_cand.review_source == "intake_review"
    ):
        _log_step(
            db, cand.id, "ingest",
            "follow-up on intake_review candidate — no new pipeline run",
            meta={"message_id": message_id},
        )
        gmail.mark_processed(message_id)
        return

    # Sonnet flagged this as a contextual application that doesn't fit the
    # standard checklist. Hand off to a human instead of running the pipeline
    # or looping missing_items reminders. Threshold gates the noisy long tail.
    if (
        category == "application_needs_review"
        and cls.get("confidence", 0) >= get_settings().caveat_confidence_threshold
    ):
        # Still parse resume + extract URLs so the hiring manager sees whatever
        # the candidate did send on the detail page. Best-effort — failures here
        # must not block the handoff.
        try:
            parsed = parse_resume(email.attachments)
        except Exception:
            parsed = None
        ev = _new_evaluation(db, cand, source_message_id=message_id)
        if parsed is not None:
            ev.raw_resume_text = parsed.text or None
            ev.resume_filename = parsed.selected_filename
            body_urls = find_urls(email.body_text or "")
            all_urls = list({*body_urls, *parsed.urls})
            github_url, portfolio_url, _ = classify_urls(all_urls)
            ev.github_url = github_url
            ev.portfolio_url = portfolio_url
        db.add(ev)

        cand.status = "manual_review"
        cand.review_source = "intake_review"
        cand.review_reason = (cls.get("review_reason") or "")[:500] or None
        db.add(cand)

        _enqueue_send_template(db, cand.id, "caveat_acknowledgment", {
            "name": email.sender_name, "to": email.sender_email,
        })
        _log_step(
            db, cand.id, "intake_review",
            f"flagged for human review: {cand.review_reason or '(no reason)'}",
            meta={"confidence": cls.get("confidence", 0)},
        )
        gmail.mark_processed(message_id)
        return

    # Empty body and no attachments → empty_email template (handled by classifier as gibberish, but be safe)
    if not (email.body_text or "").strip() and not email.attachments:
        _enqueue_send_template(db, cand.id, "empty_email", {"name": email.sender_name, "to": email.sender_email})
        cand.status = "incomplete"
        gmail.mark_processed(message_id)
        return

    # Parse resume now (synchronously) — needed to classify what's missing.
    with log_step(db, cand.id, "parse_resume", meta={"attachment_count": len(email.attachments)}) as ctx:
        parsed = parse_resume(email.attachments)
        ctx["resume_present"] = parsed.resume_present
        ctx["any_attachment"] = parsed.any_attachment
        ctx["resume_filename"] = parsed.selected_filename
        ctx["url_count"] = len(parsed.urls)

    # Wrong-format attachment: had attachments but no supported resume (PDF or DOCX).
    if parsed.any_attachment and not parsed.resume_present:
        _enqueue_send_template(db, cand.id, "non_pdf_attachment", {"name": email.sender_name, "to": email.sender_email})
        cand.status = "incomplete"
        cand.missing_items = ["resume (must be a PDF or DOCX)"]
        gmail.mark_processed(message_id)
        return

    # Build new evaluation row
    ev = _new_evaluation(db, cand, source_message_id=message_id)
    ev.raw_resume_text = parsed.text or None
    ev.resume_filename = parsed.selected_filename

    # Aggregate URLs from email body + resume
    body_urls = find_urls(email.body_text or "")
    all_urls = list({*body_urls, *parsed.urls})
    github_url, portfolio_url, linkedin_url = classify_urls(all_urls)
    ev.github_url = github_url
    ev.portfolio_url = portfolio_url

    # Merge from prior evaluation: any field the new email did NOT supply is
    # carried forward from what the candidate sent previously. The new email
    # always wins when it provides a value.
    merged_fields: list[str] = []
    if is_duplicate:
        if not ev.raw_resume_text and prior_resume_text:
            ev.raw_resume_text = prior_resume_text
            ev.resume_filename = prior_resume_filename
            parsed.resume_present = True  # downstream branches read this
            merged_fields.append("resume")
        if not ev.github_url and prior_github_url:
            ev.github_url = prior_github_url
            github_url = prior_github_url
            merged_fields.append("github_url")
        if not ev.portfolio_url and prior_portfolio_url:
            ev.portfolio_url = prior_portfolio_url
            portfolio_url = prior_portfolio_url
            merged_fields.append("portfolio_url")
        if merged_fields:
            _log_step(
                db, cand.id, "ingest",
                f"merged from prior evaluation: {', '.join(merged_fields)}",
                meta={"merged": merged_fields, "prior_evaluation_id": prior_ev.id if prior_ev else None},
            )

    db.add(ev)
    db.flush()

    # Send acknowledgment for any application-shaped email (complete OR incomplete)
    _enqueue_send_template(db, cand.id, "acknowledgment", {"name": email.sender_name, "to": email.sender_email})

    # Duplicate notice (replaces normal ack? PRD says it's a separate "got your update" email)
    if is_duplicate:
        _enqueue_send_template(db, cand.id, "duplicate_update", {"name": email.sender_name, "to": email.sender_email})

    # Decide what's missing AFTER secondary discovery (which happens later in pipeline if we have *something* to chase).
    # Strategy: if we have at least the portfolio_url, run discover_secondary first; if we have nothing to chase,
    # send the missing-items email immediately.
    has_resume = parsed.resume_present
    has_github = bool(github_url)
    has_portfolio = bool(portfolio_url)

    # If portfolio is actually LinkedIn, tell them.
    if linkedin_url and not portfolio_url:
        _enqueue_send_template(db, cand.id, "portfolio_is_linkedin", {"name": email.sender_name, "to": email.sender_email})
        cand.status = "incomplete"
        missing = []
        if not has_resume:
            missing.append("a resume PDF")
        if not has_github:
            missing.append("a link to your GitHub profile")
        missing.append("a real portfolio link (not LinkedIn)")
        cand.missing_items = missing
        db.add(cand)
        gmail.mark_processed(message_id)
        return

    # If portfolio exists, attempt secondary discovery before flagging missing.
    if has_portfolio and (not has_github or not has_resume):
        queue.enqueue(db, type="discover_secondary", candidate_id=cand.id, payload={"evaluation_id": ev.id})
        cand.status = "pending"
        db.add(cand)
        gmail.mark_processed(message_id)
        return

    # Nothing to chase — if anything's missing, send missing items
    if not (has_resume and has_github and has_portfolio):
        missing = _missing_list(has_resume, has_github, has_portfolio)
        cand.status = "incomplete"
        cand.missing_items = missing
        _enqueue_send_template(db, cand.id, "missing_items", {
            "name": email.sender_name, "to": email.sender_email, "missing": missing,
        })
        # Schedule reminder
        queue.enqueue(
            db, type="send_reminder", candidate_id=cand.id,
            payload={"missing": missing, "to": email.sender_email, "name": email.sender_name},
            delay_seconds=(_settings_row(db).reminder_hours or 48) * 3600,
        )
        db.add(cand)
        gmail.mark_processed(message_id)
        return

    # Complete — kick off the full pipeline
    queue.enqueue(db, type="fetch_github", candidate_id=cand.id, payload={"evaluation_id": ev.id})
    gmail.mark_processed(message_id)


def _missing_list(has_resume: bool, has_github: bool, has_portfolio: bool) -> list[str]:
    out = []
    if not has_resume:
        out.append("a resume PDF (attached to your email)")
    if not has_github:
        out.append("a link to your GitHub profile")
    if not has_portfolio:
        out.append("a link to your portfolio or projects")
    return out


def _mark_incomplete_and_remind(
    db: Session, cand: Candidate, missing: list[str], *, template: str = "missing_items"
) -> None:
    """Consolidated path for any candidate-fixable issue: mark incomplete, set
    missing_items, send the candidate-facing template, and schedule a reminder."""
    cand.status = "incomplete"
    cand.missing_items = missing
    _enqueue_send_template(db, cand.id, template, {
        "name": cand.name, "to": cand.email, "missing": missing,
    })
    queue.enqueue(
        db, type="send_reminder", candidate_id=cand.id,
        payload={"missing": missing, "to": cand.email, "name": cand.name},
        delay_seconds=(_settings_row(db).reminder_hours or 48) * 3600,
    )
    db.add(cand)


# ---------------------------- discover_secondary ----------------------------


def handle_discover_secondary(db: Session, job: Job) -> None:
    """If GitHub/resume are missing, scan portfolio page for them. Then continue
    pipeline if complete, else send missing_items."""
    ev_id = (job.payload or {}).get("evaluation_id")
    ev = db.get(Evaluation, ev_id)
    cand = db.get(Candidate, ev.candidate_id)
    _log_step(db, cand.id, "discover_secondary", f"scanning portfolio {ev.portfolio_url}")

    has_resume = bool(ev.raw_resume_text)
    has_github = bool(ev.github_url)

    try:
        pdata = fetch_portfolio(ev.portfolio_url)
    except PortfolioCandidateError as e:
        _log_step(db, cand.id, "discover_secondary", f"portfolio rejected: {e}", level="warn")
        missing: list[str] = []
        if not has_resume:
            missing.append("a resume PDF (attached to your email)")
        if not has_github:
            missing.append("a link to your GitHub profile")
        # LinkedIn-as-portfolio keeps its dedicated template; unreachable
        # portfolios use the generic missing_items template. Either way, the
        # candidate has to fix the portfolio link — same category, same
        # reminder flow.
        if "linkedin" in str(e).lower():
            missing.append("a real portfolio or projects link (LinkedIn isn't enough)")
            template = "portfolio_is_linkedin"
        else:
            missing.append("a working portfolio link (the one you sent didn't load)")
            template = "missing_items"
        _mark_incomplete_and_remind(db, cand, missing, template=template)
        return
    except PortfolioInfraError:
        # Let the queue retry
        raise

    ev.portfolio_data = {
        "url": pdata.url,
        "final_url": pdata.final_url,
        "title": pdata.title,
        "text_snippet": pdata.text_snippet,
        "project_links": pdata.project_links,
    }

    if not has_github and pdata.discovered_github_url:
        ev.github_url = pdata.discovered_github_url
        has_github = True
        _log_step(db, cand.id, "discover_secondary", f"github discovered from portfolio: {ev.github_url}")

    if not has_resume and pdata.discovered_resume_bytes:
        text, urls = parse_pdf_bytes(pdata.discovered_resume_bytes)
        if text:
            ev.raw_resume_text = text
            ev.resume_filename = pdata.discovered_resume_url or "portfolio_resume.pdf"
            has_resume = True
            _log_step(db, cand.id, "discover_secondary", f"resume discovered from portfolio: {pdata.discovered_resume_url}")
            # Maybe new URLs found in the discovered resume
            from app.pipeline.extract import classify_urls
            g2, _, _ = classify_urls(urls)
            if not has_github and g2:
                ev.github_url = g2
                has_github = True

    db.add(ev)

    if has_resume and has_github:
        # Complete now — proceed
        queue.enqueue(db, type="fetch_github", candidate_id=cand.id, payload={"evaluation_id": ev.id})
        cand.status = "pending"
        db.add(cand)
        return

    # Still missing
    missing = _missing_list(has_resume, has_github, has_portfolio=True)
    cand.status = "incomplete"
    cand.missing_items = missing
    _enqueue_send_template(db, cand.id, "missing_items", {"name": cand.name, "to": cand.email, "missing": missing})
    queue.enqueue(
        db, type="send_reminder", candidate_id=cand.id,
        payload={"missing": missing, "to": cand.email, "name": cand.name},
        delay_seconds=(_settings_row(db).reminder_hours or 48) * 3600,
    )
    db.add(cand)


# ---------------------------- fetch_github ----------------------------


def handle_fetch_github(db: Session, job: Job) -> None:
    ev_id = (job.payload or {}).get("evaluation_id")
    ev = db.get(Evaluation, ev_id)
    cand = db.get(Candidate, ev.candidate_id)
    with log_step(db, cand.id, "fetch_github", meta={"github_url": ev.github_url}) as ctx:
        try:
            data = fetch_github(ev.github_url)
        except GitHubCandidateError as e:
            ctx["outcome"] = "candidate_error"
            ctx["error"] = str(e)[:200]
            log_event(db, cand.id, "fetch_github", f"candidate-side error: {e}", level="warn")
            missing = list(cand.missing_items or [])
            gh_item = "a working public GitHub profile link"
            if gh_item not in missing:
                missing.append(gh_item)
            _mark_incomplete_and_remind(db, cand, missing, template="github_unreachable")
            return
        except GitHubInfraError:
            raise  # retry via queue
        ctx["public_repos"] = data.public_repos
        ctx["followers"] = data.followers

    ev.github_data = {
        "username": data.username,
        "profile_url": data.profile_url,
        "public_repos": data.public_repos,
        "followers": data.followers,
        "languages": data.languages,
        "recent_repos_pushed_6mo": data.recent_repos_pushed_6mo,
        "recent_commits_90d": data.recent_commits_90d,
        "top_repos": data.top_repos,
    }
    db.add(ev)
    queue.enqueue(db, type="fetch_portfolio", candidate_id=cand.id, payload={"evaluation_id": ev.id})


# ---------------------------- fetch_portfolio ----------------------------


def handle_fetch_portfolio(db: Session, job: Job) -> None:
    ev_id = (job.payload or {}).get("evaluation_id")
    ev = db.get(Evaluation, ev_id)
    cand = db.get(Candidate, ev.candidate_id)

    # If discover_secondary already populated portfolio_data, skip refetch.
    if ev.portfolio_data:
        _log_step(db, cand.id, "fetch_portfolio", "using cached portfolio_data")
        queue.enqueue(db, type="structure_profile", candidate_id=cand.id, payload={"evaluation_id": ev.id})
        return

    with log_step(db, cand.id, "fetch_portfolio", meta={"portfolio_url": ev.portfolio_url}) as ctx:
        try:
            pdata = fetch_portfolio(ev.portfolio_url)
        except PortfolioCandidateError as e:
            ctx["outcome"] = "candidate_error"
            ctx["error"] = str(e)[:200]
            log_event(db, cand.id, "fetch_portfolio", f"portfolio rejected: {e}", level="warn")
            missing = list(cand.missing_items or [])
            if "linkedin" in str(e).lower():
                item = "a real portfolio or projects link (LinkedIn isn't enough)"
                template = "portfolio_is_linkedin"
            else:
                item = "a working portfolio link (the one you sent didn't load)"
                template = "portfolio_unreachable"
            if item not in missing:
                missing.append(item)
            _mark_incomplete_and_remind(db, cand, missing, template=template)
            return
        except PortfolioInfraError:
            raise
        ctx["final_url"] = pdata.final_url
        ctx["project_link_count"] = len(pdata.project_links or [])

    ev.portfolio_data = {
        "url": pdata.url,
        "final_url": pdata.final_url,
        "title": pdata.title,
        "text_snippet": pdata.text_snippet,
        "project_links": pdata.project_links,
    }
    db.add(ev)
    queue.enqueue(db, type="structure_profile", candidate_id=cand.id, payload={"evaluation_id": ev.id})


# ---------------------------- structure_profile ----------------------------


def handle_structure_profile(db: Session, job: Job) -> None:
    ev_id = (job.payload or {}).get("evaluation_id")
    ev = db.get(Evaluation, ev_id)
    cand = db.get(Candidate, ev.candidate_id)
    with log_step(db, cand.id, "structure_profile") as ctx:
        profile = structure_profile(ev.raw_resume_text or "", ev.github_data, ev.portfolio_data)
        ctx["name"] = profile.get("name")
    ev.structured_profile = profile
    if not cand.name and profile.get("name"):
        cand.name = profile["name"]
        db.add(cand)
    db.add(ev)
    queue.enqueue(db, type="score", candidate_id=cand.id, payload={"evaluation_id": ev.id})


# ---------------------------- score ----------------------------


def handle_score(db: Session, job: Job) -> None:
    ev_id = (job.payload or {}).get("evaluation_id")
    ev = db.get(Evaluation, ev_id)
    cand = db.get(Candidate, ev.candidate_id)
    settings = _settings_row(db)
    from app.models import DEFAULT_RUBRIC
    rubric = settings.rubric or DEFAULT_RUBRIC
    # Don't blow up the log with full descriptions — record keys + weights only.
    meta = {"rubric": [{"key": d["key"], "weight": d["weight"]} for d in rubric]}
    with log_step(db, cand.id, "score", meta=meta) as ctx:
        result = score_candidate(ev.structured_profile or {}, rubric)
        ctx["overall_score"] = result["overall_score"]
    ev.scores = result["scores"]
    ev.overall_score = result["overall_score"]
    ev.decision_reason = result["decision_reason"]
    db.add(ev)
    queue.enqueue(db, type="decide", candidate_id=cand.id, payload={"evaluation_id": ev.id})


# ---------------------------- decide ----------------------------


def handle_decide(db: Session, job: Job) -> None:
    ev_id = (job.payload or {}).get("evaluation_id")
    ev = db.get(Evaluation, ev_id)
    cand = db.get(Candidate, ev.candidate_id)
    settings = _settings_row(db)
    thresholds = settings.tier_thresholds or {"auto_fail_ceiling": 49, "manual_review_ceiling": 69, "auto_pass_floor": 70}
    tier = decide_tier(ev.overall_score or 0.0, thresholds)
    ev.tier = tier
    db.add(ev)
    _log_step(db, cand.id, "decide", f"tier={tier} score={ev.overall_score}")

    if tier == "auto_pass":
        cand.status = "auto_pass"
        _enqueue_send_template(db, cand.id, "pass_decision", {
            "name": cand.name, "to": cand.email,
            "next_steps": settings.pass_next_steps_text or "",
        })
    elif tier == "auto_fail":
        cand.status = "auto_fail"
        _enqueue_send_template(db, cand.id, "fail_decision", {
            "name": cand.name, "to": cand.email,
            "reason": ev.decision_reason or "",
        })
    else:
        cand.status = "manual_review"
        # No email — wait for hiring manager.

    db.add(cand)


# ---------------------------- send_template_email ----------------------------


def handle_send_template_email(db: Session, job: Job) -> None:
    payload = job.payload or {}
    template_key = payload["template"]
    to = payload.get("to")
    if not to and job.candidate_id:
        cand = db.get(Candidate, job.candidate_id)
        to = cand.email if cand else None
    if not to:
        raise ValueError(f"send_template_email missing 'to' (template={template_key})")
    settings = _settings_row(db)
    rendered = _render_template(template_key, payload, settings.company_name)
    msg_id = gmail.send_email(to=to, body_text=rendered.body)
    db.add(EmailLog(
        candidate_id=job.candidate_id,
        gmail_message_id=msg_id,
        direction="out",
        sender=get_settings().gmail_address,
        subject=f"(reply: {rendered.template_key})",
        body_snippet=rendered.body[:1000],
        template_used=rendered.template_key,
    ))
    _log_step(db, job.candidate_id, "send_email", f"sent {template_key}")


# ---------------------------- send_reminder ----------------------------


def handle_send_reminder(db: Session, job: Job) -> None:
    """Send reminder ONLY if candidate is still incomplete with the same missing items."""
    if not job.candidate_id:
        return
    cand = db.get(Candidate, job.candidate_id)
    if not cand or cand.status != "incomplete":
        _log_step(db, job.candidate_id, "send_reminder", "skipped — candidate no longer incomplete")
        return
    payload = job.payload or {}
    missing = payload.get("missing") or cand.missing_items or []
    settings = _settings_row(db)
    rendered = tpl.reminder(cand.name, missing, settings.company_name)
    msg_id = gmail.send_email(to=cand.email, body_text=rendered.body)
    db.add(EmailLog(
        candidate_id=cand.id,
        gmail_message_id=msg_id,
        direction="out",
        sender=get_settings().gmail_address,
        subject="(reply: reminder)",
        body_snippet=rendered.body[:1000],
        template_used="reminder",
    ))
    _log_step(db, cand.id, "send_reminder", "reminder sent")


# ---------------------------- registry ----------------------------


HANDLERS: dict[str, Callable[[Session, Job], None]] = {
    "ingest_email": handle_ingest_email,
    "discover_secondary": handle_discover_secondary,
    "fetch_github": handle_fetch_github,
    "fetch_portfolio": handle_fetch_portfolio,
    "structure_profile": handle_structure_profile,
    "score": handle_score,
    "decide": handle_decide,
    "send_template_email": handle_send_template_email,
    "send_reminder": handle_send_reminder,
}
