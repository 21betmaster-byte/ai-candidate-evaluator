"""Unit tests for the parsers and helpers added during the 2026-04 hardening pass.

Covered:
  - GitHub manifest parsers (package.json, pyproject, requirements.txt, Cargo, go.mod)
  - Portfolio flag computation (_compute_portfolio_flags)
  - URL stripping (_strip_github_urls)
  - Portfolio sanitization + dict field ordering (_sanitize_portfolio)
  - PDF link annotation extraction (extract_pdf_link_uris)

All tests are offline — no network calls, no LLM calls.
"""
from __future__ import annotations

import fitz

from app.pipeline.github import (
    _parse_cargo_toml,
    _parse_go_mod,
    _parse_package_json,
    _parse_pyproject,
    _parse_requirements_txt,
)
from app.pipeline.resume import extract_pdf_link_uris
from app.pipeline.structure import (
    _compute_portfolio_flags,
    _sanitize_portfolio,
    _strip_github_urls,
)


# ---------------------------- manifest parsers ----------------------------


def test_parse_package_json_merges_all_dep_sections():
    text = """
    {
      "name": "melon",
      "dependencies": {"next": "15.0.0", "react": "19.0.0"},
      "devDependencies": {"@playwright/test": "1.58.0"},
      "peerDependencies": {"react-dom": "19.0.0"}
    }
    """
    deps = _parse_package_json(text)
    assert set(deps) == {"next", "react", "@playwright/test", "react-dom"}


def test_parse_package_json_handles_garbage():
    assert _parse_package_json("not json") == []
    assert _parse_package_json("{}") == []


def test_parse_pyproject_pep621_and_poetry():
    pep621 = """
    [project]
    name = "foo"
    dependencies = ["fastapi>=0.115", "httpx==0.27.0", "pydantic[email]>=2.9"]
    """
    assert _parse_pyproject(pep621) == ["fastapi", "httpx", "pydantic"]

    poetry = """
    [tool.poetry.dependencies]
    python = "^3.11"
    fastapi = "^0.115"
    httpx = "^0.27"
    """
    assert _parse_pyproject(poetry) == ["fastapi", "httpx"]


def test_parse_requirements_txt_strips_versions_and_comments():
    text = """
    # main deps
    fastapi>=0.115
    httpx==0.27.0
    pydantic[email]>=2.9 ; python_version >= "3.11"
    -r other.txt
    """
    assert _parse_requirements_txt(text) == ["fastapi", "httpx", "pydantic"]


def test_parse_cargo_toml():
    text = """
    [package]
    name = "foo"

    [dependencies]
    serde = "1.0"
    tokio = { version = "1", features = ["full"] }
    """
    assert set(_parse_cargo_toml(text)) == {"serde", "tokio"}


def test_parse_go_mod_block_and_single_require():
    text = """
    module example.com/foo

    go 1.22

    require github.com/gin-gonic/gin v1.9.1

    require (
        github.com/stretchr/testify v1.8.4
        golang.org/x/sync v0.5.0
    )
    """
    deps = _parse_go_mod(text)
    assert deps == [
        "github.com/gin-gonic/gin",
        "github.com/stretchr/testify",
        "golang.org/x/sync",
    ]


# ---------------------------- portfolio flags ----------------------------


def test_live_demos_excludes_own_domain_and_social_hosts():
    portfolio = {
        "final_url": "https://shivam-doshi-portfolio.vercel.app/",
        "project_links": [
            "https://shivam-doshi-portfolio.vercel.app/Resume.pdf",  # own
            "https://guileless-phoenix-a58c38.netlify.app/",  # demo
            "https://expensetracker-kappa-six.vercel.app/",  # demo
            "https://github.com/21betmaster-byte",  # social
            "https://www.linkedin.com/in/shivamdoshi/",  # social
            "https://x.com/shivamdoshi",  # social
            "mailto:doshishivam@gmail.com",
            "tel:+918884400789",
        ],
        "discovered_resume_url": "https://shivam-doshi-portfolio.vercel.app/Resume.pdf",
    }
    flags = _compute_portfolio_flags(portfolio)
    assert flags == {
        "has_downloadable_resume": True,
        "has_live_demos": True,
        "live_demo_count": 2,
    }


def test_live_demos_counts_unique_hostnames_only():
    portfolio = {
        "final_url": "https://me.dev/",
        "project_links": [
            "https://demo.com/a",
            "https://demo.com/b",
            "https://demo.com/c",
            "https://other.io/",
        ],
    }
    flags = _compute_portfolio_flags(portfolio)
    assert flags["live_demo_count"] == 2  # demo.com + other.io


def test_live_demos_excludes_subdomains_of_portfolio():
    portfolio = {
        "final_url": "https://me.dev/",
        "project_links": [
            "https://blog.me.dev/post",  # own subdomain → excluded
            "https://projects.me.dev/x",  # own subdomain → excluded
            "https://external.com/",  # real demo
        ],
    }
    assert _compute_portfolio_flags(portfolio)["live_demo_count"] == 1


def test_live_demos_with_no_resume():
    assert _compute_portfolio_flags({"final_url": "https://me.dev/", "project_links": []}) == {
        "has_downloadable_resume": False,
        "has_live_demos": False,
        "live_demo_count": 0,
    }


# ---------------------------- URL stripping ----------------------------


def test_strip_github_urls_removes_profile_and_repo_urls():
    gh = {
        "username": "alice",
        "profile_url": "https://github.com/alice",
        "public_repos": 3,
        "top_repos": [
            {"name": "a", "url": "https://github.com/alice/a", "stars": 1},
            {"name": "b", "url": "https://github.com/alice/b", "stars": 0},
        ],
    }
    cleaned = _strip_github_urls(gh)
    assert "profile_url" not in cleaned
    assert cleaned["username"] == "alice"
    for repo in cleaned["top_repos"]:
        assert "url" not in repo
        assert "name" in repo  # other fields preserved


def test_strip_github_urls_none_passthrough():
    assert _strip_github_urls(None) is None


# ---------------------------- portfolio sanitization ----------------------------


def test_sanitize_portfolio_field_ordering_survives_truncation():
    """Regression test: the deterministic flags must appear BEFORE text_snippet
    in the serialized dict, so tail-chopping during JSON truncation can never
    strip them."""
    portfolio = {
        "final_url": "https://me.dev/",
        "title": "My Portfolio",
        "text_snippet": "x" * 5000,
        "project_links": ["https://demo.com/"],
        "discovered_resume_url": "https://me.dev/resume.pdf",
    }
    sanitized = _sanitize_portfolio(portfolio)
    keys = list(sanitized.keys())
    assert keys.index("has_live_demos") < keys.index("text_snippet")
    assert keys.index("has_downloadable_resume") < keys.index("text_snippet")
    assert keys.index("live_demo_count") < keys.index("text_snippet")
    assert keys.index("title") < keys.index("text_snippet")


def test_sanitize_portfolio_computes_flags_correctly():
    sanitized = _sanitize_portfolio({
        "final_url": "https://me.dev/",
        "title": "Me",
        "text_snippet": "hi",
        "project_links": ["https://demo.com/", "https://other.io/"],
        "discovered_resume_url": None,
    })
    assert sanitized["has_live_demos"] is True
    assert sanitized["live_demo_count"] == 2
    assert sanitized["has_downloadable_resume"] is False


def test_sanitize_portfolio_none_passthrough():
    assert _sanitize_portfolio(None) is None


# ---------------------------- PDF link annotation extraction ----------------------------


def test_extract_pdf_link_uris_captures_annotations():
    """Create a tiny PDF in memory with a visible 'LinkedIn' word that
    hyperlinks to linkedin.com. Plain text extraction would miss the URL;
    our annotation-aware extractor should find it.
    """
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    text_rect = fitz.Rect(50, 50, 200, 80)
    page.insert_textbox(text_rect, "LinkedIn", fontsize=14)
    # Attach a link annotation covering the same rectangle.
    page.insert_link({
        "kind": fitz.LINK_URI,
        "from": text_rect,
        "uri": "https://www.linkedin.com/in/example/",
    })
    pdf_bytes = doc.tobytes()
    doc.close()

    uris = extract_pdf_link_uris(pdf_bytes)
    assert "https://www.linkedin.com/in/example/" in uris


def test_extract_pdf_link_uris_empty_on_no_data():
    assert extract_pdf_link_uris(b"") == []
