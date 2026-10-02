"""
tests/test_backboard.py — Unit tests for Nudge10 BackboardService.

Tests cover:
  - successful Backboard response (mission + nudge)
  - valid JSON parsing
  - malformed JSON from model
  - Backboard API exception
  - missing assistant ID (disabled service)
  - fallback trigger in FastAPI route

All tests use mocks — no real API calls are made.
"""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build a fake ChatMessagesResponse
# ---------------------------------------------------------------------------

def _fake_response(content: str):
    """Return a mock that behaves like ChatMessagesResponse with .content."""
    mock = MagicMock()
    mock.content = content
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    """Inject dummy (non-secret) settings so the service reports as enabled."""
    from app.config import settings
    monkeypatch.setattr(settings, "backboard_api_key", "test-key-not-real")
    monkeypatch.setattr(settings, "backboard_assistant_id", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(settings, "backboard_model_provider", "openrouter")
    monkeypatch.setattr(settings, "backboard_model_name", "google/gemma-3-27b-it")


@pytest.fixture()
def service():
    """Fresh BackboardService instance per test."""
    from app.backboard_service import BackboardService
    svc = BackboardService()
    svc.enabled = True  # settings are patched above
    return svc


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_plain_json(self):
        from app.backboard_service import _extract_json
        raw = '{"title": "Do it", "action": "open doc", "reason": "easiest start"}'
        result = _extract_json(raw)
        assert result == {"title": "Do it", "action": "open doc", "reason": "easiest start"}

    def test_json_in_markdown_fence(self):
        from app.backboard_service import _extract_json
        raw = '```json\n{"title": "T", "action": "A", "reason": "R"}\n```'
        result = _extract_json(raw)
        assert result is not None
        assert result["title"] == "T"

    def test_json_embedded_in_prose(self):
        from app.backboard_service import _extract_json
        raw = 'Sure! Here you go: {"title":"X","action":"Y","reason":"Z"} Hope that helps.'
        result = _extract_json(raw)
        assert result is not None
        assert result["action"] == "Y"

    def test_completely_invalid(self):
        from app.backboard_service import _extract_json
        assert _extract_json("This is just text.") is None

    def test_empty_string(self):
        from app.backboard_service import _extract_json
        assert _extract_json("") is None


# ---------------------------------------------------------------------------
# create_mission — success
# ---------------------------------------------------------------------------

class TestCreateMissionSuccess:
    @pytest.mark.asyncio
    async def test_returns_dict_with_required_keys(self, service):
        payload = json.dumps({"title": "DBMS", "action": "Open chapter 3", "reason": "Smallest step"})
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_fake_response(payload))
        service.client = mock_client

        result = await service.create_mission("Finish DBMS assignment", 10)

        assert result is not None
        assert result["title"] == "DBMS"
        assert result["action"] == "Open chapter 3"
        assert result["reason"] == "Smallest step"

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_fields(self, service):
        payload = json.dumps({"title": "  My Task  ", "action": "  Do thing  ", "reason": "  Because  "})
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_fake_response(payload))
        service.client = mock_client

        result = await service.create_mission("Task", 10)
        assert result["title"] == "My Task"
        assert result["action"] == "Do thing"


# ---------------------------------------------------------------------------
# create_mission — malformed model output
# ---------------------------------------------------------------------------

class TestCreateMissionMalformed:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_none(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_fake_response("not json at all!"))
        service.client = mock_client

        result = await service.create_mission("Task", 10)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_required_field_returns_none(self, service):
        # "reason" is missing — Pydantic must reject this
        payload = json.dumps({"title": "T", "action": "A"})
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_fake_response(payload))
        service.client = mock_client

        result = await service.create_mission("Task", 10)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_content_returns_none(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_fake_response(""))
        service.client = mock_client

        result = await service.create_mission("Task", 10)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_content_returns_none(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_fake_response(None))
        service.client = mock_client

        result = await service.create_mission("Task", 10)
        assert result is None


# ---------------------------------------------------------------------------
# create_mission — API failure / exception
# ---------------------------------------------------------------------------

class TestCreateMissionAPIError:
    @pytest.mark.asyncio
    async def test_send_message_exception_returns_none(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(side_effect=RuntimeError("connection refused"))
        service.client = mock_client

        result = await service.create_mission("Task", 10)
        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(side_effect=Exception("403 Forbidden"))
        service.client = mock_client

        result = await service.create_mission("Task", 10)
        assert result is None


# ---------------------------------------------------------------------------
# Missing assistant ID — disabled service
# ---------------------------------------------------------------------------

class TestDisabledService:
    @pytest.mark.asyncio
    async def test_no_assistant_id_returns_none(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "backboard_assistant_id", None)

        from app.backboard_service import BackboardService
        svc = BackboardService()
        # enabled should be False when assistant_id is missing
        assert svc.enabled is False

        result = await svc.create_mission("Task", 10)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "backboard_api_key", None)

        from app.backboard_service import BackboardService
        svc = BackboardService()
        assert svc.enabled is False

        result = await svc.create_mission("Task", 10)
        assert result is None


# ---------------------------------------------------------------------------
# generate_nudge — success
# ---------------------------------------------------------------------------

class TestGenerateNudgeSuccess:
    @pytest.mark.asyncio
    async def test_returns_message_and_action(self, service):
        payload = json.dumps({"message": "You drifted. That's fine.", "action": "Close YouTube and open your doc."})
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_fake_response(payload))
        service.client = mock_client

        result = await service.generate_nudge("DBMS", 4, "YouTube Shorts", 1)
        assert result is not None
        assert "message" in result
        assert "action" in result

    @pytest.mark.asyncio
    async def test_malformed_nudge_returns_none(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_fake_response("broken"))
        service.client = mock_client

        result = await service.generate_nudge("DBMS", 4, "Reddit", 2)
        assert result is None


# ---------------------------------------------------------------------------
# FastAPI fallback integration
# ---------------------------------------------------------------------------

class TestFallbackRoute:
    @pytest.mark.asyncio
    async def test_mission_endpoint_falls_back_when_backboard_returns_none(self):
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app import backboard_service

        with patch.object(backboard_service.backboard, "create_mission", new=AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/mission", json={"task": "Test task", "minutes": 10})
                assert resp.status_code == 200
                body = resp.json()
                assert body["source"] == "demo-fallback"
                assert "title" in body
                assert "action" in body
                assert "why" in body

    @pytest.mark.asyncio
    async def test_mission_endpoint_returns_ai_when_backboard_succeeds(self):
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app import backboard_service

        ai_result = {"title": "Open chapter 3", "action": "Read first two pages", "reason": "Easiest entry point"}
        with patch.object(backboard_service.backboard, "create_mission", new=AsyncMock(return_value=ai_result)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/mission", json={"task": "DBMS assignment", "minutes": 10})
                assert resp.status_code == 200
                body = resp.json()
                assert body["source"] == "backboard"
                assert body["title"] == "Open chapter 3"
                # "reason" is mapped to "why" in the API response
                assert body["why"] == "Easiest entry point"


# ---------------------------------------------------------------------------
# _MissionRaw Pydantic model
# ---------------------------------------------------------------------------

class TestMissionRawModel:
    def test_valid(self):
        from app.backboard_service import _MissionRaw
        m = _MissionRaw(title="T", action="A", reason="R")
        assert m.title == "T"

    def test_missing_reason_raises(self):
        from app.backboard_service import _MissionRaw
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _MissionRaw(title="T", action="A")  # reason missing

    def test_missing_action_raises(self):
        from app.backboard_service import _MissionRaw
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _MissionRaw(title="T", reason="R")  # action missing


class TestHealthAndProductionConfig:
    @pytest.mark.asyncio
    async def test_health_in_development_exposes_assistant_id(self, monkeypatch):
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.config import settings
        from app.backboard_service import backboard

        monkeypatch.setattr(settings, "app_env", "development")
        monkeypatch.setattr(backboard, "enabled", True)
        monkeypatch.setattr(settings, "backboard_assistant_id", "test-asst-uuid")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["ai_enabled"] is True
            assert data.get("assistant_id") == "test-asst-uuid"

    @pytest.mark.asyncio
    async def test_health_in_production_omits_assistant_id(self, monkeypatch):
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.config import settings
        from app.backboard_service import backboard

        monkeypatch.setattr(settings, "app_env", "production")
        monkeypatch.setattr(backboard, "enabled", True)
        monkeypatch.setattr(settings, "backboard_assistant_id", "test-asst-uuid")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["ai_enabled"] is True
            assert "assistant_id" not in data

    @pytest.mark.asyncio
    async def test_frontend_root_serves_html(self):
        from httpx import AsyncClient, ASGITransport
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "text/html" in resp.headers.get("content-type", "")
            assert "Nudge10" in resp.text

