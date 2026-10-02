"""
tests/test_preference_memory.py — Unit tests for BackboardService preference memory methods.

Tests:
  save_user_preference:
    - stores preference with correct assistant_id
    - passes metadata with source, confidence, type
    - returns success=True and memory_id on success
    - returns success=False on API exception
    - returns success=False on empty preference (no API call made)
    - returns success=False when service is disabled
    - does not expose API key in any result

  delete_memory_by_id:
    - calls delete_memory with correct assistant_id and memory_id
    - returns True on success
    - returns False on exception

  delete_memories_matching:
    - finds and deletes memories that match the substring
    - skips memories that do not match
    - returns count of deleted memories
    - returns 0 for empty pattern
    - returns 0 when list_memories returns empty

  search_user_memories (alias for search_memories):
    - passes assistant_id and query and limit
    - returns list of dicts with id, content, score, metadata
    - returns [] on failure

  Auto-memory behavior:
    - send_in_thread passes memory="Auto"
    - retrieved_memories is extracted from the raw message dict

  No secret leakage:
    - save_user_preference result never contains api_key value
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "backboard_api_key", "FAKE-KEY-DO-NOT-LOG")
    monkeypatch.setattr(settings, "backboard_assistant_id", "asst-0000-0000-0000-000000000001")
    monkeypatch.setattr(settings, "backboard_model_provider", "openrouter")
    monkeypatch.setattr(settings, "backboard_model_name", "google/gemma-3-27b-it")


@pytest.fixture()
def service():
    from app.backboard_service import BackboardService
    svc = BackboardService()
    svc.enabled = True
    return svc


# ---------------------------------------------------------------------------
# save_user_preference — success
# ---------------------------------------------------------------------------

class TestSaveUserPreference:
    @pytest.mark.asyncio
    async def test_returns_success_true_and_memory_id(self, service):
        mock_client = AsyncMock()
        mock_client.add_memory = AsyncMock(return_value={"memory_id": "mem-abc123"})
        service.client = mock_client

        result = await service.save_user_preference("User prefers short tasks.")
        assert result["success"] is True
        assert result["memory_id"] == "mem-abc123"

    @pytest.mark.asyncio
    async def test_passes_assistant_id(self, service):
        mock_client = AsyncMock()
        mock_client.add_memory = AsyncMock(return_value={"memory_id": "m1"})
        service.client = mock_client

        await service.save_user_preference("Preference A")
        mock_client.add_memory.assert_called_once()
        call_kwargs = mock_client.add_memory.call_args.kwargs
        assert call_kwargs["assistant_id"] == "asst-0000-0000-0000-000000000001"

    @pytest.mark.asyncio
    async def test_passes_correct_content(self, service):
        mock_client = AsyncMock()
        mock_client.add_memory = AsyncMock(return_value={"memory_id": "m1"})
        service.client = mock_client

        await service.save_user_preference("  User dislikes essays.  ")
        call_kwargs = mock_client.add_memory.call_args.kwargs
        # Content should be stripped
        assert call_kwargs["content"] == "User dislikes essays."

    @pytest.mark.asyncio
    async def test_passes_correct_metadata(self, service):
        mock_client = AsyncMock()
        mock_client.add_memory = AsyncMock(return_value={"memory_id": "m1"})
        service.client = mock_client

        await service.save_user_preference("Preference X", confidence="high")
        meta = mock_client.add_memory.call_args.kwargs["metadata"]
        assert meta["source"] == "user_preference"
        assert meta["confidence"] == "high"
        assert meta["type"] == "explicit"

    @pytest.mark.asyncio
    async def test_returns_failure_on_api_exception(self, service):
        mock_client = AsyncMock()
        mock_client.add_memory = AsyncMock(side_effect=RuntimeError("server error"))
        service.client = mock_client

        result = await service.save_user_preference("Preference Y")
        assert result["success"] is False
        assert result["memory_id"] is None

    @pytest.mark.asyncio
    async def test_returns_failure_on_empty_preference(self, service):
        mock_client = AsyncMock()
        service.client = mock_client

        result = await service.save_user_preference("   ")
        assert result["success"] is False
        # Must NOT call the API for empty input
        mock_client.add_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_failure_when_disabled(self):
        from app.backboard_service import BackboardService
        svc = BackboardService()
        svc.enabled = False

        result = await svc.save_user_preference("User likes X.")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_result_does_not_contain_api_key(self, service):
        mock_client = AsyncMock()
        mock_client.add_memory = AsyncMock(return_value={"memory_id": "m1"})
        service.client = mock_client

        result = await service.save_user_preference("Preference Z")
        result_str = str(result)
        assert "FAKE-KEY-DO-NOT-LOG" not in result_str


# ---------------------------------------------------------------------------
# delete_memory_by_id
# ---------------------------------------------------------------------------

class TestDeleteMemoryById:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, service):
        mock_client = AsyncMock()
        mock_client.delete_memory = AsyncMock(return_value={"success": True})
        service.client = mock_client

        result = await service.delete_memory_by_id("mem-xyz")
        assert result is True

    @pytest.mark.asyncio
    async def test_passes_correct_ids(self, service):
        mock_client = AsyncMock()
        mock_client.delete_memory = AsyncMock(return_value={"success": True})
        service.client = mock_client

        await service.delete_memory_by_id("mem-target")
        mock_client.delete_memory.assert_called_once_with(
            assistant_id="asst-0000-0000-0000-000000000001",
            memory_id="mem-target",
        )

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, service):
        mock_client = AsyncMock()
        mock_client.delete_memory = AsyncMock(side_effect=Exception("404"))
        service.client = mock_client

        result = await service.delete_memory_by_id("mem-bad")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_disabled(self):
        from app.backboard_service import BackboardService
        svc = BackboardService()
        svc.enabled = False

        result = await svc.delete_memory_by_id("mem-id")
        assert result is False


# ---------------------------------------------------------------------------
# delete_memories_matching
# ---------------------------------------------------------------------------

def _make_memory_list(*contents):
    return [{"id": f"mem-{i:03d}", "content": c, "created_at": None}
            for i, c in enumerate(contents)]


class TestDeleteMemoriesMatching:
    @pytest.mark.asyncio
    async def test_deletes_matching_memories(self, service):
        mock_client = AsyncMock()
        mock_client.get_memories = AsyncMock()

        # list_memories uses get_memories; mock it
        mock_result = MagicMock()
        mem_a = MagicMock(); mem_a.id = "mem-001"; mem_a.content = "machine learning project"; mem_a.created_at = None
        mem_b = MagicMock(); mem_b.id = "mem-002"; mem_b.content = "User prefers direct style"; mem_b.created_at = None
        mock_result.memories = [mem_a, mem_b]
        mock_client.get_memories = AsyncMock(return_value=mock_result)
        mock_client.delete_memory = AsyncMock(return_value={"success": True})
        service.client = mock_client

        count = await service.delete_memories_matching("machine learning")
        assert count == 1
        mock_client.delete_memory.assert_called_once_with(
            assistant_id="asst-0000-0000-0000-000000000001",
            memory_id="mem-001",
        )

    @pytest.mark.asyncio
    async def test_skips_non_matching_memories(self, service):
        mock_client = AsyncMock()
        mock_result = MagicMock()
        mem = MagicMock(); mem.id = "mem-001"; mem.content = "User prefers short tasks"; mem.created_at = None
        mock_result.memories = [mem]
        mock_client.get_memories = AsyncMock(return_value=mock_result)
        mock_client.delete_memory = AsyncMock()
        service.client = mock_client

        count = await service.delete_memories_matching("machine learning")
        assert count == 0
        mock_client.delete_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_pattern(self, service):
        mock_client = AsyncMock()
        service.client = mock_client

        count = await service.delete_memories_matching("   ")
        assert count == 0
        mock_client.delete_memory = AsyncMock()
        mock_client.delete_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_memories(self, service):
        mock_client = AsyncMock()
        mock_result = MagicMock()
        mock_result.memories = []
        mock_client.get_memories = AsyncMock(return_value=mock_result)
        service.client = mock_client

        count = await service.delete_memories_matching("anything")
        assert count == 0


# ---------------------------------------------------------------------------
# search_user_memories (alias for search_memories)
# ---------------------------------------------------------------------------

class TestSearchUserMemories:
    @pytest.mark.asyncio
    async def test_returns_list_with_metadata(self, service):
        mock_client = AsyncMock()
        mock_client.search_memories = AsyncMock(return_value={
            "memories": [
                {
                    "id": "m1",
                    "content": "User prefers direct instructions",
                    "score": 0.91,
                    "metadata": {"source": "user_preference", "confidence": "high"},
                }
            ],
            "total_count": 1,
        })
        service.client = mock_client

        results = await service.search_user_memories("direct instructions", limit=3)
        assert len(results) == 1
        assert results[0]["content"] == "User prefers direct instructions"
        assert results[0]["score"] == 0.91
        assert results[0]["metadata"]["source"] == "user_preference"

    @pytest.mark.asyncio
    async def test_passes_correct_params(self, service):
        mock_client = AsyncMock()
        mock_client.search_memories = AsyncMock(return_value={"memories": []})
        service.client = mock_client

        await service.search_user_memories("focus habits", limit=4)
        mock_client.search_memories.assert_called_once_with(
            assistant_id="asst-0000-0000-0000-000000000001",
            query="focus habits",
            limit=4,
        )

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_exception(self, service):
        mock_client = AsyncMock()
        mock_client.search_memories = AsyncMock(side_effect=RuntimeError("timeout"))
        service.client = mock_client

        results = await service.search_user_memories("anything")
        assert results == []


# ---------------------------------------------------------------------------
# Auto-memory and retrieved_memories in send_in_thread
# ---------------------------------------------------------------------------

class TestAutoMemoryInThread:
    @pytest.mark.asyncio
    async def test_retrieved_memories_from_response(self, service):
        retrieved = [{"content": "User prefers direct style", "score": 0.95}]
        last_msg = {
            "content": "Here is your mission.",
            "thread_id": "thread-xxx",
            "memory_operation_id": None,
            "retrieved_memories": retrieved,
            "model_provider": "openrouter",
            "model_name": "google/gemma-3-27b-it",
            "status": "COMPLETED",
        }
        mock_resp = MagicMock()
        mock_resp.messages = [last_msg]

        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=mock_resp)
        service.client = mock_client

        result = await service.send_in_thread("Give me a mission", "thread-xxx")
        assert result["retrieved_memories"] == retrieved

    @pytest.mark.asyncio
    async def test_send_in_thread_passes_memory_auto(self, service):
        last_msg = {
            "content": "ok", "thread_id": "thread-yyy",
            "memory_operation_id": None, "retrieved_memories": None,
            "model_provider": "openrouter", "model_name": "google/gemma-3-27b-it",
        }
        mock_resp = MagicMock()
        mock_resp.messages = [last_msg]

        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=mock_resp)
        service.client = mock_client

        await service.send_in_thread("Query", "thread-yyy")
        call_kwargs = mock_client.send_message.call_args.kwargs
        assert call_kwargs["memory"] == "Auto"
