"""Portfolio fetcher + secondary source discovery.

PRD §6 Test 13–15: before flagging incomplete, look for GitHub link AND a
downloadable resume PDF on the portfolio page.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.pipeline.extract import is_github_profile, is_linkedin

# If the static HTML scrape yields fewer than this many anchor tags, assume the
# page is a JS-rendered SPA shell and fall back to a headless browser render.
SPA_LINK_THRESHOLD = 8
SPA_TEXT_THRESHOLD = 800  # chars of visible text


class PortfolioCandidateError(Exception):
    """Permanent issue with the URL itself (e.g. it's just LinkedIn)."""


class PortfolioInfraError(Exception):
    """5xx / timeout / network — retry."""


@dataclass
class PortfolioData:
    url: str
    final_url: str
    title: str | None
    text_snippet: str
    discovered_github_url: str | None
    discovered_resume_url: str | None
    discovered_resume_bytes: bytes | None  # if we downloaded one
    project_links: list[str]


def _render_with_playwright(url: str) -> tuple[str, str]:
    """Render a JS-heavy page in headless Chromium. Returns (html, final_url)."""
    from playwright.sync_api import sync_playwright  # local import: heavy dep

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(user_agent="ai-candidate-evaluator/1.0")
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
            final_url = page.url
        finally:
            browser.close()
    return html, final_url


def fetch_portfolio(url: str) -> PortfolioData:
    if is_linkedin(url):
        raise PortfolioCandidateError("portfolio link is actually a LinkedIn profile")

    timeout = httpx.Timeout(15.0)
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": "ai-candidate-evaluator/1.0"}) as client:
            resp = client.get(url)
            if resp.status_code == 404:
                raise PortfolioCandidateError(f"portfolio 404: {url}")
            if resp.status_code >= 500:
                raise PortfolioInfraError(f"portfolio 5xx: {resp.status_code}")
            if resp.status_code >= 400:
                raise PortfolioCandidateError(f"portfolio {resp.status_code}: {url}")
            html = resp.text
            final_url = str(resp.url)

            soup = BeautifulSoup(html, "html.parser")
            anchor_count = len(soup.find_all("a", href=True))
            visible_text_len = len(soup.get_text(" ", strip=True))
            if anchor_count < SPA_LINK_THRESHOLD or visible_text_len < SPA_TEXT_THRESHOLD:
                # Likely a JS-rendered SPA shell — re-render with Playwright.
                try:
                    html, final_url = _render_with_playwright(url)
                    soup = BeautifulSoup(html, "html.parser")
                except Exception:
                    # Fall through with the static HTML we already have.
                    pass
            title = (soup.title.string if soup.title and soup.title.string else None) or None
            text = soup.get_text(" ", strip=True)
            text_snippet = text[:20000]

            discovered_github = None
            discovered_resume_url = None
            project_links: list[str] = []

            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith("#"):
                    continue
                absolute = urljoin(final_url, href)
                if not discovered_github and is_github_profile(absolute):
                    discovered_github = absolute
                if not discovered_resume_url and absolute.lower().endswith(".pdf"):
                    label = (a.get_text(" ", strip=True) or "").lower()
                    if "resume" in label or "cv" in label or "resume" in absolute.lower() or "cv" in absolute.lower():
                        discovered_resume_url = absolute
                project_links.append(absolute)

            # If we found a resume URL, try to download it.
            discovered_resume_bytes: bytes | None = None
            if discovered_resume_url:
                try:
                    rresp = client.get(discovered_resume_url)
                    if rresp.status_code == 200 and len(rresp.content) < 10 * 1024 * 1024:
                        discovered_resume_bytes = rresp.content
                except Exception:
                    pass

            return PortfolioData(
                url=url,
                final_url=final_url,
                title=title,
                text_snippet=text_snippet,
                discovered_github_url=discovered_github,
                discovered_resume_url=discovered_resume_url,
                discovered_resume_bytes=discovered_resume_bytes,
                project_links=project_links[:30],
            )
    except httpx.ConnectError as e:
        # DNS resolution failure or TCP refused — the URL itself is broken
        # from the public internet, which is a candidate-side problem. Don't
        # burn retries; surface it immediately so the candidate can fix it.
        raise PortfolioCandidateError(f"portfolio unreachable: {e}")
    except (httpx.TimeoutException, httpx.NetworkError) as e:
        raise PortfolioInfraError(str(e))
