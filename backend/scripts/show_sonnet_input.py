"""Dump the EXACT system+user payloads that get sent to Sonnet for the test email.

Runs the deterministic parsers, then builds the same prompts classify.py and
structure.py would build — but prints them instead of calling the API.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.gmail.client import Attachment, InboundEmail  # noqa: E402
from app.pipeline.classify import CLASSIFY_SYSTEM  # noqa: E402
from app.pipeline.github import fetch_github  # noqa: E402
from app.pipeline.portfolio import fetch_portfolio  # noqa: E402
from app.pipeline.resume import parse_resume  # noqa: E402
from app.pipeline.structure import (  # noqa: E402
    STRUCTURE_SYSTEM,
    _sanitize_portfolio,
    _strip_github_urls,
)

PDF_PATH = Path("/Users/shivamdoshi/Downloads/Shivam Doshi_Resume_Mar'26.pdf")

BODY = (
    "Thrilled to apply for the builder residency-\n"
    "Please find attached my resume.\n\n"
    "Here is my portfolio link- https://shivam-doshi-portfolio.vercel.app/\n"
    "Here is my github link- https://github.com/21betmaster-byte\n"
)

att = Attachment(
    filename=PDF_PATH.name,
    mime_type="application/pdf",
    data=PDF_PATH.read_bytes(),
)

email = InboundEmail(
    message_id="test-msg-1",
    thread_id="test-thread-1",
    sender="Shivam Doshi <shivam@example.com>",
    sender_email="shivam@example.com",
    sender_name="Shivam Doshi",
    subject="Applying for the Product builder role",
    body_text=BODY,
    attachments=[att],
)

# ---------- CALL #1: classify_email ----------
classify_user = (
    f"Subject: {email.subject}\n"
    f"From: {email.sender}\n"
    f"Has attachments: {len(email.attachments)} ({', '.join(a.filename for a in email.attachments) or 'none'})\n\n"
    f"Body:\n{(email.body_text or '')[:4000]}"
)

print("#" * 78)
print("# SONNET CALL #1 — classify_email")
print("# model: claude-sonnet-4-6   max_tokens: 400")
print("#" * 78)
print("\n--- SYSTEM ---")
print(CLASSIFY_SYSTEM)
print("\n--- USER ---")
print(classify_user)
print("\n--- BYTES ---")
print(f"system={len(CLASSIFY_SYSTEM)} chars, user={len(classify_user)} chars")

# ---------- Run parsers to build structure input ----------
parsed = parse_resume([att])
gh = fetch_github("https://github.com/21betmaster-byte")
port = fetch_portfolio("https://shivam-doshi-portfolio.vercel.app/")

github_data_raw = {
    "username": gh.username,
    "profile_url": gh.profile_url,
    "public_repos": gh.public_repos,
    "followers": gh.followers,
    "languages": gh.languages,
    "recent_repos_pushed_6mo": gh.recent_repos_pushed_6mo,
    "recent_commits_90d": gh.recent_commits_90d,
    "top_repos": gh.top_repos,
}
portfolio_data_raw = {
    "url": port.url,
    "final_url": port.final_url,
    "title": port.title,
    "text_snippet": port.text_snippet,
    "discovered_github_url": port.discovered_github_url,
    "discovered_resume_url": port.discovered_resume_url,
    "project_links": port.project_links,
}

# Apply the same sanitization structure_profile() would apply before calling Sonnet.
github_data = _strip_github_urls(github_data_raw)
portfolio_data = _sanitize_portfolio(portfolio_data_raw)

# ---------- CALL #2: structure_profile ----------
structure_user = (
    "RESUME TEXT:\n"
    f"{parsed.text[:12000] if parsed.text else '(none)'}\n\n"
    "GITHUB DATA:\n"
    f"{json.dumps(github_data or {}, indent=2)[:4000]}\n\n"
    "PORTFOLIO DATA:\n"
    f"{json.dumps(portfolio_data or {}, indent=2)[:20000]}\n"
)

print("\n\n" + "#" * 78)
print("# SONNET CALL #2 — structure_profile")
print("# model: claude-sonnet-4-6   max_tokens: 2500")
print("#" * 78)
print("\n--- SYSTEM ---")
print(STRUCTURE_SYSTEM)
print("\n--- USER ---")
print(structure_user)
print("\n--- BYTES ---")
print(f"system={len(STRUCTURE_SYSTEM)} chars, user={len(structure_user)} chars")
