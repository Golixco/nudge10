"""
tests/test_memory.py — Unit tests for BackboardService memory and thread methods.

Tests:
  - create_thread returns a thread_id string
  - create_thread returns None on API failure (no crash)
  - send_in_thread passes correct assistant_id
  - send_in_thread uses the given thread_id (not a different one)
  - send_in_thread passes memory="Auto"
  - send_in_thread extracts memory_operation_id from raw message dict
  - send_in_thread extracts retrieved_memories from raw message dict
  - send_in_thread returns status="api_error" on exception (no crash)
  - send_in_thread returns status="disabled" when service is disabled
  - check_memory_operation returns correct dict shape
  - check_memory_operation returns {"status": "unavailable"} on exception
  - poll_memory_operation returns on "completed"
  - poll_memory_operation handles "unavailable"
  - list_memories returns list of dicts
  - list_memories returns [] on failure
  - search_memories returns list of dicts
  - search_memories returns [] on failure

All tests use mocks — no real API calls.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "backboard_api_key", "test-key-not-real")
    monkeypatch.setattr(settings, "backboard_assistant_id", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(settings, "backboard_model_provider", "openrouter")
    monkeypatch.setattr(settings, "backboard_model_name", "google/gemma-3-27b-it")


@pytest.fixture()
def service():
    from app.backboard_service import BackboardService
    svc = BackboardService()
    svc.enabled = True
    return svc


def _make_thread(thread_id: str = "thread-aaa"):
    t = MagicMock()
    t.thread_id = thread_id
    return t


def _make_response(
    content: str = "ok",
    thread_id: str = "thread-aaa",
    memory_operation_id: str | None = "op-123",
    retrieved_memories: list | None = None,
    model_provider: str = "openrouter",
    model_name: str = "google/gemma-3-27b-it",
):
    last_msg: dict[str, Any] = {
        "content": content,
        "thread_id": thread_id,
        "memory_operation_id": memory_operation_id,
        "retrieved_memories": retrieved_memories,
        "model_provider": model_provider,
        "model_name": model_name,
        "status": "COMPLETED",
    }
    resp = MagicMock()
    resp.messages = [last_msg]
    resp.content = content
    return resp


def _make_op_status(status: str, result_count: int = 1, memory_ids: list | None = None):
    op = MagicMock()
    op.operation_id = "op-123"
    op.status = status
    op.memory_ids = memory_ids or ["mem-1"]
    op.result_count = result_count
    return op


# ---------------------------------------------------------------------------
# create_thread
# ---------------------------------------------------------------------------

class TestCreateThread:
    @pytest.mark.asyncio
    async def test_returns_thread_id_string(self, service):
        mock_client = AsyncMock()
        mock_client.create_thread = AsyncMock(return_value=_make_thread("thread-xyz"))
        service.client = mock_client

        result = await service.create_thread()
        assert result == "thread-xyz"

    @pytest.mark.asyncio
    async def test_passes_assistant_id(self, service):
        mock_client = AsyncMock()
        mock_client.create_thread = AsyncMock(return_value=_make_thread("t1"))
        service.client = mock_client

        await service.create_thread()
        mock_client.create_thread.assert_called_once_with(
            assistant_id="00000000-0000-0000-0000-000000000001"
        )

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, service):
        mock_client = AsyncMock()
        mock_client.create_thread = AsyncMock(side_effect=RuntimeError("network error"))
        service.client = mock_client

        result = await service.create_thread()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self):
        from app.backboard_service import BackboardService
        svc = BackboardService()
        svc.enabled = False

        result = await svc.create_thread()
        assert result is None


# ---------------------------------------------------------------------------
# send_in_thread
# ---------------------------------------------------------------------------

class TestSendInThread:
    @pytest.mark.asyncio
    async def test_returns_ok_status_on_success(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_make_response(
            content="Here's your mission.",
            thread_id="thread-aaa",
            memory_operation_id="op-999",
        ))
        service.client = mock_client

        result = await service.send_in_thread("Do task", "thread-aaa")
        assert result["status"] == "ok"
        assert result["content"] == "Here's your mission."

    @pytest.mark.asyncio
    async def test_uses_given_thread_id(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_make_response(thread_id="thread-bbb"))
        service.client = mock_client

        await service.send_in_thread("Do task", "thread-bbb")

        call_kwargs = mock_client.send_message.call_args.kwargs
        assert call_kwargs["thread_id"] == "thread-bbb"

    @pytest.mark.asyncio
    async def test_passes_memory_auto(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_make_response())
        service.client = mock_client

        await service.send_in_thread("Do task", "thread-aaa")

        call_kwargs = mock_client.send_message.call_args.kwargs
        assert call_kwargs["memory"] == "Auto"

    @pytest.mark.asyncio
    async def test_passes_correct_assistant_id(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_make_response())
        service.client = mock_client

        await service.send_in_thread("Do task", "thread-aaa")

        call_kwargs = mock_client.send_message.call_args.kwargs
        assert call_kwargs["assistant_id"] == "00000000-0000-0000-0000-000000000001"

    @pytest.mark.asyncio
    async def test_extracts_memory_operation_id(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_make_response(
            memory_operation_id="op-special-42"
        ))
        service.client = mock_client

        result = await service.send_in_thread("Do task", "thread-aaa")
        assert result["memory_operation_id"] == "op-special-42"

    @pytest.mark.asyncio
    async def test_extracts_retrieved_memories(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=_make_response(
            retrieved_memories=[{"content": "prefers short instructions"}]
        ))
        service.client = mock_client

        result = await service.send_in_thread("Do task", "thread-aaa")
        assert result["retrieved_memories"] == [{"content": "prefers short instructions"}]

    @pytest.mark.asyncio
    async def test_returns_api_error_on_exception(self, service):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(side_effect=RuntimeError("connection failed"))
        service.client = mock_client

        result = await service.send_in_thread("Do task", "thread-aaa")
        assert result["status"] == "api_error"
        assert result["content"] is None

    @pytest.mark.asyncio
    async def test_returns_disabled_when_no_client(self):
        from app.backboard_service import BackboardService
        svc = BackboardService()
        svc.enabled = False

        result = await svc.send_in_thread("Do task", "thread-aaa")
        assert result["status"] == "disabled"


# ---------------------------------------------------------------------------
# check_memory_operation
# ---------------------------------------------------------------------------

class TestCheckMemoryOperation:
    @pytest.mark.asyncio
    async def test_returns_correct_shape(self, service):
        mock_client = AsyncMock()
        mock_client.get_memory_operation_status = AsyncMock(
            return_value=_make_op_status("completed", result_count=2)
        )
        service.client = mock_client

        result = await service.check_memory_operation("op-123")
        assert result["operation_id"] == "op-123"
        assert result["status"] == "completed"
        assert result["result_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_unavailable_on_exception(self, service):
        mock_client = AsyncMock()
        mock_client.get_memory_operation_status = AsyncMock(
            side_effect=Exception("404")
        )
        service.client = mock_client

        result = await service.check_memory_operation("op-999")
        assert result["status"] == "unavailable"


# ---------------------------------------------------------------------------
# poll_memory_operation
# ---------------------------------------------------------------------------

class TestPollMemoryOperation:
    @pytest.mark.asyncio
    async def test_returns_immediately_on_completed(self, service):
        mock_client = AsyncMock()
        mock_client.get_memory_operation_status = AsyncMock(
            return_value=_make_op_status("completed")
        )
        service.client = mock_client

        result = await service.poll_memory_operation("op-123", timeout_seconds=5.0)
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_returns_on_failed_status(self, service):
        mock_client = AsyncMock()
        mock_client.get_memory_operation_status = AsyncMock(
            return_value=_make_op_status("failed")
        )
        service.client = mock_client

        result = await service.poll_memory_operation("op-123", timeout_seconds=5.0)
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_handles_unavailable(self, service):
        mock_client = AsyncMock()
        mock_client.get_memory_operation_status = AsyncMock(
            side_effect=Exception("network error")
        )
        service.client = mock_client

        result = await service.poll_memory_operation("op-123", timeout_seconds=2.0)
        assert result["status"] == "unavailable"


# ---------------------------------------------------------------------------
# list_memories
# ---------------------------------------------------------------------------

class TestListMemories:
    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self, service):
        mem = MagicMock()
        mem.id = "mem-001"
        mem.content = "Prefers 10-minute tasks"
        mem.created_at = None

        mock_result = MagicMock()
        mock_result.memories = [mem]

        mock_client = AsyncMock()
        mock_client.get_memories = AsyncMock(return_value=mock_result)
        service.client = mock_client

        result = await service.list_memories()
        assert len(result) == 1
        assert result[0]["id"] == "mem-001"
        assert result[0]["content"] == "Prefers 10-minute tasks"

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_exception(self, service):
        mock_client = AsyncMock()
        mock_client.get_memories = AsyncMock(side_effect=RuntimeError("api down"))
        service.client = mock_client

        result = await service.list_memories()
        assert result == []


# ---------------------------------------------------------------------------
# search_memories
# ---------------------------------------------------------------------------

class TestSearchMemories:
    @pytest.mark.asyncio
    async def test_returns_list_on_success(self, service):
        mock_client = AsyncMock()
        mock_client.search_memories = AsyncMock(return_value={
            "memories": [{"id": "m1", "content": "short tasks", "score": 0.95}]
        })
        service.client = mock_client

        result = await service.search_memories("10-minute focus")
        assert len(result) == 1
        assert result[0]["content"] == "short tasks"
        assert result[0]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_exception(self, service):
        mock_client = AsyncMock()
        mock_client.search_memories = AsyncMock(side_effect=RuntimeError("timeout"))
        service.client = mock_client

        result = await service.search_memories("something")
        assert result == []

    @pytest.mark.asyncio
    async def test_passes_assistant_id(self, service):
        mock_client = AsyncMock()
        mock_client.search_memories = AsyncMock(return_value={"memories": []})
        service.client = mock_client

        await service.search_memories("query text", limit=3)
        mock_client.search_memories.assert_called_once_with(
            assistant_id="00000000-0000-0000-0000-000000000001",
            query="query text",
            limit=3,
        )
