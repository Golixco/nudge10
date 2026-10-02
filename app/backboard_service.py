"""
backboard_service.py — Nudge10 AI service layer.

Uses backboard-sdk==1.5.19 (all client methods are async).

send_message signature (relevant params):
  send_message(content, *, assistant_id, system_prompt, llm_provider,
               model_name, memory, json_output, thread_id, stream)
               -> ChatMessagesResponse
  response.content -> Optional[str]  (proxies messages[-1]["content"])

Raw message dict keys (confirmed from live API):
  thread_id, assistant_id, content, memory_operation_id,
  retrieved_memories, model_provider, model_name, status,
  input_tokens, output_tokens, message_id, run_id, created_at

Memory operations are ASYNC on the Backboard platform:
  memory_operation_id is returned in the response when Auto memory
  causes a write/update. Poll get_memory_operation_status(operation_id)
  until status is "completed" or a timeout is reached.

Thread API:
  create_thread(assistant_id)  -> Thread (has .thread_id)
  send_message(..., thread_id=...)  -> continues that thread

Mission JSON contract returned by the model:
  { "title": str, "action": str, "reason": str }

The API response uses "why" (stable frontend contract) mapped from "reason".
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from .config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical system prompt (must match what was provisioned via setup_backboard.py)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are Nudge10, a concise anti-doomscrolling focus companion.\n\n"
    "Your purpose is to help one user overcome procrastination by making "
    "productive work feel small enough to start.\n\n"
    "Core behavior:\n"
    "- Break overwhelming tasks into one concrete action that can realistically "
    "be completed in about 10 minutes.\n"
    "- Prefer actionable instructions over motivational speeches.\n"
    "- Be direct, calm, encouraging, and slightly human.\n"
    "- Never shame, insult, guilt-trip, or manipulate the user.\n"
    "- When the user gets distracted, acknowledge the distraction without "
    "moralizing and give one immediate next action.\n"
    "- Keep normal responses short.\n"
    "- Adapt to the user's preferences and behavior when reliable information "
    "is available in memory.\n"
    "- Do not invent memories.\n"
    "- Do not claim to know browsing activity unless the application explicitly "
    "provides it in the current request.\n"
    "- Protect privacy and do not request unnecessary personal information.\n"
    "- When asked to create a focus mission, return only the requested "
    "structured fields.\n"
    "- When asked to create a distraction nudge, return only the requested "
    "structured fields.\n\n"
    "You are part of a productivity tool, not a therapist, doctor, or "
    "mental-health professional."
)


# ---------------------------------------------------------------------------
# Pydantic validators for raw model JSON — never trust the model directly
# ---------------------------------------------------------------------------

class _MissionRaw(BaseModel):
    """Strict shape expected from the LLM for a focus mission."""
    title: str
    action: str
    reason: str


class _NudgeRaw(BaseModel):
    """Strict shape expected from the LLM for a distraction nudge."""
    message: str
    action: str


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _extract_json(content: str) -> dict[str, Any] | None:
    """Parse JSON from model output, tolerating markdown code fences."""
    text = content.strip()
    # Strip markdown code blocks if present
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    # Fallback: find first '{' to last '}'
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BackboardService:
    def __init__(self) -> None:
        self.enabled = bool(settings.backboard_api_key and settings.backboard_assistant_id)
        self.client = None

    async def _get_client(self):
        if not self.enabled:
            return None
        if self.client is None:
            from backboard import BackboardClient
            self.client = BackboardClient(api_key=settings.backboard_api_key)
        return self.client

    async def _send(self, prompt: str, json_output: bool = True) -> tuple[str | None, str]:
        """
        Send a message to the Nudge10 assistant.

        Returns (content, status) where status is one of:
          "ok", "no_content", "api_error", "disabled"
        """
        client = await self._get_client()
        if client is None:
            return None, "disabled"

        try:
            response = await client.send_message(
                prompt,
                assistant_id=settings.backboard_assistant_id,
                system_prompt=SYSTEM_PROMPT,
                llm_provider=settings.backboard_model_provider,
                model_name=settings.backboard_model_name,
                memory="Auto",
                json_output=json_output,
                stream=False,
            )
            content = response.content
            if not content:
                return None, "no_content"
            return content, "ok"
        except Exception as exc:
            # Log safe technical details without exposing credentials
            logger.error(
                "Backboard send_message failed | assistant=%s | provider=%s | model=%s | error=%s",
                settings.backboard_assistant_id,
                settings.backboard_model_provider,
                settings.backboard_model_name,
                type(exc).__name__,
            )
            return None, "api_error"

    async def create_mission(self, task: str, minutes: int) -> dict[str, Any] | None:
        """
        Generate a single focused mission from a task description.

        Returns a dict with keys: title, action, reason (maps to why in API response).
        Returns None on any failure — caller must use fallback.

        Model is asked for: { "title": str, "action": str, "reason": str }
        """
        prompt = (
            f"Create exactly one realistic {minutes}-minute focus mission from this task:\n"
            f"TASK: {task}\n\n"
            f"Rules:\n"
            f"- title must be short (under 8 words)\n"
            f"- action must be ONE concrete thing, not a list of steps\n"
            f"- action must be realistically finishable in {minutes} minutes\n"
            f"- reason must be one sentence explaining why this is the right first step\n"
            f"- do not give generic advice like 'break it into smaller tasks'\n"
            f"- do not write a motivational essay\n"
            f"- if relevant memory is available, use it; never invent memories\n\n"
            f"Return ONLY valid JSON with this exact shape:\n"
            f'{{"title": "...", "action": "...", "reason": "..."}}'
        )

        content, status = await self._send(prompt, json_output=True)

        logger.debug(
            "mission | assistant=%s | provider=%s | model=%s | status=%s",
            settings.backboard_assistant_id,
            settings.backboard_model_provider,
            settings.backboard_model_name,
            status,
        )

        if not content:
            return None

        raw = _extract_json(content)
        if not raw:
            logger.warning("mission | malformed JSON from model | content_preview=%.80r", content)
            return None

        try:
            validated = _MissionRaw.model_validate(raw)
        except ValidationError as exc:
            logger.warning("mission | Pydantic validation failed | errors=%s", exc.errors())
            return None

        return {
            "title": validated.title.strip(),
            "action": validated.action.strip(),
            "reason": validated.reason.strip(),
        }

    async def generate_nudge(
        self,
        task: str,
        elapsed_minutes: int,
        distraction: str,
        distraction_count: int,
    ) -> dict[str, str] | None:
        """
        Generate a distraction intervention nudge.

        Returns dict with keys: message, action. Returns None on failure.
        """
        prompt = (
            f"The user is in a {10}-minute focus session.\n"
            f"Task: {task}\n"
            f"Minutes elapsed: {elapsed_minutes}\n"
            f"Distraction detected: {distraction}\n"
            f"Distraction count in this session: {distraction_count}\n\n"
            f"Give a short intervention that gets them back to the task without shaming them.\n"
            f"Return ONLY valid JSON:\n"
            f'{{"message": "one or two short sentences", "action": "a tiny concrete action they should do next"}}'
        )

        content, status = await self._send(prompt, json_output=True)

        logger.debug(
            "nudge | assistant=%s | provider=%s | model=%s | status=%s",
            settings.backboard_assistant_id,
            settings.backboard_model_provider,
            settings.backboard_model_name,
            status,
        )

        if not content:
            return None

        raw = _extract_json(content)
        if not raw:
            logger.warning("nudge | malformed JSON from model | content_preview=%.80r", content)
            return None

        try:
            validated = _NudgeRaw.model_validate(raw)
        except ValidationError as exc:
            logger.warning("nudge | Pydantic validation failed | errors=%s", exc.errors())
            return None

        return {
            "message": validated.message.strip(),
            "action": validated.action.strip(),
        }

    async def remember_session(self, summary: str) -> bool:
        """Store a durable session summary in Backboard memory."""
        if not summary or not summary.strip():
            return False
        client = await self._get_client()
        if client is None:
            return False
        try:
            await client.add_memory(
                assistant_id=settings.backboard_assistant_id,
                content=summary.strip(),
                metadata={"source": "nudge10-session"},
            )
            return True
        except Exception:
            logger.exception("Backboard memory write failed")
            return False

    async def get_memory_count(self) -> int | None:
        """Return the number of stored memories, or None if unavailable."""
        client = await self._get_client()
        if client is None:
            return None
        try:
            result = await client.get_memories(assistant_id=settings.backboard_assistant_id)
            if hasattr(result, "memories"):
                return len(result.memories)
            if hasattr(result, "items"):
                return len(result.items)
            return None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Thread management
    # ------------------------------------------------------------------

    async def create_thread(self) -> str | None:
        """
        Create a new conversation thread under the Nudge10 assistant.

        Returns the thread_id string, or None on failure.
        """
        client = await self._get_client()
        if client is None:
            return None
        try:
            thread = await client.create_thread(
                assistant_id=settings.backboard_assistant_id
            )
            thread_id = str(thread.thread_id)
            logger.debug("created thread %s", thread_id)
            return thread_id
        except Exception:
            logger.exception("create_thread failed")
            return None

    # ------------------------------------------------------------------
    # Memory operation status
    # ------------------------------------------------------------------

    async def check_memory_operation(self, operation_id: str) -> dict[str, Any]:
        """
        Fetch the current status of a memory operation.

        Returns a dict:
          {
            "operation_id": str,
            "status": str,           # "pending" | "completed" | "failed"
            "memory_ids": list | None,
            "result_count": int | None,
          }
        Returns {"status": "unavailable"} on error.
        """
        client = await self._get_client()
        if client is None:
            return {"status": "unavailable"}
        try:
            op = await client.get_memory_operation_status(operation_id)
            return {
                "operation_id": op.operation_id,
                "status": op.status,
                "memory_ids": op.memory_ids,
                "result_count": op.result_count,
            }
        except Exception as exc:
            logger.error("check_memory_operation failed: %s", type(exc).__name__)
            return {"status": "unavailable"}

    async def poll_memory_operation(
        self,
        operation_id: str,
        *,
        timeout_seconds: float = 15.0,
        interval_seconds: float = 1.5,
    ) -> dict[str, Any]:
        """
        Poll get_memory_operation_status until complete or timeout.

        Memory operations on Backboard are asynchronous; the operation_id is
        returned in the raw message dict as messages[-1]["memory_operation_id"].

        Returns the final status dict from check_memory_operation.
        """
        import asyncio as _asyncio

        deadline = _asyncio.get_event_loop().time() + timeout_seconds
        while True:
            status = await self.check_memory_operation(operation_id)
            if status.get("status") in ("completed", "failed", "unavailable"):
                return status
            remaining = deadline - _asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning("poll_memory_operation timed out for %s", operation_id)
                return {**status, "status": "timeout"}
            await _asyncio.sleep(min(interval_seconds, remaining))

    # ------------------------------------------------------------------
    # Message sending with thread + memory metadata extraction
    # ------------------------------------------------------------------

    async def send_in_thread(
        self,
        prompt: str,
        thread_id: str,
        *,
        json_output: bool = False,
    ) -> dict[str, Any]:
        """
        Send a message in a specific thread and return safe metadata.

        Returns:
          {
            "content": str | None,
            "thread_id": str | None,
            "memory_operation_id": str | None,
            "retrieved_memories": list | None,
            "model_provider": str | None,
            "model_name": str | None,
            "status": "ok" | "api_error" | "disabled",
          }
        """
        client = await self._get_client()
        if client is None:
            return {"content": None, "status": "disabled"}

        try:
            response = await client.send_message(
                prompt,
                assistant_id=settings.backboard_assistant_id,
                thread_id=thread_id,
                system_prompt=SYSTEM_PROMPT,
                llm_provider=settings.backboard_model_provider,
                model_name=settings.backboard_model_name,
                memory="Auto",
                json_output=json_output,
                stream=False,
            )
            last = response.messages[-1] if response.messages else {}
            return {
                "content": last.get("content"),
                "thread_id": last.get("thread_id"),
                "memory_operation_id": last.get("memory_operation_id"),
                "retrieved_memories": last.get("retrieved_memories"),
                "model_provider": last.get("model_provider"),
                "model_name": last.get("model_name"),
                "status": "ok",
            }
        except Exception as exc:
            logger.error(
                "send_in_thread failed | thread=%s | error=%s",
                thread_id,
                type(exc).__name__,
            )
            return {"content": None, "status": "api_error"}

    # ------------------------------------------------------------------
    # Memory listing and search
    # ------------------------------------------------------------------

    async def list_memories(
        self, *, page: int = 1, page_size: int = 20
    ) -> list[dict[str, Any]]:
        """
        Return a list of stored memory dicts for the Nudge10 assistant.

        Each dict has: id, content, metadata, created_at.
        Never returns raw sensitive information beyond what is stored.
        """
        client = await self._get_client()
        if client is None:
            return []
        try:
            result = await client.get_memories(
                assistant_id=settings.backboard_assistant_id,
                page=page,
                page_size=page_size,
            )
            memories = result.memories if hasattr(result, "memories") else []
            return [
                {
                    "id": str(m.id),
                    "content": m.content,
                    "created_at": str(m.created_at) if m.created_at else None,
                }
                for m in memories
            ]
        except Exception:
            logger.exception("list_memories failed")
            return []

    async def search_memories(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Semantic search over stored memories.

        Returns a list of dicts with keys: id, content, score.
        search_memories SDK returns: {"memories": [...], "total_count": N}
        Each memory item has: id, content, score, metadata, created_at.
        """
        client = await self._get_client()
        if client is None:
            return []
        try:
            result = await client.search_memories(
                assistant_id=settings.backboard_assistant_id,
                query=query,
                limit=limit,
            )
            items = result.get("memories") or []
            return [
                {
                    "id": str(item.get("id", "")),
                    "content": item.get("content", ""),
                    "score": item.get("score"),
                    "metadata": item.get("metadata"),
                }
                for item in items
            ]
        except Exception:
            logger.exception("search_memories failed")
            return []

    # Alias for clarity
    search_user_memories = search_memories

    # ------------------------------------------------------------------
    # Explicit preference storage
    # ------------------------------------------------------------------

    async def save_user_preference(
        self,
        preference: str,
        confidence: str = "high",
    ) -> dict[str, Any]:
        """
        Explicitly store a durable user preference using the manual add_memory API.

        This bypasses Auto memory extraction and guarantees the preference is stored
        verbatim with structured metadata.

        Args:
            preference: Human-readable preference statement.
                        Example: "User prefers 10-minute focus missions."
            confidence: "high" | "medium" | "low" — indicates how certain we are.

        Returns:
            dict with at minimum {"success": bool, "memory_id": str | None}
        add_memory SDK returns: dict with success and memory_id.
        """
        if not preference or not preference.strip():
            return {"success": False, "memory_id": None, "reason": "empty preference"}

        client = await self._get_client()
        if client is None:
            return {"success": False, "memory_id": None, "reason": "disabled"}

        try:
            result = await client.add_memory(
                assistant_id=settings.backboard_assistant_id,
                content=preference.strip(),
                metadata={
                    "source": "user_preference",
                    "confidence": confidence,
                    "type": "explicit",
                },
            )
            memory_id = result.get("memory_id") or result.get("id")
            logger.info(
                "save_user_preference | memory_id=%s | preference=%.60r",
                memory_id,
                preference,
            )
            return {"success": True, "memory_id": memory_id}
        except Exception as exc:
            logger.error("save_user_preference failed: %s", type(exc).__name__)
            return {"success": False, "memory_id": None, "reason": type(exc).__name__}

    async def delete_memory_by_id(self, memory_id: str) -> bool:
        """
        Delete a single memory by its ID.

        Returns True on success, False on failure.
        """
        client = await self._get_client()
        if client is None:
            return False
        try:
            await client.delete_memory(
                assistant_id=settings.backboard_assistant_id,
                memory_id=memory_id,
            )
            logger.info("deleted memory %s", memory_id)
            return True
        except Exception as exc:
            logger.error("delete_memory_by_id failed for %s: %s", memory_id, type(exc).__name__)
            return False

    async def delete_memories_matching(self, content_substring: str) -> int:
        """
        Find and delete all memories whose content contains the given substring.

        Used for surgical cleanup (e.g., removing a misextracted transient fact)
        without resetting all memories.

        Returns the number of memories deleted.
        """
        if not content_substring.strip():
            return 0

        all_memories = await self.list_memories(page_size=100)
        deleted = 0
        for mem in all_memories:
            if content_substring.lower() in (mem.get("content") or "").lower():
                success = await self.delete_memory_by_id(mem["id"])
                if success:
                    deleted += 1
        logger.info(
            "delete_memories_matching | pattern=%.60r | deleted=%d", content_substring, deleted
        )
        return deleted


backboard = BackboardService()
