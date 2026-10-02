"""
scripts/smoke_test_session_api.py — Real API smoke test for Nudge10 Stage 8.

Verifies:
  - POST /api/session/start (using real Backboard/Gemma AI integration)
  - POST /api/session/distraction
  - POST /api/session/abandon
  - POST /api/session/complete
Never exposes API keys or credentials.
"""

import asyncio
from httpx import ASGITransport, AsyncClient
from app.main import app


async def smoke_test():
    print("=" * 60)
    print("NUDGE10 STAGE 8 SESSION API SMOKE TEST (REAL BACKBOARD/GEMMA)")
    print("=" * 60)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30.0) as client:
        # 1. POST /api/session/start
        print("\n1. Testing POST /api/session/start...")
        start_payload = {"task": "Finish DBMS question 1 schema design", "duration_minutes": 10}
        resp = await client.post("/api/session/start", json=start_payload)
        assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
        data = resp.json()
        session_id = data["session_id"]
        mission = data["mission"]
        print(f"   ✓ Session started! ID: {session_id}")
        print(f"   ✓ Source: {mission.get('source')}")
        print(f"   ✓ Title:  {mission.get('title')}")
        print(f"   ✓ Action: {mission.get('action')}")
        print(f"   ✓ Reason: {mission.get('reason')}")

        # 2. POST /api/session/distraction
        print("\n2. Testing POST /api/session/distraction...")
        dist_payload = {
            "session_id": session_id,
            "site": "youtube.com",
            "elapsed_seconds": 180,
        }
        resp = await client.post("/api/session/distraction", json=dist_payload)
        assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
        dist_data = resp.json()
        print(f"   ✓ Distraction logged!")
        print(f"   ✓ Source:  {dist_data.get('source')}")
        print(f"   ✓ Message: {dist_data.get('message')}")
        print(f"   ✓ Action:  {dist_data.get('action')}")

        # 3. POST /api/session/abandon
        print("\n3. Testing POST /api/session/abandon...")
        abandon_payload = {
            "session_id": session_id,
            "elapsed_seconds": 240,
            "reason": "felt stuck on table joins",
        }
        resp = await client.post("/api/session/abandon", json=abandon_payload)
        assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
        abandon_data = resp.json()
        print(f"   ✓ Abandon logged gracefully!")
        print(f"   ✓ Message:   {abandon_data.get('message')}")
        print(f"   ✓ Next Step: {abandon_data.get('next_step')}")

        # 4. POST /api/session/start (new) & POST /api/session/complete
        print("\n4. Testing POST /api/session/start & /api/session/complete...")
        start2_resp = await client.post("/api/session/start", json={"task": "Write README docs", "duration_minutes": 10})
        assert start2_resp.status_code == 200
        session_id_2 = start2_resp.json()["session_id"]

        comp_payload = {
            "session_id": session_id_2,
            "elapsed_seconds": 600,
        }
        resp = await client.post("/api/session/complete", json=comp_payload)
        assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
        comp_data = resp.json()
        print(f"   ✓ Session completed!")
        print(f"   ✓ Status:  {comp_data.get('status')}")
        print(f"   ✓ Message: {comp_data.get('message')}")

    print("\n" + "=" * 60)
    print("ALL 4 ENDPOINTS PASSED REAL SMOKE TEST!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(smoke_test())
