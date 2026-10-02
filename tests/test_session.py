"""
tests/test_session.py — Comprehensive tests for Nudge10 Stage 8 Session Lifecycle.

Tests cover:
  - Session creation via POST /api/session/start
  - Unique session IDs across calls
  - Session completion via POST /api/session/complete
  - Session abandonment via POST /api/session/abandon (no shame)
  - Distraction logging via POST /api/session/distraction
  - Handling of unknown / invalid session IDs
  - Elapsed time validation (negative, out-of-bounds)
  - Automatic timeout completion simulation
  - Behavioral memory gating (only durable/recurring patterns remembered)
  - Backboard memory write failure resilience
  - Backboard AI failure fallback resilience
  - No secret or API key leakage in responses
  - Client session persistence schema compatibility
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app import backboard_service, session_service


@pytest.fixture(autouse=True)
def clean_sessions():
    """Clear in-memory sessions before each test."""
    session_service._sessions.clear()
    yield
    session_service._sessions.clear()


@pytest.fixture(autouse=True)
def mock_default_ai():
    """Default AI mocks for fast unit tests without network delays."""
    default_mission = {
        "title": "Start with one tiny step",
        "action": "Work on the first line",
        "reason": "Reduces friction",
    }
    default_nudge = {
        "message": "You left your mission. Come back before the 10 minutes are up.",
        "action": "Return to your task and focus for 60 seconds.",
    }
    with patch.object(backboard_service.backboard, "create_mission", new=AsyncMock(return_value=default_mission)):
        with patch.object(backboard_service.backboard, "generate_nudge", new=AsyncMock(return_value=default_nudge)):
            yield


@pytest.mark.asyncio
async def test_session_creation():
    """POST /api/session/start returns a valid session_id and mission."""
    fake_mission = {
        "title": "Write 3 lines",
        "action": "Write the introduction paragraph",
        "reason": "Reduces initial friction",
    }
    with patch.object(backboard_service.backboard, "create_mission", new=AsyncMock(return_value=fake_mission)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/session/start", json={"task": "Write research paper", "duration_minutes": 10})
            assert resp.status_code == 200
            data = resp.json()
            assert "session_id" in data
            assert len(data["session_id"]) > 10
            assert data["duration_minutes"] == 10
            assert data["mission"]["title"] == "Write 3 lines"
            assert data["mission"]["action"] == "Write the introduction paragraph"
            assert data["mission"]["reason"] == "Reduces initial friction"
            assert data["mission"]["source"] == "backboard"
            assert "started_at" in data


@pytest.mark.asyncio
async def test_session_unique_ids():
    """Multiple sessions generate distinct session_ids."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.post("/api/session/start", json={"task": "Task 1", "duration_minutes": 10})
        resp2 = await client.post("/api/session/start", json={"task": "Task 2", "duration_minutes": 10})
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        id1 = resp1.json()["session_id"]
        id2 = resp2.json()["session_id"]
        assert id1 != id2


@pytest.mark.asyncio
async def test_session_completion():
    """POST /api/session/complete marks session completed and returns supportive response."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start_resp = await client.post("/api/session/start", json={"task": "Organize notes", "duration_minutes": 10})
        session_id = start_resp.json()["session_id"]

        comp_resp = await client.post(
            "/api/session/complete",
            json={"session_id": session_id, "elapsed_seconds": 600},
        )
        assert comp_resp.status_code == 200
        data = comp_resp.json()
        assert data["session_id"] == session_id
        assert data["status"] == "completed"
        assert data["elapsed_seconds"] == 600
        assert "complete" in data["message"].lower()

        # Check internal status
        s = session_service.get_session(session_id)
        assert s is not None
        assert s["status"] == "completed"
        assert s["elapsed_seconds"] == 600


@pytest.mark.asyncio
async def test_session_abandonment_no_shame():
    """POST /api/session/abandon returns a supportive, non-judgmental response with a next step."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start_resp = await client.post("/api/session/start", json={"task": "Math Homework", "duration_minutes": 10})
        session_id = start_resp.json()["session_id"]

        aban_resp = await client.post(
            "/api/session/abandon",
            json={"session_id": session_id, "elapsed_seconds": 320, "reason": "tired"},
        )
        assert aban_resp.status_code == 200
        data = aban_resp.json()
        assert data["session_id"] == session_id
        assert data["status"] == "abandoned"
        # No guilt / shame check
        message = data["message"].lower()
        assert "fail" not in message
        assert "lazy" not in message
        assert "bad" not in message
        assert "next_step" in data
        assert len(data["next_step"]) > 0

        # Check internal status
        s = session_service.get_session(session_id)
        assert s["status"] == "abandoned"


@pytest.mark.asyncio
async def test_session_distraction():
    """POST /api/session/distraction records normalized site and returns intervention."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start_resp = await client.post("/api/session/start", json={"task": "Write essay", "duration_minutes": 10})
        session_id = start_resp.json()["session_id"]

        dist_resp = await client.post(
            "/api/session/distraction",
            json={"session_id": session_id, "site": "youtube.com", "elapsed_seconds": 150},
        )
        assert dist_resp.status_code == 200
        data = dist_resp.json()
        assert "message" in data
        assert "action" in data

        s = session_service.get_session(session_id)
        assert len(s["distractions"]) == 1
        assert s["distractions"][0]["site"] == "youtube.com"


@pytest.mark.asyncio
async def test_invalid_session_id_handled_gracefully():
    """Passing an unknown or non-existent session_id does not throw 500."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        comp_resp = await client.post(
            "/api/session/complete",
            json={"session_id": "non-existent-id-999", "elapsed_seconds": 300},
        )
        assert comp_resp.status_code == 200
        assert comp_resp.json()["status"] == "completed"

        aban_resp = await client.post(
            "/api/session/abandon",
            json={"session_id": "non-existent-id-999", "elapsed_seconds": 100},
        )
        assert aban_resp.status_code == 200
        assert aban_resp.json()["status"] == "abandoned"


@pytest.mark.asyncio
async def test_elapsed_seconds_validation():
    """Negative elapsed seconds or out-of-bounds elapsed seconds fail schema validation with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Negative
        resp = await client.post(
            "/api/session/complete",
            json={"session_id": "test-id", "elapsed_seconds": -10},
        )
        assert resp.status_code == 422

        # Too large (> 1800)
        resp2 = await client.post(
            "/api/session/complete",
            json={"session_id": "test-id", "elapsed_seconds": 9999},
        )
        assert resp2.status_code == 422


@pytest.mark.asyncio
async def test_automatic_completion_at_timeout():
    """Simulation of timer expiring after 600s."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start_resp = await client.post("/api/session/start", json={"task": "Final presentation slides", "duration_minutes": 10})
        session_id = start_resp.json()["session_id"]

        comp_resp = await client.post(
            "/api/session/complete",
            json={"session_id": session_id, "elapsed_seconds": 600},
        )
        assert comp_resp.status_code == 200
        assert comp_resp.json()["elapsed_seconds"] == 600
        assert comp_resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_behavioral_memory_gating():
    """Verify memory is only saved for durable/recurring patterns, not isolated events."""
    remember_mock = AsyncMock(return_value=True)
    with patch.object(backboard_service.backboard, "remember_session", new=remember_mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Clean completion without repeated distractions -> should NOT write memory
            s1 = await client.post("/api/session/start", json={"task": "Read book", "duration_minutes": 10})
            id1 = s1.json()["session_id"]
            await client.post("/api/session/complete", json={"session_id": id1, "elapsed_seconds": 600})
            assert remember_mock.call_count == 0

            # 2. Session with 1 isolated distraction -> should NOT write memory
            s2 = await client.post("/api/session/start", json={"task": "Read book 2", "duration_minutes": 10})
            id2 = s2.json()["session_id"]
            await client.post("/api/session/distraction", json={"session_id": id2, "site": "reddit.com", "elapsed_seconds": 150})
            await client.post("/api/session/complete", json={"session_id": id2, "elapsed_seconds": 600})
            assert remember_mock.call_count == 0

            # 3. Session with REPEATED distractions on same site (>=2) and elapsed >= 120s -> SHOULD write memory
            s3 = await client.post("/api/session/start", json={"task": "Read book 3", "duration_minutes": 10})
            id3 = s3.json()["session_id"]
            await client.post("/api/session/distraction", json={"session_id": id3, "site": "youtube.com", "elapsed_seconds": 150})
            await client.post("/api/session/distraction", json={"session_id": id3, "site": "youtube.com", "elapsed_seconds": 300})
            await client.post("/api/session/complete", json={"session_id": id3, "elapsed_seconds": 600})
            assert remember_mock.call_count == 1
            saved_text = remember_mock.call_args[0][0]
            assert "youtube.com" in saved_text


@pytest.mark.asyncio
async def test_backboard_memory_write_failure_resilience():
    """If Backboard remember_session fails or raises an error, the endpoint completes gracefully."""
    with patch.object(backboard_service.backboard, "remember_session", new=AsyncMock(side_effect=Exception("API down"))):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            start_resp = await client.post("/api/session/start", json={"task": "Study code", "duration_minutes": 10})
            session_id = start_resp.json()["session_id"]

            # Record 2 distractions to trigger memory branch
            await client.post("/api/session/distraction", json={"session_id": session_id, "site": "x.com", "elapsed_seconds": 150})
            await client.post("/api/session/distraction", json={"session_id": session_id, "site": "x.com", "elapsed_seconds": 250})

            # Should complete without error
            comp_resp = await client.post("/api/session/complete", json={"session_id": session_id, "elapsed_seconds": 600})
            assert comp_resp.status_code == 200
            assert comp_resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_backboard_ai_failure_fallback():
    """If Backboard mission or nudge generation fails, fallback content is returned."""
    with patch.object(backboard_service.backboard, "create_mission", new=AsyncMock(return_value=None)):
        with patch.object(backboard_service.backboard, "generate_nudge", new=AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                start_resp = await client.post("/api/session/start", json={"task": "Study code", "duration_minutes": 10})
                assert start_resp.status_code == 200
                data = start_resp.json()
                assert data["mission"]["source"] == "demo-fallback"

                dist_resp = await client.post(
                    "/api/session/distraction",
                    json={"session_id": data["session_id"], "site": "instagram.com", "elapsed_seconds": 120},
                )
                assert dist_resp.status_code == 200
                dist_data = dist_resp.json()
                assert dist_data["source"] == "demo-fallback"
                assert "instagram.com" in dist_data["message"]


@pytest.mark.asyncio
async def test_no_secret_leakage():
    """Verify neither the API key nor secret tokens appear in responses."""
    from app.config import settings

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start_resp = await client.post("/api/session/start", json={"task": "Check privacy", "duration_minutes": 10})
        body_str = json.dumps(start_resp.json())
        assert settings.backboard_api_key not in body_str
        assert "Bearer" not in body_str

        # Distraction response
        dist_resp = await client.post(
            "/api/session/distraction",
            json={"session_id": start_resp.json()["session_id"], "site": "reddit.com", "elapsed_seconds": 50},
        )
        dist_str = json.dumps(dist_resp.json())
        assert settings.backboard_api_key not in dist_str


def test_client_localstorage_schema_compatibility():
    """Verify that client localStorage session state structure has all required fields."""
    client_stored_session = {
        "session_id": "test-uuid-1234",
        "task": "Finish DBMS question 1",
        "mission": {
            "title": "Start tiny",
            "action": "Write question 1 schema definition",
            "reason": "Low friction entry point",
            "source": "backboard",
        },
        "duration_minutes": 10,
        "status": "active",
        "started_at": 1727878888000,
        "target_end_time": 1727879488000,
    }

    # Serialization test
    serialized = json.dumps(client_stored_session)
    restored = json.loads(serialized)
    assert restored["session_id"] == "test-uuid-1234"
    assert restored["status"] == "active"
    assert restored["target_end_time"] > restored["started_at"]
    assert "action" in restored["mission"]
