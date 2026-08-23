"""LANE 1 — public, unauthenticated job pages.

Server-rendered so Google can index the JobPosting structured data without
executing JavaScript. The interactive application form stays in the SPA; this
page is the crawlable, shareable, paste-into-LinkedIn surface that links to it.

No prefix: a job URL people share should read /j/<id>, not /intake/j/<id>.
"""

from __future__ import annotations

import json
from html import escape

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import HTMLResponse

from intake import posting, repo
from shared.config import get_settings
from shared.models.job import JobStatus
from shared.tenancy import get_organization

router = APIRouter(tags=["public"])


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title} — {org}</title>
<meta name="description" content="{summary}"/>
<link rel="canonical" href="{canonical}"/>
<meta property="og:title" content="{title} — {org}"/>
<meta property="og:description" content="{summary}"/>
<meta property="og:type" content="website"/>
<meta property="og:url" content="{canonical}"/>
{robots}
<script type="application/ld+json">{jsonld}</script>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;
         background:#fff; color:#16181d; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background:#101114; color:#e8eaed; }}
    .meta, footer {{ color:#9aa1ab; }}
    a.apply {{ background:#e8eaed; color:#101114; }}
  }}
  main {{ max-width:44rem; margin:0 auto; padding:3rem 1.25rem 5rem; }}
  h1 {{ font-size:1.75rem; margin:0 0 .35rem; }}
  .meta {{ color:#6b7280; font-size:.95rem; margin-bottom:2rem; }}
  a.apply {{ display:inline-block; margin:2rem 0; padding:.75rem 1.4rem;
            background:#16181d; color:#fff; text-decoration:none;
            border-radius:6px; font-weight:500; }}
  .jd p {{ margin:0 0 1rem; }}
  footer {{ margin-top:3rem; font-size:.85rem; color:#6b7280; }}
  .closed {{ padding:.85rem 1rem; border:1px solid #b42318; color:#b42318;
             border-radius:6px; margin-bottom:2rem; }}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p class="meta">{org} &middot; {where}{etype}</p>
  {banner}
  <div class="jd">{description}</div>
  {apply}
  <footer>Interviews for this role are conducted by an AI interviewer and
  recorded. A human reviews every outcome.</footer>
</main>
</body>
</html>"""


@router.get("/j/{job_id}", response_class=HTMLResponse, include_in_schema=False)
def public_job_page(job_id: str) -> HTMLResponse:
    """The shareable, indexable posting.

    Unauthenticated by necessity — a crawler has no session, and so does a
    candidate following a link. Only fields meant to be public are rendered;
    the screening profile and question bank are not among them.
    """
    job = repo.get_job_unscoped(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")

    org = get_organization(job.org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")

    cfg = get_settings()
    apply_url = f"{cfg.app_base_url}/apply/{job.id}"
    canonical = f"{cfg.app_base_url.rstrip('/')}/j/{job.id}"
    is_open = job.status is JobStatus.OPEN

    summary = " ".join(job.jd_text.split())[:155]
    where = "Remote" if job.remote else (job.location or "Location not specified")
    etype = (
        f" &middot; {job.employment_type.value.replace('_', ' ').title()}"
        if job.employment_type
        else ""
    )

    return HTMLResponse(
        PAGE.format(
            title=escape(job.title),
            org=escape(org.name),
            summary=escape(summary),
            canonical=escape(canonical),
            where=escape(where),
            etype=etype,
            # A closed role must not stay in the index advertising a vacancy
            # that no longer exists.
            robots="" if is_open else '<meta name="robots" content="noindex"/>',
            jsonld=json.dumps(
                posting.job_posting_jsonld(job, org, apply_url), separators=(",", ":")
            ),
            banner=""
            if is_open
            else '<p class="closed">This role is no longer accepting applications.</p>',
            description=posting._html_paragraphs(job.jd_text),
            apply=f'<a class="apply" href="{escape(apply_url)}">Apply for this role</a>'
            if is_open
            else "",
        )
    )


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap() -> Response:
    """How Google discovers the postings.

    Open roles only — listing a closed one invites a crawl of a page that
    immediately says the vacancy is gone.
    """
    cfg = get_settings()
    base = cfg.app_base_url.rstrip("/")
    urls = "".join(
        f"<url><loc>{base}/j/{j['id']}</loc>"
        f"<lastmod>{j['updated_at'][:10]}</lastmod></url>"
        for j in repo.open_jobs_for_sitemap()
    )
    return Response(
        content=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{urls}</urlset>"
        ),
        media_type="application/xml",
    )


@router.get("/robots.txt", include_in_schema=False)
def robots() -> Response:
    base = get_settings().app_base_url.rstrip("/")
    return Response(
        content=f"User-agent: *\nAllow: /j/\nSitemap: {base}/sitemap.xml\n",
        media_type="text/plain",
    )
