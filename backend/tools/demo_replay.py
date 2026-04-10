"""Leadership demo replay — walk through a candidate's processing timeline.

Connects to the production Postgres DB, queries processing_logs for a given
candidate, and renders each step as a narrated, color-coded terminal block.
Press Enter to advance between steps.

Usage:
    python -m tools.demo_replay jane@example.com
    python -m tools.demo_replay --id 42
    python -m tools.demo_replay --recent
    python -m tools.demo_replay --latest
    python -m tools.demo_replay --latest --auto
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AppSettings, Candidate, EmailLog, Evaluation, ProcessingLog


# ---------------------------------------------------------------------------
# ANSI helpers (no deps)
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_WHITE = "\033[37m"
_BG_BLUE = "\033[44m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{_RESET}"


def _level_color(level: str) -> str:
    if level == "error":
        return _RED
    if level in ("warning", "warn"):
        return _YELLOW
    return _GREEN


def _level_icon(level: str) -> str:
    if level == "error":
        return _c(_RED, "FAILED")
    if level in ("warning", "warn"):
        return _c(_YELLOW, "WARNING")
    return _c(_GREEN, "OK")


# ---------------------------------------------------------------------------
# Step display names & narration
# ---------------------------------------------------------------------------

_STEP_DISPLAY = {
    "email_received": "Email Received",
    "classify": "Email Classification (Sonnet)",
    "ingest": "Candidate Record Created",
    "parse_resume": "Resume Parsed",
    "discover_secondary": "Secondary Source Discovery",
    "fetch_github": "GitHub Profile Fetched",
    "fetch_portfolio": "Portfolio Scraped",
    "structure_profile": "Profile Structured (Sonnet)",
    "score": "Scoring (Opus)",
    "decide": "Decision",
    "send_email": "Email Sent",
}

_CATEGORY_EXPLANATIONS = {
    "application": "The pipeline will now extract the resume and begin evaluation.",
    "auto_reply": "This is an auto-reply / out-of-office. No response will be sent.",
    "gibberish": "The email content was not parseable. A friendly nudge was sent.",
    "spam_sales": "This appears to be spam or a sales pitch. A playful deflection was sent.",
    "question": "The sender asked a question about the role. A helpful response was generated.",
    "other": "The email didn't match any known category. A generic response was sent.",
    "application_needs_review": "Sonnet flagged this email as needing human review before full evaluation.",
}


# ---------------------------------------------------------------------------
# Template decision-logic explanations
# ---------------------------------------------------------------------------

_TEMPLATE_LOGIC: dict[str, str] = {
    "pass_decision": (
        "The candidate's weighted score met or exceeded the auto-pass threshold.\n"
        "  Rule: overall_score >= auto_pass_floor (default 50).\n"
        "  The system sends a congratulatory email with configured next-steps text."
    ),
    "fail_decision": (
        "The candidate's weighted score fell below the auto-fail ceiling.\n"
        "  Rule: overall_score <= auto_fail_ceiling (default 48).\n"
        "  A polite rejection is sent. Scores and rubric details are never included."
    ),
    "missing_items": (
        "The application is missing one or more required materials.\n"
        "  Rule: After parsing, the system checks three items in order:\n"
        "    1. Resume (PDF or DOCX attached to the email)\n"
        "    2. GitHub profile link (in email body or resume text)\n"
        "    3. Portfolio / project link (in email body or resume text)\n"
        "  Whichever items are missing are listed in the email."
    ),
    "non_pdf_attachment": (
        "The email had attachment(s) but none were a valid PDF or DOCX.\n"
        "  Rule: any_attachment=True AND resume_present=False.\n"
        "  Common trigger: .pages, .rtf, .zip, or image-only attachments.\n"
        "  The candidate is asked to resend as PDF or Word."
    ),
    "portfolio_is_linkedin": (
        "The candidate provided a LinkedIn URL where a portfolio was expected.\n"
        "  Rule: A linkedin.com URL was found but no other portfolio link.\n"
        "  The system asks for a real portfolio (personal site, Behance, GitHub Pages, etc.)."
    ),
    "github_unreachable": (
        "The GitHub profile URL returned a 404 or is set to private.\n"
        "  Rule: GitHub API returned 404 (user not found) or 403 (private).\n"
        "  This is treated as a candidate-side error (not infra).\n"
        "  The candidate is asked to check the URL and ensure the profile is public."
    ),
    "portfolio_unreachable": (
        "The portfolio URL could not be loaded after retries.\n"
        "  Rule: HTTP fetch of the portfolio returned an error or timed out.\n"
        "  This is treated as a candidate-side error.\n"
        "  The candidate is asked to verify the URL is correct and accessible."
    ),
    "gibberish": (
        "The email content was not parseable as a real message.\n"
        "  Rule: Sonnet classified the email as 'gibberish'.\n"
        "  A lighthearted nudge is sent with application instructions."
    ),
    "spam_sales": (
        "The email was identified as spam or a sales pitch.\n"
        "  Rule: Sonnet classified the email as 'spam_sales'.\n"
        "  A fun deflection is sent."
    ),
    "question_response": (
        "The sender asked a question about the role instead of applying.\n"
        "  Rule: Sonnet classified the email as 'question' and extracted the question text.\n"
        "  Sonnet generated a helpful on-brand answer."
    ),
    "empty_email": (
        "The email had no body text and no attachments.\n"
        "  Rule: body is empty AND attachment count is zero.\n"
        "  A friendly nudge is sent with application instructions."
    ),
    "unclassifiable": (
        "Sonnet could not confidently classify the email.\n"
        "  Rule: classify returned 'other'.\n"
        "  A generic response is sent."
    ),
    "caveat_acknowledgment": (
        "Sonnet flagged this as an application that needs human review before evaluation.\n"
        "  Rule: classify returned 'application_needs_review' with high confidence.\n"
        "  The candidate is acknowledged; the application is queued for a hiring manager."
    ),
    "duplicate_update": (
        "The system detected a re-submission from the same email address.\n"
        "  Rule: An existing candidate record was found for this sender.\n"
        "  The prior evaluation is marked as superseded; a new one begins."
    ),
    "reminder": (
        "A follow-up reminder after the candidate didn't re-send missing materials.\n"
        "  Rule: The candidate was marked incomplete and the configured reminder delay\n"
        "  (default 48 hours) has elapsed without a re-submission."
    ),
    "processing_error_notice": (
        "All retry attempts for a pipeline step were exhausted.\n"
        "  Rule: A job failed max_attempts times (default 5) with exponential backoff.\n"
        "  The candidate is notified of a processing issue."
    ),
    "rapid_emails": (
        "The candidate sent multiple emails in quick succession.\n"
        "  Rule: Rate-limit detection triggered.\n"
        "  A calming response asks them to wait for a reply."
    ),
}


def _narrate(step: str, message: str, meta: dict, level: str) -> str:
    """Return a plain-English narration for a processing log entry."""
    m = meta or {}

    # Failed / error steps
    if level == "error" or message.startswith("failed"):
        error = m.get("error", message)
        return f"This step failed: {error}. The system will retry automatically."

    # Warning-level events (only for steps we don't have specific narration for)
    if level in ("warning", "warn") and step not in _STEP_DISPLAY:
        return f"A non-critical issue was detected: {message}"

    # --- per-step narration ---

    if step == "email_received":
        sender = m.get("sender", "unknown")
        subj = m.get("subject", "")
        att = m.get("attachment_count", 0)
        return (
            f"An inbound email arrived from {sender}.\n"
            f"  Subject: \"{subj}\"\n"
            f"  Attachments: {att}\n"
            f"  The email was logged for processing by the evaluation pipeline."
        )

    if step == "classify":
        if message == "started":
            return "Claude Sonnet is analyzing the email to determine its category..."
        cat = m.get("category", "unknown")
        dur = m.get("duration_ms")
        explanation = _CATEGORY_EXPLANATIONS.get(cat, "")
        dur_s = f" ({dur / 1000:.1f}s)" if dur else ""
        return (
            f"Claude Sonnet classified this email as: {_c(_BOLD, cat)}{dur_s}.\n"
            f"  {explanation}"
        )

    if step == "ingest":
        dup = m.get("duplicate", False)
        if dup:
            return (
                "This is a re-submission from the same email address.\n"
                "  The previous evaluation was superseded and a new one started."
            )
        return "A new candidate record was created in the database."

    if step == "parse_resume":
        if message == "started":
            att = m.get("attachment_count", "?")
            return f"Scanning {att} attachment(s) for a valid resume..."
        fname = m.get("resume_filename", "the attachment")
        present = m.get("resume_present", False)
        urls = m.get("url_count", 0)
        dur = m.get("duration_ms")
        dur_s = f" ({dur / 1000:.1f}s)" if dur else ""
        if not present:
            any_att = m.get("any_attachment", False)
            if any_att:
                return "Attachment(s) found but no valid PDF resume detected. Candidate flagged as incomplete."
            return "No attachments found. Candidate flagged as incomplete."
        return (
            f"Text extracted from {_c(_BOLD, fname)}{dur_s}.\n"
            f"  {urls} URL(s) discovered in the document."
        )

    if step == "discover_secondary":
        return "Checking the portfolio page for a downloadable resume or GitHub link..."

    if step == "fetch_github":
        if message == "started":
            url = m.get("github_url", "?")
            return f"Fetching GitHub profile at {url}..."
        if "candidate-side error" in message or m.get("outcome") == "candidate_error":
            error = m.get("error", message)
            return f"GitHub profile could not be reached: {error}.\n  The candidate was notified."
        repos = m.get("public_repos", "?")
        followers = m.get("followers", "?")
        commits = m.get("recent_commits_90d", "?")
        dur = m.get("duration_ms")
        dur_s = f" ({dur / 1000:.1f}s)" if dur else ""
        return (
            f"GitHub profile fetched successfully{dur_s}.\n"
            f"  Public repos: {repos} | Followers: {followers} | Recent commits (90d): {commits}"
        )

    if step == "fetch_portfolio":
        if message == "started":
            url = m.get("portfolio_url", "?")
            return f"Scraping portfolio site at {url}..."
        if "candidate-side error" in message or m.get("outcome") == "candidate_error":
            error = m.get("error", message)
            return f"Portfolio could not be reached: {error}.\n  The candidate was notified."
        url = m.get("final_url", m.get("portfolio_url", "?"))
        links = m.get("project_link_count", "?")
        dur = m.get("duration_ms")
        dur_s = f" ({dur / 1000:.1f}s)" if dur else ""
        return (
            f"Portfolio scraped successfully{dur_s}.\n"
            f"  Final URL: {url}\n"
            f"  Project links found: {links}"
        )

    if step == "structure_profile":
        if message == "started":
            return "Claude Sonnet is combining resume, GitHub, and portfolio data into a structured profile..."
        name = m.get("name", "?")
        dur = m.get("duration_ms")
        dur_s = f" ({dur / 1000:.1f}s)" if dur else ""
        return (
            f"Candidate profile structured successfully{dur_s}.\n"
            f"  Extracted candidate name: {_c(_BOLD, name)}"
        )

    if step == "score":
        if message == "started":
            return "Claude Opus is scoring the candidate against each rubric dimension..."
        overall = m.get("overall_score", "?")
        dur = m.get("duration_ms")
        dur_s = f" ({dur / 1000:.1f}s)" if dur else ""
        return (
            f"Candidate scored: {_c(_BOLD, str(overall))} / 100{dur_s}.\n"
            f"  (see score breakdown table below)"
        )

    if step == "decide":
        return ""  # handled specially in render

    if step == "send_email":
        # message usually is "sent <template_key>"
        template = message.replace("sent ", "").strip() if message.startswith("sent") else message
        return f"A '{_c(_BOLD, template)}' email was sent to the candidate."

    if step == "decide":
        return ""  # handled specially in render — duplicated above but keep fallback clean

    # Fallback
    return message


# ---------------------------------------------------------------------------
# Structured profile summary
# ---------------------------------------------------------------------------

def _render_profile_summary(evaluation: Evaluation | None) -> str | None:
    if not evaluation or not evaluation.structured_profile:
        return None
    p = evaluation.structured_profile
    if p.get("_parse_error"):
        return f"  {_c(_RED, 'Profile parsing failed — raw output not shown.')}"

    lines: list[str] = []
    lines.append(f"  {_c(_BOLD + _CYAN, 'STRUCTURED PROFILE SUMMARY')}")
    lines.append("")

    # Identity
    name = p.get("name", "—")
    headline = p.get("headline", "—")
    yoe = p.get("years_of_experience")
    role = p.get("current_role", "—")
    lines.append(f"  Name:       {_c(_BOLD, name)}")
    lines.append(f"  Headline:   {headline}")
    if yoe is not None:
        lines.append(f"  Experience: {yoe} years")
    lines.append(f"  Current:    {role}")
    lines.append("")

    # Work experience (compact)
    work = p.get("work_experience") or []
    if work:
        lines.append(f"  {_c(_BOLD, 'Work Experience')} ({len(work)} roles)")
        for w in work[:5]:
            company = w.get("company", "?")
            title = w.get("title", "?")
            dur = w.get("duration", "")
            dur_str = f" ({dur})" if dur else ""
            lines.append(f"    • {title} @ {company}{dur_str}")
        if len(work) > 5:
            lines.append(f"    … and {len(work) - 5} more")
        lines.append("")

    # Skills (one-liner per source)
    skills = p.get("technical_skills") or {}
    from_resume = skills.get("from_resume") or []
    from_gh_lang = skills.get("from_github_languages") or []
    from_gh_deps = skills.get("from_github_manifests") or []
    if from_resume or from_gh_lang or from_gh_deps:
        lines.append(f"  {_c(_BOLD, 'Technical Skills')}")
        if from_resume:
            lines.append(f"    Resume:   {', '.join(from_resume[:10])}")
        if from_gh_lang:
            lines.append(f"    GitHub:   {', '.join(from_gh_lang[:8])}")
        if from_gh_deps:
            lines.append(f"    Deps:     {', '.join(from_gh_deps[:8])}")
        lines.append("")

    # Shipped products (compact)
    shipped = p.get("shipped_products") or []
    if shipped:
        lines.append(f"  {_c(_BOLD, 'Shipped Products')} ({len(shipped)})")
        for sp in shipped[:4]:
            name_sp = sp.get("name", "?")
            ev_type = sp.get("evidence_type", "?")
            prod = "✓ live" if sp.get("in_production") else ""
            lines.append(f"    • {name_sp} [{ev_type}] {prod}")
        if len(shipped) > 4:
            lines.append(f"    … and {len(shipped) - 4} more")
        lines.append("")

    # GitHub signal (one-liner)
    gh = p.get("github_signal") or {}
    if gh and gh.get("active") is not None:
        repos = gh.get("total_public_repos", "?")
        langs = ", ".join((gh.get("primary_languages") or [])[:4])
        notable = gh.get("notable_repos") or []
        lines.append(f"  {_c(_BOLD, 'GitHub Signal')}")
        lines.append(f"    Active: {'yes' if gh['active'] else 'no'} | Repos: {repos} | Languages: {langs}")
        if notable:
            top = notable[0]
            lines.append(f"    Top repo: {top.get('name', '?')} — {top.get('what_it_does', '?')} ({top.get('stars', 0)}★)")
        lines.append("")

    # Portfolio signal (one-liner)
    pf = p.get("portfolio_signal") or {}
    if pf:
        real = "yes" if pf.get("has_real_projects") else "no"
        count = pf.get("project_count", "?")
        demos = pf.get("live_demo_count", 0)
        lines.append(f"  {_c(_BOLD, 'Portfolio Signal')}")
        lines.append(f"    Real projects: {real} | Count: {count} | Live demos: {demos}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Score breakdown table
# ---------------------------------------------------------------------------

def _render_score_table(evaluation: Evaluation | None, settings: AppSettings | None) -> str | None:
    if not evaluation or not evaluation.scores:
        return None
    scores = evaluation.scores
    rubric = (settings.rubric if settings else None) or []
    weight_map = {d["key"]: d["weight"] for d in rubric}

    lines = []
    lines.append(f"  {'Dimension':<24} {'Weight':>6}  {'Score':>5}")
    lines.append(f"  {'─' * 24} {'─' * 6}  {'─' * 5}")
    for key, data in scores.items():
        score_val = data.get("score", "?") if isinstance(data, dict) else data
        weight = weight_map.get(key, "?")
        display_key = key.replace("_", " ").title()
        lines.append(f"  {display_key:<24} {str(weight) + '%':>6}  {score_val:>5}")
    lines.append(f"  {'─' * 24} {'─' * 6}  {'─' * 5}")
    overall = evaluation.overall_score
    lines.append(f"  {_c(_BOLD, 'Overall (weighted)'):<35} {'' :>6}  {_c(_BOLD, str(round(overall, 1)) if overall else '?'):>5}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Decision rendering
# ---------------------------------------------------------------------------

def _render_decision(evaluation: Evaluation | None, settings: AppSettings | None) -> str | None:
    if not evaluation or not evaluation.tier:
        return None
    tier = evaluation.tier
    score = evaluation.overall_score
    thresholds = (settings.tier_thresholds if settings else None) or {}
    af = thresholds.get("auto_fail_ceiling", 48)
    ap = thresholds.get("auto_pass_floor", 50)

    tier_display = tier.upper().replace("_", " ")
    if tier == "auto_pass":
        color = _GREEN
        explanation = f"The candidate scored {score:.0f}, which is at or above the auto-pass threshold of {ap}. A congratulatory email was sent automatically."
    elif tier == "auto_fail":
        color = _RED
        explanation = f"The candidate scored {score:.0f}, which is below the auto-fail ceiling of {af}. A polite rejection email was sent automatically."
    elif tier == "manual_review":
        color = _YELLOW
        explanation = f"The candidate scored {score:.0f}, which falls between the auto-fail ceiling ({af}) and auto-pass floor ({ap}). The application is queued for a hiring manager to review."
    else:
        color = _WHITE
        explanation = f"Tier: {tier}. Score: {score}."

    reason = evaluation.decision_reason
    lines = [
        f"  Tier:   {_c(color + _BOLD, tier_display)}",
        f"  Score:  {score:.0f} / 100",
        "",
        f"  {explanation}",
    ]
    if reason:
        lines.append(f"\n  Reasoning: {reason}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step grouping
# ---------------------------------------------------------------------------

def _group_logs(logs: list[ProcessingLog]) -> list[dict]:
    """Group processing log rows into logical steps.

    A step is either:
    - A started+completed pair (same step name, sequential)
    - A started+failed pair
    - A standalone event (e.g. email_received, send_email, ingest)
    """
    groups: list[dict] = []
    i = 0
    while i < len(logs):
        log = logs[i]

        # If this is a "started" message, look for the matching completed/failed
        if log.message == "started":
            # Find the next log with the same step name that's completed or failed
            matched = None
            for j in range(i + 1, min(i + 10, len(logs))):
                nxt = logs[j]
                if nxt.step == log.step and nxt.message in ("completed",) or (
                    nxt.step == log.step and nxt.message.startswith("failed")
                ):
                    matched = j
                    break
            if matched is not None:
                completion = logs[matched]
                # Merge meta from both
                merged_meta = dict(log.meta or {})
                merged_meta.update(completion.meta or {})
                # Pick worst level across the range (started..completed + any warnings in between)
                worst_level = completion.level
                for k in range(i, matched + 1):
                    if logs[k].step == log.step and logs[k].level in ("warn", "warning", "error"):
                        if worst_level == "info":
                            worst_level = "warning" if logs[k].level in ("warn", "warning") else "error"
                        # Also absorb warning metadata
                        if logs[k].meta:
                            merged_meta.update(logs[k].meta)
                # If meta says outcome=candidate_error, treat as warning
                if merged_meta.get("outcome") == "candidate_error" and worst_level == "info":
                    worst_level = "warning"
                groups.append({
                    "step": log.step,
                    "level": worst_level,
                    "message": completion.message,
                    "meta": merged_meta,
                    "started_at": log.created_at,
                    "ended_at": completion.created_at,
                })
                i = matched + 1
                continue
            # No match found — treat started as standalone
            groups.append({
                "step": log.step,
                "level": log.level,
                "message": log.message,
                "meta": log.meta or {},
                "started_at": log.created_at,
                "ended_at": log.created_at,
            })
            i += 1
            continue

        # Standalone event (email_received, send_email, ingest, warnings)
        groups.append({
            "step": log.step,
            "level": log.level,
            "message": log.message,
            "meta": log.meta or {},
            "started_at": log.created_at,
            "ended_at": log.created_at,
        })
        i += 1

    return groups


# ---------------------------------------------------------------------------
# Dedup: skip retry noise
# ---------------------------------------------------------------------------

def _dedup_groups(groups: list[dict]) -> list[dict]:
    """Remove redundant retry attempts — keep only the last attempt per step.

    When a step fails and retries, we want to show the final outcome (success
    or last failure), not every intermediate crash.
    """
    # Walk backwards: for each step, keep the last completed or the very last entry.
    seen_completed: set[str] = set()
    result: list[dict] = []
    for g in reversed(groups):
        key = g["step"]
        # Always keep send_email (there can be multiple distinct sends)
        if key == "send_email":
            result.append(g)
            continue
        # Always keep email_received / ingest (can appear once per attempt but we want the final)
        if g["message"] in ("completed",) or not g["message"].startswith("failed"):
            if key not in seen_completed:
                seen_completed.add(key)
                result.append(g)
        else:
            # Failed entry — only keep if we haven't seen a completed for this step
            if key not in seen_completed:
                result.append(g)
    result.reverse()
    return result


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def _pause(auto: bool) -> None:
    if auto:
        return
    try:
        input(f"\n{_c(_DIM, '                            [press Enter to continue]')}")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def _render_header(candidate: Candidate) -> None:
    name = candidate.name or "Unknown"
    email = candidate.email
    cid = candidate.id
    print()
    print(_c(_BOLD + _CYAN, "=" * 54))
    print(_c(_BOLD + _CYAN, f"  Demo Replay: {name}"))
    print(_c(_CYAN, f"  {email}  |  Candidate #{cid}"))
    print(_c(_BOLD + _CYAN, "=" * 54))
    print()


def _render_email_detail(
    template_key: str,
    email_logs: list[EmailLog],
    email_log_cursor: list[int],
) -> str | None:
    """Render the decision-logic box + actual email content for a send_email step.

    email_log_cursor is a mutable [int] used to track which outbound EmailLog
    we've consumed so far (since there can be multiple send_email steps).
    """
    # Find the next outbound EmailLog matching this template
    outbound = [e for e in email_logs if e.direction == "out"]
    matched: EmailLog | None = None
    idx = email_log_cursor[0]
    for i in range(idx, len(outbound)):
        if outbound[i].template_used == template_key:
            matched = outbound[i]
            email_log_cursor[0] = i + 1
            break
    # If exact match failed, try the next unmatched outbound
    if matched is None and idx < len(outbound):
        matched = outbound[idx]
        email_log_cursor[0] = idx + 1

    lines: list[str] = []

    # --- Decision logic ---
    logic = _TEMPLATE_LOGIC.get(template_key)
    if logic:
        lines.append(f"  {_c(_BOLD + _CYAN, 'WHY THIS EMAIL?')}")
        lines.append("")
        for line in logic.split("\n"):
            lines.append(f"  {line}")
        lines.append("")

    # --- Actual email content ---
    if matched:
        subj = matched.subject or "(no subject)"
        body = matched.body_snippet or "(no body stored)"
        lines.append(f"  {_c(_BOLD + _CYAN, 'EMAIL SENT')}")
        lines.append("")
        lines.append(f"  {_c(_DIM, 'Subject:')} {subj}")
        lines.append(f"  {_c(_DIM, 'To:')}      {matched.sender or '?'} -> candidate")
        lines.append("")
        # Indent the body and wrap for readability
        for body_line in body.split("\n"):
            lines.append(f"  {_c(_DIM, '|')} {body_line}")
        lines.append("")

    return "\n".join(lines) if lines else None


def _render_step(
    num: int,
    group: dict,
    evaluation: Evaluation | None,
    settings: AppSettings | None,
    auto: bool,
    email_logs: list[EmailLog] | None = None,
    email_log_cursor: list[int] | None = None,
) -> None:
    step = group["step"]
    level = group["level"]
    message = group["message"]
    meta = group["meta"]

    display_name = _STEP_DISPLAY.get(step, step.replace("_", " ").title())

    # Special title for decide step
    if step == "decide" and evaluation and evaluation.tier:
        display_name = f"Decision: {evaluation.tier.upper().replace('_', ' ')}"

    icon = _level_icon(level)
    color = _level_color(level)

    print(_c(color, "  " + "─" * 52))
    print(f"  {_c(_BOLD, f'STEP {num}')}  {_c(_BOLD, display_name):<42} {icon}")
    print(_c(color, "  " + "─" * 52))
    print()

    # Duration
    dur = meta.get("duration_ms")
    if dur:
        print(f"  {_c(_DIM, f'Duration: {dur / 1000:.1f}s')}")
        print()

    # Narration
    narration = _narrate(step, message, meta, level)
    if narration:
        for line in narration.split("\n"):
            print(f"  {line}")
        print()

    # Structured profile summary (only for structure_profile step)
    if step == "structure_profile" and message == "completed":
        profile_summary = _render_profile_summary(evaluation)
        if profile_summary:
            print(profile_summary)

    # Score table (only for score step)
    if step == "score" and message == "completed":
        table = _render_score_table(evaluation, settings)
        if table:
            print(table)
            print()

    # Decision details (only for decide step)
    if step == "decide":
        decision = _render_decision(evaluation, settings)
        if decision:
            print(decision)
            print()

    # Email detail: decision logic + actual email content (only for send_email steps)
    if step == "send_email" and email_logs is not None and email_log_cursor is not None:
        template_key = message.replace("sent ", "").strip() if message.startswith("sent") else message
        detail = _render_email_detail(template_key, email_logs, email_log_cursor)
        if detail:
            print(detail)

    _pause(auto)


def _render_summary(
    candidate: Candidate,
    evaluation: Evaluation | None,
    groups: list[dict],
    email_logs: list[EmailLog],
) -> None:
    completed = sum(1 for g in groups if g["level"] != "error")
    failed = sum(1 for g in groups if g["level"] == "error")
    outbound = [e for e in email_logs if e.direction == "out"]
    templates = [e.template_used or "unknown" for e in outbound]

    # Total wall time
    if groups:
        first = groups[0]["started_at"]
        last = groups[-1]["ended_at"]
        if first and last:
            total_s = (last - first).total_seconds()
        else:
            total_s = 0
    else:
        total_s = 0

    print()
    print(_c(_BOLD + _CYAN, "  " + "=" * 52))
    print(_c(_BOLD + _CYAN, "  SUMMARY"))
    print(_c(_BOLD + _CYAN, "  " + "=" * 52))
    print()
    print(f"  Candidate:    {_c(_BOLD, candidate.name or 'Unknown')}")
    print(f"  Email:        {candidate.email}")
    print(f"  Final status: {_c(_BOLD, candidate.status)}")
    if evaluation and evaluation.overall_score is not None:
        print(f"  Score:        {evaluation.overall_score:.0f} / 100")
        print(f"  Tier:         {evaluation.tier or '—'}")
    if candidate.missing_items:
        print(f"  Missing:      {', '.join(candidate.missing_items)}")
    print(f"  Steps:        {completed} completed, {failed} failed")
    print(f"  Total time:   {total_s:.1f}s")
    if templates:
        print(f"  Emails sent:  {len(templates)} ({', '.join(templates)})")
    else:
        print(f"  Emails sent:  0")
    print()
    print(_c(_BOLD + _CYAN, "  " + "=" * 52))
    print()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_candidate_by_email(db: Session, email: str) -> Candidate | None:
    return db.query(Candidate).filter(Candidate.email == email).first()


def _load_candidate_by_id(db: Session, cid: int) -> Candidate | None:
    return db.get(Candidate, cid)


def _load_latest(db: Session) -> Candidate | None:
    return db.query(Candidate).order_by(Candidate.created_at.desc()).first()


def _load_logs(db: Session, candidate_id: int) -> list[ProcessingLog]:
    return (
        db.query(ProcessingLog)
        .filter(ProcessingLog.candidate_id == candidate_id)
        .order_by(ProcessingLog.created_at)
        .all()
    )


def _load_email_logs(db: Session, candidate_id: int) -> list[EmailLog]:
    return (
        db.query(EmailLog)
        .filter(EmailLog.candidate_id == candidate_id)
        .order_by(EmailLog.created_at)
        .all()
    )


def _load_evaluation(db: Session, candidate_id: int) -> Evaluation | None:
    return (
        db.query(Evaluation)
        .filter(Evaluation.candidate_id == candidate_id, Evaluation.superseded == False)
        .order_by(Evaluation.created_at.desc())
        .first()
    )


def _load_settings(db: Session) -> AppSettings | None:
    return db.get(AppSettings, 1)


# ---------------------------------------------------------------------------
# Recent candidates
# ---------------------------------------------------------------------------

def _ago(dt: datetime) -> str:
    if dt.tzinfo is None:
        now = datetime.now()
    else:
        now = datetime.now(timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _show_recent(db: Session, limit: int = 20) -> None:
    candidates = (
        db.query(Candidate)
        .order_by(Candidate.created_at.desc())
        .limit(limit)
        .all()
    )
    if not candidates:
        print("  No candidates found.")
        return

    print()
    print(_c(_BOLD, "  Recent candidates:"))
    print()
    print(f"  {'#ID':<6} {'Email':<40} {'Status':<16} {'When':<12}")
    print(f"  {'─' * 5} {'─' * 39} {'─' * 15} {'─' * 11}")
    for c in candidates:
        when = _ago(c.created_at) if c.created_at else "?"
        print(f"  {c.id:<6} {c.email:<40} {c.status:<16} {when:<12}")
    print()
    print(f"  Replay one:  python -m tools.demo_replay --id <ID>")
    print()


# ---------------------------------------------------------------------------
# Also search by pre-candidate logs (emails that didn't become candidates)
# ---------------------------------------------------------------------------

def _find_candidate_by_log_search(db: Session, search: str) -> Candidate | None:
    """Fuzzy search: try email contains, then name contains."""
    cand = db.query(Candidate).filter(Candidate.email.ilike(f"%{search}%")).first()
    if cand:
        return cand
    cand = db.query(Candidate).filter(Candidate.name.ilike(f"%{search}%")).first()
    return cand


# ---------------------------------------------------------------------------
# Main replay
# ---------------------------------------------------------------------------

def replay(db: Session, candidate: Candidate, auto: bool = False) -> None:
    logs = _load_logs(db, candidate.id)
    if not logs:
        print(f"\n  No processing logs found for candidate #{candidate.id}.\n")
        return

    evaluation = _load_evaluation(db, candidate.id)
    email_logs = _load_email_logs(db, candidate.id)
    settings = _load_settings(db)

    groups = _group_logs(logs)
    groups = _dedup_groups(groups)

    _render_header(candidate)
    _pause(auto)

    email_log_cursor = [0]  # mutable counter to track consumed outbound logs
    for i, group in enumerate(groups, 1):
        _render_step(i, group, evaluation, settings, auto, email_logs, email_log_cursor)

    _render_summary(candidate, evaluation, groups, email_logs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay a candidate's processing timeline for leadership demos."
    )
    parser.add_argument("search", nargs="?", help="Candidate email address (or partial match)")
    parser.add_argument("--id", type=int, help="Candidate ID")
    parser.add_argument("--recent", action="store_true", help="List recent candidates")
    parser.add_argument("--latest", action="store_true", help="Replay the most recent candidate")
    parser.add_argument("--auto", action="store_true", help="Auto-advance (no pausing)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.recent:
            _show_recent(db)
            return 0

        candidate: Candidate | None = None

        if args.id:
            candidate = _load_candidate_by_id(db, args.id)
            if not candidate:
                print(f"\n  No candidate found with ID {args.id}.\n")
                return 1
        elif args.latest:
            candidate = _load_latest(db)
            if not candidate:
                print("\n  No candidates in the database.\n")
                return 1
        elif args.search:
            # Try exact email first, then fuzzy
            candidate = _load_candidate_by_email(db, args.search)
            if not candidate:
                candidate = _find_candidate_by_log_search(db, args.search)
            if not candidate:
                print(f"\n  No candidate found matching '{args.search}'.")
                print(f"  Try: python -m tools.demo_replay --recent\n")
                return 1
        else:
            parser.print_help()
            return 1

        replay(db, candidate, auto=args.auto)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
