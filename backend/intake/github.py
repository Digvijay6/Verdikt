"""GitHub lookups for a candidate who applied.

**Verification, not sourcing.** These run only against links a candidate
supplied on their own application, to check claims they made themselves.
GitHub's Acceptable Use Policy forbids using information from the Service
"(whether scraped, collected through our API, or obtained otherwise)... for the
purposes of sending unsolicited emails to users or selling personal information,
such as to recruiters, headhunters, and job boards". Sourcing strangers from
GitHub would be squarely inside that. Checking whether someone who applied to
you actually wrote the code they claim is not.

Every function fails soft. A rate limit, a deleted repo, a private account, a
404 — none of them are the candidate's fault, and none may ever count against
them. See D32.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

API = "https://api.github.com"
TIMEOUT = 12
README_CHARS = 4000

# Unauthenticated is 60 requests/hour, which one candidate can exhaust. A token
# raises it to 5000/hour and costs nothing.
_UA = "verdikt-evidence/1.0"


def username_from_url(url: str) -> str | None:
    """Pull a username out of whatever the candidate pasted.

    They write `github.com/x`, `https://github.com/x/`, `@x`, or just `x`.
    Rejecting a valid profile over a trailing slash would be a silly way to
    lose evidence.
    """
    if not url:
        return None
    text = url.strip().rstrip("/")
    m = re.search(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)", text)
    if m:
        return m.group(1)
    bare = text.lstrip("@")
    if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", bare):
        return bare
    return None


def _get(path: str) -> Any | None:
    """One GET. Returns None on anything that is not a clean success.

    httpx rather than urllib: urllib uses the OS trust store, which is missing
    on some Python installs and fails every HTTPS call with
    CERTIFICATE_VERIFY_FAILED. httpx bundles certifi, so it works the same
    everywhere — and a cert problem here would otherwise look identical to a
    candidate having no GitHub profile.

    Deliberately swallows errors rather than raising: an outage or a rate limit
    must degrade to "no evidence found", never to a failed application.
    """
    headers = {"Accept": "application/vnd.github+json", "User-Agent": _UA}
    # Read straight from the environment rather than Settings: this is one
    # optional value for reading public data, and coupling it to the full
    # config would mean a missing LiveKit key breaks GitHub lookups.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = httpx.get(f"{API}{path}", headers=headers, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


# --- the calls the agent makes --------------------------------------------


def profile(username: str) -> dict | None:
    d = _get(f"/users/{username}")
    if not d:
        return None
    return {
        "login": d.get("login"),
        "name": d.get("name"),
        "bio": d.get("bio"),
        "company": d.get("company"),
        "location": d.get("location"),
        "public_repos": d.get("public_repos"),
        "followers": d.get("followers"),
        "created_at": d.get("created_at"),
        "url": d.get("html_url"),
    }


def repositories(username: str, limit: int = 30) -> list[dict]:
    """Most recently pushed first — recency is the useful ordering here.

    Forks are excluded: a forked repo says nothing about what someone built,
    and they are the most common way a skill looks evidenced when it is not.
    """
    d = _get(f"/users/{username}/repos?sort=pushed&per_page={limit}")
    if not d:
        return []
    return [
        {
            "name": r.get("name"),
            "description": r.get("description"),
            "language": r.get("language"),
            "stars": r.get("stargazers_count"),
            "pushed_at": r.get("pushed_at"),
            "topics": r.get("topics", []),
            "url": r.get("html_url"),
        }
        for r in d
        if not r.get("fork")
    ]


def repository_detail(username: str, repo: str) -> dict | None:
    """Languages and README — enough to tell a real project from a tutorial."""
    meta = _get(f"/repos/{username}/{repo}")
    if not meta:
        return None

    languages = _get(f"/repos/{username}/{repo}/languages") or {}
    readme_text = None
    readme = _get(f"/repos/{username}/{repo}/readme")
    if readme and readme.get("content"):
        import base64

        try:
            readme_text = base64.b64decode(readme["content"]).decode(
                "utf-8", "replace"
            )[:README_CHARS]
        except Exception:
            readme_text = None

    return {
        "name": meta.get("name"),
        "description": meta.get("description"),
        "url": meta.get("html_url"),
        "created_at": meta.get("created_at"),
        "pushed_at": meta.get("pushed_at"),
        "stars": meta.get("stargazers_count"),
        # Byte counts per language, which distinguishes a project genuinely
        # written in something from one that merely mentions it.
        "languages": languages,
        "readme": readme_text,
    }


def commits_by_author(username: str, repo: str, author: str) -> int | None:
    """How many commits `author` has in a repo. None if it cannot be determined."""
    d = _get(f"/repos/{username}/{repo}/commits?author={author}&per_page=100")
    if d is None:
        return None
    return len(d)
