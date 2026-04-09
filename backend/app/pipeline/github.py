"""GitHub profile fetcher.

Distinguishes candidate-side issues (404, private profile) from infrastructure
issues (5xx, network errors). PRD §6: only the former should email the candidate;
the latter triggers retry-with-backoff via the queue.
"""
from __future__ import annotations

import base64
import json
import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from app.config import get_settings


class GitHubCandidateError(Exception):
    """404 / private / invalid URL — surface to candidate."""


class GitHubInfraError(Exception):
    """5xx, timeout, network — retry."""


@dataclass
class GitHubData:
    username: str
    profile_url: str
    public_repos: int
    followers: int
    languages: dict[str, int]  # language -> bytes (aggregated across top repos)
    recent_repos_pushed_6mo: int  # # of repos with a push in the last 6 months
    recent_commits_90d: int  # actual commits authored in the last ~90 days
    top_repos: list[dict]  # name, stars, forks, lang, description, url


def _username_from_url(url: str) -> str | None:
    try:
        p = urlparse(url)
        if "github.com" not in (p.netloc or "").lower():
            return None
        path = (p.path or "").strip("/").split("/")
        if not path or not path[0]:
            return None
        return path[0]
    except Exception:
        return None


def _headers() -> dict:
    s = get_settings()
    h = {"Accept": "application/vnd.github+json", "User-Agent": "ai-candidate-evaluator"}
    if s.github_token:
        h["Authorization"] = f"Bearer {s.github_token}"
    return h


# ---------------- Manifest fetching (per top repo) ----------------
#
# Strategy (user-approved "Alternative 2"):
#   1. List root contents of the repo with a single GET /contents/ call.
#   2. Pick the first manifest in a priority order we actually support.
#   3. Fetch that single manifest via GET /contents/{filename} and parse it
#      to a list of dependency names (no versions).
#
# Two API calls per top repo, capped at the top-10 sort slice → 20 extra calls
# per candidate in the worst case. Well within the authenticated rate limit
# and cheap relative to what we already spend on /commits + /languages.

_MANIFEST_PRIORITY: list[str] = [
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
]


def _strip_py_version_spec(spec: str) -> str:
    return re.split(r"[<>=!~\[;\s]", spec, maxsplit=1)[0].strip()


def _parse_package_json(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except Exception:
        return []
    deps: list[str] = []
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(key) or {}
        if isinstance(section, dict):
            deps.extend(section.keys())
    return deps


def _parse_pyproject(text: str) -> list[str]:
    try:
        data = tomllib.loads(text)
    except Exception:
        return []
    deps: list[str] = []
    # PEP 621
    project = data.get("project") or {}
    for entry in project.get("dependencies") or []:
        if isinstance(entry, str):
            name = _strip_py_version_spec(entry)
            if name:
                deps.append(name)
    # Poetry
    poetry = (data.get("tool") or {}).get("poetry") or {}
    for name in (poetry.get("dependencies") or {}).keys():
        if name.lower() != "python":
            deps.append(name)
    return deps


def _parse_requirements_txt(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name = _strip_py_version_spec(line)
        if name:
            out.append(name)
    return out


def _parse_cargo_toml(text: str) -> list[str]:
    try:
        data = tomllib.loads(text)
    except Exception:
        return []
    deps_section = data.get("dependencies") or {}
    return list(deps_section.keys()) if isinstance(deps_section, dict) else []


def _parse_go_mod(text: str) -> list[str]:
    deps: list[str] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block:
            if line == ")":
                in_block = False
                continue
            parts = line.split()
            if parts:
                deps.append(parts[0])
            continue
        if line.startswith("require "):
            parts = line[len("require "):].split()
            if parts:
                deps.append(parts[0])
    return deps


_MANIFEST_PARSERS: dict[str, "callable"] = {
    "package.json": _parse_package_json,
    "pyproject.toml": _parse_pyproject,
    "requirements.txt": _parse_requirements_txt,
    "Cargo.toml": _parse_cargo_toml,
    "go.mod": _parse_go_mod,
}


def _fetch_repo_dependencies(
    client: "httpx.Client",
    base: str,
    owner: str,
    repo_name: str,
) -> tuple[str | None, list[str]]:
    """Return (manifest_type, [dep_names]) for the first matching manifest at repo root.

    Returns (None, []) if the repo has no manifest we recognize, is empty, or
    the fetch fails.
    """
    try:
        listing = client.get(f"{base}/repos/{owner}/{repo_name}/contents/")
        if listing.status_code != 200:
            return (None, [])
        items = listing.json()
        if not isinstance(items, list):
            return (None, [])
        files_at_root = {
            item["name"]: item
            for item in items
            if isinstance(item, dict) and item.get("type") == "file"
        }
    except Exception:
        return (None, [])

    for manifest_name in _MANIFEST_PRIORITY:
        if manifest_name not in files_at_root:
            continue
        try:
            resp = client.get(
                f"{base}/repos/{owner}/{repo_name}/contents/{manifest_name}"
            )
            if resp.status_code != 200:
                continue
            payload = resp.json()
            encoded = payload.get("content") or ""
            if payload.get("encoding") == "base64":
                text = base64.b64decode(encoded).decode("utf-8", errors="ignore")
            else:
                text = encoded
            parser = _MANIFEST_PARSERS[manifest_name]
            deps = parser(text)
            # Dedupe, preserve order.
            seen: set[str] = set()
            unique_deps: list[str] = []
            for d in deps:
                if d and d not in seen:
                    seen.add(d)
                    unique_deps.append(d)
            return (manifest_name, unique_deps)
        except Exception:
            continue
    return (None, [])


def _count_recent_commits(
    client: "httpx.Client",
    base: str,
    username: str,
    repos: list[dict],
    days: int = 90,
) -> int:
    """Count commits authored by `username` across the given repos in the last N days.

    Hits /repos/{owner}/{repo}/commits with `author` and `since` filters; counts
    items returned (capped at 100 per repo). Costs one API call per repo, which
    is fine since we only ever pass the top ~10 repos here.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    total = 0
    for r in repos:
        name = r.get("name")
        if not name:
            continue
        try:
            resp = client.get(
                f"{base}/repos/{username}/{name}/commits",
                params={"author": username, "since": since, "per_page": 100},
            )
            if resp.status_code == 200:
                total += len(resp.json())
        except Exception:
            continue
    return total


def fetch_github(profile_url: str) -> GitHubData:
    username = _username_from_url(profile_url)
    if not username:
        raise GitHubCandidateError(f"not a GitHub profile URL: {profile_url}")

    base = "https://api.github.com"
    timeout = httpx.Timeout(15.0)
    try:
        with httpx.Client(headers=_headers(), timeout=timeout) as client:
            user_resp = client.get(f"{base}/users/{username}")
            if user_resp.status_code == 404:
                raise GitHubCandidateError(f"GitHub user not found: {username}")
            if user_resp.status_code in (401, 403):
                # Could be rate-limit (infra) or auth — treat as infra and retry.
                raise GitHubInfraError(f"GitHub auth/ratelimit {user_resp.status_code}")
            if user_resp.status_code >= 500:
                raise GitHubInfraError(f"GitHub 5xx {user_resp.status_code}")
            user = user_resp.json()

            repos_resp = client.get(f"{base}/users/{username}/repos", params={"per_page": 100, "sort": "updated"})
            if repos_resp.status_code >= 500:
                raise GitHubInfraError(f"GitHub repos 5xx {repos_resp.status_code}")
            repos = repos_resp.json() if repos_resp.status_code == 200 else []

            languages: dict[str, int] = {}  # language -> bytes
            top_repos: list[dict] = []
            recent_repos_pushed = 0
            cutoff = datetime.now(timezone.utc) - timedelta(days=180)

            sorted_repos = sorted(repos, key=lambda r: (r.get("stargazers_count", 0), r.get("pushed_at") or ""), reverse=True)
            top_slice = sorted_repos[:10]

            for r in top_slice:
                name = r.get("name")

                # Real language bytes per repo (aggregated).
                try:
                    lang_resp = client.get(f"{base}/repos/{username}/{name}/languages")
                    if lang_resp.status_code == 200:
                        for lang, byte_count in lang_resp.json().items():
                            languages[lang] = languages.get(lang, 0) + int(byte_count)
                except Exception:
                    pass

                # Dependency manifest per repo (2 calls max).
                manifest_type, deps = _fetch_repo_dependencies(client, base, username, name)

                top_repos.append({
                    "name": name,
                    "stars": r.get("stargazers_count", 0),
                    "forks": r.get("forks_count", 0),
                    "language": r.get("language"),
                    "description": (r.get("description") or "")[:300],
                    "url": r.get("html_url"),
                    "pushed_at": r.get("pushed_at"),
                    "manifest_type": manifest_type,
                    "dependencies": deps,
                })

                pushed = r.get("pushed_at")
                if pushed:
                    try:
                        if datetime.fromisoformat(pushed.replace("Z", "+00:00")) >= cutoff:
                            recent_repos_pushed += 1
                    except Exception:
                        pass

            # Real commits authored by user in last 90 days (per top repo).
            recent_commits = _count_recent_commits(client, base, username, top_slice)

            return GitHubData(
                username=username,
                profile_url=user.get("html_url", profile_url),
                public_repos=user.get("public_repos", 0),
                followers=user.get("followers", 0),
                languages=languages,
                recent_repos_pushed_6mo=recent_repos_pushed,
                recent_commits_90d=recent_commits,
                top_repos=top_repos,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as e:
        raise GitHubInfraError(str(e))
