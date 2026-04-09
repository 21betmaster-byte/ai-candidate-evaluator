"""Trace the parser pipeline against a hardcoded test email + local PDF.

Skips LLM-dependent stages (classify, structure, score) — those require network +
ANTHROPIC_API_KEY. Runs the deterministic parsers and prints a processing-log
style trace.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.gmail.client import Attachment  # noqa: E402
from app.pipeline.extract import classify_urls, find_urls  # noqa: E402
from app.pipeline.github import GitHubCandidateError, GitHubInfraError, fetch_github  # noqa: E402
from app.pipeline.portfolio import PortfolioCandidateError, PortfolioInfraError, fetch_portfolio  # noqa: E402
from app.pipeline.resume import parse_resume  # noqa: E402

PDF_PATH = Path("/Users/shivamdoshi/Downloads/Shivam Doshi_Resume_Mar'26.pdf")

EMAIL = {
    "subject": "Applying for the Product builder role",
    "sender": "shivam@example.com",
    "body_text": (
        "Thrilled to apply for the builder residency-\n"
        "Please find attached my resume.\n\n"
        "Here is my portfolio link- https://shivam-doshi-portfolio.vercel.app/\n"
        "Here is my github link- https://github.com/21betmaster-byte\n"
    ),
}


def log(step: str, level: str, msg: str, meta=None):
    print(f"[{level.upper():5}] {step:24} {msg}")
    if meta:
        print(json.dumps(meta, indent=2, default=str))


def main():
    print("=" * 70)
    print("STAGE 1: Email body URL extraction")
    print("=" * 70)
    body_urls = find_urls(EMAIL["body_text"])
    log("extract_urls_body", "info", f"found {len(body_urls)} urls", {"urls": body_urls})
    gh, port, li = classify_urls(body_urls)
    log("classify_urls_body", "info", "classified", {"github": gh, "portfolio": port, "linkedin": li})

    print()
    print("=" * 70)
    print("STAGE 2: Resume PDF parsing")
    print("=" * 70)
    pdf_bytes = PDF_PATH.read_bytes()
    att = Attachment(filename=PDF_PATH.name, mime_type="application/pdf", data=pdf_bytes)
    parsed = parse_resume([att])
    log(
        "parse_resume",
        "info",
        f"resume_present={parsed.resume_present} chars={len(parsed.text)} urls={len(parsed.urls)}",
        {
            "filename": parsed.selected_filename,
            "first_500_chars": parsed.text[:500],
            "urls_in_resume": parsed.urls,
        },
    )

    # Combined URL set (body + resume)
    all_urls = list(dict.fromkeys(body_urls + parsed.urls))
    gh2, port2, li2 = classify_urls(all_urls)
    log("classify_urls_combined", "info", "after merging body+resume", {"github": gh2, "portfolio": port2, "linkedin": li2})

    print()
    print("=" * 70)
    print("STAGE 3: GitHub fetch")
    print("=" * 70)
    try:
        gh_data = fetch_github(gh2)
        log(
            "fetch_github",
            "info",
            f"@{gh_data.username} repos={gh_data.public_repos} followers={gh_data.followers}",
            {
                "languages_bytes": gh_data.languages,
                "recent_repos_pushed_6mo": gh_data.recent_repos_pushed_6mo,
                "recent_commits_90d": gh_data.recent_commits_90d,
                "top_repos": gh_data.top_repos,
            },
        )
    except GitHubCandidateError as e:
        log("fetch_github", "error", f"candidate-error: {e}")
    except GitHubInfraError as e:
        log("fetch_github", "error", f"infra-error: {e}")

    print()
    print("=" * 70)
    print("STAGE 4: Portfolio fetch")
    print("=" * 70)
    try:
        port_data = fetch_portfolio(port2)
        log(
            "fetch_portfolio",
            "info",
            f"title={port_data.title!r} links={len(port_data.project_links)}",
            {
                "final_url": port_data.final_url,
                "discovered_github_url": port_data.discovered_github_url,
                "discovered_resume_url": port_data.discovered_resume_url,
                "discovered_resume_downloaded": port_data.discovered_resume_bytes is not None,
                "text_snippet_first_600": port_data.text_snippet[:600],
                "first_10_links": port_data.project_links[:10],
            },
        )
    except PortfolioCandidateError as e:
        log("fetch_portfolio", "error", f"candidate-error: {e}")
    except PortfolioInfraError as e:
        log("fetch_portfolio", "error", f"infra-error: {e}")

    print()
    print("=" * 70)
    print("STAGE 5: Classifier (skipped — needs ANTHROPIC_API_KEY)")
    print("=" * 70)
    print("Heuristic check: subject doesn't trigger auto-reply, body non-empty → would call Sonnet.")
    print("Expected category: 'application' (mentions applying, attaches resume, github+portfolio links).")


if __name__ == "__main__":
    main()
