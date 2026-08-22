"""Watch applications move through the intake pipeline.

    python -m scripts.watch [job_id]

Development only. Signs in as the seeded recruiter, polls until everything has
settled, then prints what the model decided and why.
"""

from __future__ import annotations

import sys
import time
import urllib.request
import json

from supabase import create_client

from shared.config import get_settings

API = "http://localhost:8000"
SETTLED = {"rejected_screen", "review", "invited", "scored", "advanced",
           "rejected_post", "failed"}


def token() -> str:
    cfg = get_settings()
    public = create_client(cfg.supabase_url, cfg.supabase_anon_key or "")
    s = public.auth.sign_in_with_password(
        {"email": "recruiter@example.com", "password": "verdikt-dev-password"}
    )
    return s.session.access_token


def get(path: str, tok: str):
    req = urllib.request.Request(f"{API}{path}")
    req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def main() -> None:
    tok = token()
    job_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not job_id:
        jobs = get("/intake/jobs", tok)
        if not jobs:
            sys.exit("No jobs. Create one first.")
        job_id = jobs[0]["id"]
        print(f"watching most recent job: {jobs[0]['title']}\n")

    for _ in range(60):
        apps = get(f"/intake/applications?job_id={job_id}", tok)
        if not apps:
            print("  no applications yet...")
        else:
            line = "  " + " | ".join(
                f"{(a['parsed_resume'] or {}).get('full_name') or '...'}: {a['status']}"
                for a in apps
            )
            print(line, flush=True)
            if all(a["status"] in SETTLED for a in apps):
                break
        time.sleep(5)

    print("\n" + "=" * 68)
    for a in apps:
        pr = a["parsed_resume"] or {}
        print(f"\n{pr.get('full_name') or '(unparsed)'} -> {a['status'].upper()}")
        print(f"  years: {pr.get('total_years_experience')}   "
              f"location: {pr.get('location')}")
        if pr.get("skills"):
            print(f"  skills: {', '.join(pr['skills'][:12])}")

        for c in a["hard_checks"]:
            if not c["passed"]:
                print(f"  BLOCKED BY  {c['check']}: {c['detail']}")

        s = a.get("screening")
        if s:
            print(f"\n  screen: {s['outcome']} (confidence {s['confidence']})")
            print(f"  {s['rationale']}")
            if s["evidence"]:
                print("  evidence:")
                for e in s["evidence"][:6]:
                    print(f"    - {e}")
            if s["concerns"]:
                print("  concerns:")
                for c in s["concerns"]:
                    print(f"    - {c}")

        if a.get("failure_reason"):
            print(f"\n  PROBLEM: {a['failure_reason']}")


if __name__ == "__main__":
    main()
