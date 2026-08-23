"""End-to-end test of the AI interview call.

Creates a LiveKit room with the InterviewPackage as metadata, mints an access
token, and prints the URL you open in the browser to join the interview.

The voice worker (python -m voice.agent dev) must be running in a separate
terminal and registered with the same LiveKit Cloud project.

Usage:
    cd backend && python scripts/test_ai_call.py

    Then open the printed URL in Chrome with mic permissions enabled.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from livekit import api

from shared.config import get_settings
from shared.db import db


async def main() -> None:
    settings = get_settings()

    # 1. Pick a job with a ready question bank that also has applications
    supabase = db()
    jobs = supabase.table("job").select(
        "id,title,seniority,question_bank,rubric_version,org_id"
    ).eq("question_bank_status", "ready").execute()

    if not jobs.data:
        print("ERROR: No jobs with a ready question bank. Create a job first.")
        sys.exit(1)

    # Find the first job that also has an application
    job = None
    application = None
    for candidate_job in jobs.data:
        apps = (
            supabase.table("application")
            .select("id,job_id,org_id,candidate_id,parsed_resume")
            .eq("job_id", candidate_job["id"])
            .limit(1)
            .execute()
        )
        if apps.data:
            job = candidate_job
            application = apps.data[0]
            break

    if not job:
        print("ERROR: Jobs exist but none have applications.")
        print("Create an application via the frontend or seed_dev.py first.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Job: {job['title']}")
    print(f"  Seniority: {job['seniority']}")
    print(f"  Application: {application['id'][:8]}...")
    print(f"  Resume: {'yes' if application.get('parsed_resume') else 'no'}")

    # 3. Build the InterviewPackage via Lane 1's packaging function
    from intake.packaging import PackageUnavailable, build_interview_package

    interview_id = "00000000-0000-0000-0000-000000000001"
    try:
        package = build_interview_package(
            application_id=application["id"],
            org_id=application["org_id"],
            interview_id=interview_id,
        )
    except PackageUnavailable as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"  Package: {len(package.questions)} questions loaded")
    print(f"  Rubric version: {package.rubric_version}")
    print(f"{'='*60}\n")

    # 6. Create a LiveKit room with the package as metadata
    lk_api = api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )

    room_name = f"test-call-{datetime.now(UTC).strftime('%H%M%S')}"

    print(f"Creating LiveKit room: {room_name}...")
    try:
        room = await lk_api.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                metadata=package.model_dump_json(),
            ),
        )
        print(f"  Room created: {room.name}")
    except Exception as e:
        print(f"ERROR creating room: {e}")
        sys.exit(1)

    # 7. Mint an access token for the candidate (you, the tester)
    token = (
        api.AccessToken(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        .with_identity("test-candidate")
        .with_name("Test Candidate")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            ),
        )
        .to_jwt()
    )

    # 8. Write a test interview row to Supabase (so the post-call pipeline can find it)
    insert_data = {
        "id": interview_id,
        "org_id": package.org_id,
        "application_id": application["id"],
        "job_id": package.job_id,
        "status": "in_progress",
        "room_name": room_name,
        "seniority": package.seniority,
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        supabase.table("interview").upsert(insert_data).execute()
    except Exception:
        insert_data.pop("seniority", None)
        supabase.table("interview").upsert(insert_data).execute()

    # 9. Print the join URL
    # The frontend at /interview/:token expects to call /redeem first,
    # but for direct testing we can bypass that and give the LiveKit
    # token directly. Open the LiveKit playground or use the frontend.

    print(f"\n{'='*60}")
    print(f"  ROOM: {room_name}")
    print(f"  LIVEKIT_URL: {settings.livekit_url}")
    print(f"  TOKEN: {token[:40]}...")
    print(f"{'='*60}")

    # Build the frontend URL (bypasses /redeem, passes token directly)
    # The frontend route /interview/:token calls /redeem, but for direct
    # testing you can use the LiveKit playground:
    playground_url = (
        f"https://meet.livekit.io?room={room_name}"
        f"&url={settings.livekit_url}"
    )
    # Or build a simple test page URL

    print("\n  Option A — LiveKit Playground:")
    print(f"  {playground_url}")
    print("  (Paste the token below when prompted)")

    print("\n  Option B — Use the token directly:")
    print(f"  wss URL: {settings.livekit_url}")
    print(f"  Token: {token}")
    print(f"  Room: {room_name}")

    print("\n  Option C — Frontend (requires API + frontend running):")
    print("  http://localhost:5173/interview/test-token-direct")
    print("  (This will call /redeem which will fail — use Option A or B)")

    print("\n  The voice worker should auto-join this room.")
    print("  Make sure 'python -m voice.agent dev' is running.\n")

    # 10. Wait for the room to be empty, then clean up
    print("Press Ctrl+C to clean up and exit.\n")

    try:
        while True:
            await asyncio.sleep(10)
            # Check if anyone is in the room
            try:
                participants = await lk_api.room.list_participants(
                    api.ListParticipantsRequest(room=room_name),
                )
                count = len(participants) if participants else 0
                if count > 0:
                    print(
                        f"  [{datetime.now(UTC).strftime('%H:%M:%S')}] "
                        f"{count} participant(s) in room"
                    )
            except Exception:
                pass
    except KeyboardInterrupt:
        print("\nCleaning up...")

        # Delete the test interview row
        supabase.table("interview").delete().eq(
            "id", interview_id
        ).execute()

        # Delete the room
        try:
            await lk_api.room.delete_room(
                api.DeleteRoomRequest(room=room_name),
            )
            print(f"  Room {room_name} deleted.")
        except Exception:
            pass

        await lk_api.aclose()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())