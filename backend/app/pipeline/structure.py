"""Sonnet step: turn raw resume text + GitHub data + portfolio data into a
structured CandidateProfile JSON. Cheaper/faster than Opus; Opus consumes this.

Design notes (see conversation 2026-04):
  - Extraction only, no evaluation. Opus is the judge.
  - No URLs in either the input or the output: URLs are noise for scoring and
    bloat the token count. We strip them from github/portfolio payloads before
    serializing, and we do not ask Sonnet to emit any in its schema.
  - `has_live_demos`, `has_downloadable_resume`, and `live_demo_count` are
    computed in Python, not by the LLM, so they are deterministic.
  - Called with temperature=0 — extraction should not drift run-to-run.
"""
from __future__ import annotations

import json
from urllib.parse import urlparse

from app.llm import call_sonnet, parse_json_block, LLMResult

STRUCTURE_SYSTEM = """You are a hiring data extractor. You will be given three inputs:
1. Raw text from a candidate's resume
2. JSON describing their GitHub profile
3. JSON describing their portfolio page

Your job is to produce a structured candidate profile. A separate evaluator model will score this against a rubric — your job is extraction, not evaluation. Do not assess quality, fit, or strength. Do not infer what is not stated.

RULES:
- Omit any field you cannot populate from the provided inputs. Do not guess.
- Never invent metrics, products, skills, or claims not present in the source material.
- If an input is missing (e.g., no GitHub data provided), set the corresponding top-level field to null.
- Extract ownership language exactly as the candidate used it. Do not upgrade "we launched" to "I built" or downgrade "I built" to "contributed to."
- For duration fields, use exactly what the source says. Do not calculate or round.
- If a shipped product is mentioned in multiple sources (resume + GitHub + portfolio), let it be present in all the sources.
- Do not include URLs anywhere in your output. Evidence fields should be text references only (e.g. "resume: Pazcare role", "repo: melon-expense-tracker", "portfolio: Projects section").
- `headline` must be a direct quote from the resume summary section or the portfolio title. Do not rephrase.
- `current_role`: if the candidate has no explicit current role, write "no current role". Do not fabricate one.
- `technical_skills.from_resume` contains skills the candidate listed on their resume. `technical_skills.from_github_languages` contains languages detected in their GitHub repos. `technical_skills.from_github_manifests` contains frameworks/libraries extracted from repo dependency manifests. Do not compute overlap — the downstream evaluator handles that.

OUTPUT FORMAT — JSON only, no markdown fencing, no preamble:

{
  "name": "string",
  "headline": "direct quote from resume summary or portfolio title",
  "years_of_experience": number | null,
  "current_role": "string",
  "work_experience": [
    {
      "company": "string",
      "title": "string",
      "duration": "string (verbatim from source)",
      "highlights": ["verbatim or near-verbatim claims from resume/portfolio"]
    }
  ],
  "technical_skills": {
    "from_resume": ["skills listed on resume"],
    "from_github_languages": ["languages detected in GitHub repos"],
    "from_github_manifests": ["frameworks/libraries extracted from repo dependency manifests"]
  },
  "shipped_products": [
    {
      "name": "string",
      "description": "string",
      "evidence": "text reference only: 'resume: [role]' | 'repo: [repo_name]' | 'portfolio: [section]'",
      "evidence_type": "live_url | repo | screenshot | text_claim_only",
      "in_production": true | false | null,
      "stack_from_code": ["verified from repo manifest — empty array if no repo manifest"],
      "stack_source": "manifest | language | resume | portfolio | none"
    }
  ],
  "education": ["verbatim from source"],
  "github_signal": {
    "active": true | false,
    "primary_languages": ["from GitHub data, not resume"],
    "notable_repos": [
      {
        "name": "string",
        "what_it_does": "string",
        "stars": number,
        "last_pushed": "date if available, else null"
      }
    ],
    "activity_summary": "string — commit frequency, recency, contributor count",
    "total_public_repos": number | null
  },
  "portfolio_signal": {
    "has_real_projects": true | false,
    "project_count": number,
    "highlights": ["factual observations only — what is on the page"]
  }
}

Note: `has_live_demos`, `live_demo_count`, and `has_downloadable_resume` are
computed deterministically by the caller and injected into the final profile.
Do NOT emit those keys yourself — the caller will fill them in.

FINAL CHECK before outputting:
- Every metric or number in your output: can you point to the exact source line? If not, remove it.
- Every shipped product: did the candidate actually claim they built/shipped/launched/led it? If they only used it or worked at the company without ownership language, it is not a shipped product.
- No URLs anywhere in the output."""


# Hostnames that should not count as "live demos" when scanning portfolio link
# targets — they are social/communication channels, not product surfaces.
_SOCIAL_HOSTS = {
    "github.com",
    "www.github.com",
    "linkedin.com",
    "www.linkedin.com",
    "twitter.com",
    "www.twitter.com",
    "x.com",
    "www.x.com",
}


def _hostname(url: str) -> str | None:
    try:
        host = (urlparse(url).netloc or "").lower()
        return host or None
    except Exception:
        return None


def _is_own_host(link_host: str, portfolio_host: str | None) -> bool:
    if not portfolio_host:
        return False
    # exact match or subdomain of portfolio host
    return link_host == portfolio_host or link_host.endswith("." + portfolio_host)


def _compute_portfolio_flags(portfolio_data: dict) -> dict:
    """Derive has_live_demos / has_downloadable_resume / live_demo_count in Python.

    A live demo is a project link whose hostname is different from the
    portfolio's own domain AND which is not GitHub, LinkedIn, Twitter/X, or a
    mailto/tel link. Counted by unique hostname.
    """
    portfolio_host = _hostname(portfolio_data.get("final_url") or portfolio_data.get("url") or "")
    live_demo_hosts: set[str] = set()
    for link in portfolio_data.get("project_links") or []:
        if not isinstance(link, str):
            continue
        if link.startswith("mailto:") or link.startswith("tel:"):
            continue
        host = _hostname(link)
        if not host:
            continue
        if host in _SOCIAL_HOSTS:
            continue
        if _is_own_host(host, portfolio_host):
            continue
        live_demo_hosts.add(host)

    has_resume = bool(portfolio_data.get("discovered_resume_url"))
    return {
        "has_downloadable_resume": has_resume,
        "has_live_demos": len(live_demo_hosts) > 0,
        "live_demo_count": len(live_demo_hosts),
    }


def _strip_github_urls(github_data: dict | None) -> dict | None:
    """Remove URL fields from the GitHub payload before sending to the LLM."""
    if not github_data:
        return None
    cleaned = {k: v for k, v in github_data.items() if k != "profile_url"}
    top_repos = cleaned.get("top_repos") or []
    stripped_repos = []
    for repo in top_repos:
        if not isinstance(repo, dict):
            continue
        stripped_repos.append({k: v for k, v in repo.items() if k != "url"})
    cleaned["top_repos"] = stripped_repos
    return cleaned


def _sanitize_portfolio(portfolio_data: dict | None) -> dict | None:
    """Drop URLs from the portfolio payload; replace them with precomputed flags."""
    if not portfolio_data:
        return None
    flags = _compute_portfolio_flags(portfolio_data)
    # Order matters: small deterministic flags first, bulky text_snippet last.
    # The downstream JSON dump is hard-truncated, so the tail of text_snippet
    # is what gets chopped — never the flags.
    return {
        "title": portfolio_data.get("title"),
        "has_downloadable_resume": flags["has_downloadable_resume"],
        "has_live_demos": flags["has_live_demos"],
        "live_demo_count": flags["live_demo_count"],
        "text_snippet": portfolio_data.get("text_snippet"),
    }


def structure_profile(
    resume_text: str,
    github_data: dict | None,
    portfolio_data: dict | None,
) -> dict:
    sanitized_github = _strip_github_urls(github_data)
    sanitized_portfolio = _sanitize_portfolio(portfolio_data)

    # Truncation budgets (chars). Portfolio dict is ordered so deterministic
    # flags survive a tail-chop if the text_snippet blows past the budget.
    user = (
        "RESUME TEXT:\n"
        f"{resume_text[:12000] if resume_text else '(none)'}\n\n"
        "GITHUB DATA:\n"
        f"{json.dumps(sanitized_github or {}, indent=2)[:4000]}\n\n"
        "PORTFOLIO DATA:\n"
        f"{json.dumps(sanitized_portfolio or {}, indent=2)[:20000]}\n"
    )
    llm_result = call_sonnet(STRUCTURE_SYSTEM, user, max_tokens=2500, temperature=0)
    try:
        profile = parse_json_block(llm_result.text)
    except Exception:
        return {"_parse_error": True, "_raw": llm_result.text[:2000], "_llm_meta": llm_result.meta_dict()}

    # Single source of truth: the deterministic flags are injected here, not
    # echoed by Sonnet. Overrides anything the model might have hallucinated.
    portfolio_flags_overridden = False
    if portfolio_data:
        flags = _compute_portfolio_flags(portfolio_data)
        portfolio_signal = profile.get("portfolio_signal")
        if not isinstance(portfolio_signal, dict):
            portfolio_signal = {}
        portfolio_flags_overridden = (
            portfolio_signal.get("has_live_demos") != flags["has_live_demos"]
            or portfolio_signal.get("live_demo_count") != flags["live_demo_count"]
        )
        portfolio_signal["has_live_demos"] = flags["has_live_demos"]
        portfolio_signal["live_demo_count"] = flags["live_demo_count"]
        portfolio_signal["has_downloadable_resume"] = flags["has_downloadable_resume"]
        profile["portfolio_signal"] = portfolio_signal

    # Extraction stats for logging — which top-level fields were populated
    work_exp = profile.get("work_experience") or []
    shipped = profile.get("shipped_products") or []
    education = profile.get("education") or []
    profile["_llm_meta"] = llm_result.meta_dict()
    profile["_extraction_stats"] = {
        "has_name": bool(profile.get("name")),
        "has_headline": bool(profile.get("headline")),
        "years_of_experience": profile.get("years_of_experience"),
        "work_experience_count": len(work_exp),
        "shipped_products_count": len(shipped),
        "education_count": len(education),
        "has_github_signal": profile.get("github_signal") is not None,
        "has_portfolio_signal": profile.get("portfolio_signal") is not None,
        "portfolio_flags_overridden": portfolio_flags_overridden,
    }

    return profile
