"""URL extraction helpers shared across email body, resume PDF, and portfolio HTML."""
from __future__ import annotations

import re
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s)>\]\"'<]+", re.IGNORECASE)


def find_urls(text: str) -> list[str]:
    if not text:
        return []
    seen, out = set(), []
    for m in URL_RE.finditer(text):
        u = m.group(0).rstrip(".,;:)")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def is_github_profile(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    if "github.com" not in (p.netloc or "").lower():
        return False
    path = (p.path or "").strip("/")
    if not path:
        return False
    # Username only (no /repo/...) — accept; classifier permissive
    return True


def is_linkedin(url: str) -> bool:
    try:
        return "linkedin.com" in urlparse(url).netloc.lower()
    except Exception:
        return False


def looks_like_portfolio(url: str) -> bool:
    if is_github_profile(url):
        return False
    if is_linkedin(url):
        return False
    if any(x in url for x in ("mailto:", "tel:")):
        return False
    return True


def classify_urls(urls: list[str]) -> tuple[str | None, str | None, str | None]:
    """Return (github_url, portfolio_url, linkedin_url) — picks first match of each."""
    github = next((u for u in urls if is_github_profile(u)), None)
    linkedin = next((u for u in urls if is_linkedin(u)), None)
    portfolio = next((u for u in urls if looks_like_portfolio(u)), None)
    return github, portfolio, linkedin
