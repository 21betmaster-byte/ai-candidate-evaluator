"""LLM-based email classifier.

Returns one of:
  application_complete    — has resume PDF + GitHub URL + portfolio URL
  application_incomplete  — looks like an application but missing items
  question                — asking about the role / company
  spam_sales              — pitch / sales / marketing
  auto_reply              — out-of-office / vacation auto-reply (DO NOT respond)
  gibberish               — empty/garbled/unreadable
  other                   — anything else (irrelevant)

This function does NOT decide what's missing — that's done deterministically by
the resume/url-extraction step. The classifier's only job is to route.
"""
from __future__ import annotations

from app.gmail.client import InboundEmail
from app.llm import call_sonnet, parse_json_block, LLMResult

CLASSIFY_SYSTEM = """You are an email triage assistant for a hiring inbox.

Classify each email into EXACTLY ONE category:

- application: the sender is applying for a role (mentions resume, applying, role, position, attaches a resume, includes links to GitHub/portfolio, etc.)
- application_needs_review: a RARE subset of application — the sender is applying AND the email contains specific, substantive context about their background that explains why one of the standard asks (resume / GitHub / portfolio) does not fit them, OR offers a meaningful alternative artifact. Examples: "I'm a PM, my work is in specs and launch metrics, not public repos", "I spent the last 5 years at a closed-source defense contractor and can't share code", "My portfolio is under NDA but here's a writeup". Vague excuses ("I don't have GitHub lol"), jokes, one-liners, or simple omissions are NOT this category — those are plain "application". Be conservative: when in doubt, return "application".
- question: the sender is asking about the role/company without applying
- spam_sales: marketing, sales pitch, vendor outreach, cold pitch
- auto_reply: an out-of-office or vacation auto-responder
- gibberish: empty, random characters, or completely unparseable
- other: none of the above

Output ONLY a JSON object: {"category": "...", "reason": "one short sentence", "question_text": "...", "review_reason": "...", "confidence": 0.0}

- If category is "question", populate question_text with what they asked. Otherwise leave it empty.
- If category is "application_needs_review", populate review_reason with a one-sentence summary of WHY this needs a human (e.g., "PM with no public code, offered case studies instead"), and set confidence (0..1) to how sure you are this is a substantive contextual application rather than a vague excuse. Otherwise leave review_reason empty and confidence 0."""


VALID_CATEGORIES = {"application", "application_needs_review", "question", "spam_sales", "auto_reply", "gibberish", "other"}


def classify_email(email: InboundEmail) -> dict:
    # Quick heuristic shortcuts to save tokens & latency
    subject_l = (email.subject or "").lower()
    body_l = (email.body_text or "").lower()
    if any(k in subject_l for k in ("out of office", "auto-reply", "automatic reply", "vacation")):
        return {"category": "auto_reply", "reason": "subject indicates auto-reply", "question_text": "", "heuristic_shortcut": "auto_reply_subject"}
    if not body_l.strip() and not email.attachments:
        return {"category": "gibberish", "reason": "empty body, no attachments", "question_text": "", "heuristic_shortcut": "empty_body"}

    user = (
        f"Subject: {email.subject}\n"
        f"From: {email.sender}\n"
        f"Has attachments: {len(email.attachments)} ({', '.join(a.filename for a in email.attachments) or 'none'})\n\n"
        f"Body:\n{(email.body_text or '')[:4000]}"
    )
    llm_result = call_sonnet(CLASSIFY_SYSTEM, user, max_tokens=400)
    try:
        data = parse_json_block(llm_result.text)
    except Exception:
        return {"category": "other", "reason": "classifier returned unparseable JSON", "question_text": "", "_llm_meta": llm_result.meta_dict(), "_parse_error": True}
    cat = data.get("category", "other")
    if cat not in VALID_CATEGORIES:
        cat = "other"
    try:
        confidence = float(data.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "category": cat,
        "reason": data.get("reason", "")[:500],
        "question_text": data.get("question_text", "")[:1000],
        "review_reason": (data.get("review_reason") or "")[:500],
        "confidence": max(0.0, min(1.0, confidence)),
        "_llm_meta": llm_result.meta_dict(),
    }
