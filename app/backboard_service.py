import json
import logging
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
You are Nudge10, a blunt but kind anti-procrastination focus companion.
Your job is to help one specific person start and finish tiny work sessions.
Never give long motivational speeches. Be concise, practical, and non-judgmental.
Prefer one concrete next action over a productivity plan.
""".strip()


def _extract_json(content: str) -> dict[str, Any] | None:
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
    # Fallback to substring matching first '{' to last '}'
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

    async def _send(self, prompt: str, json_output: bool = True) -> str | None:
        client = await self._get_client()
        if client is None:
            return None

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
        return response.content

    async def create_mission(self, task: str, minutes: int) -> dict[str, Any] | None:
        prompt = f"""
Create exactly one realistic {minutes}-minute mission from this larger task:
TASK: {task}

Return ONLY valid JSON with this exact shape:
{{
  "title": "short mission title",
  "action": "the one thing the person should do during this session",
  "why": "one short sentence explaining why this is a good first step"
}}
""".strip()
        try:
            content = await self._send(prompt, json_output=True)
            if not content:
                return None
            parsed = _extract_json(content)
            if not parsed or not all(k in parsed for k in ("title", "action", "why")):
                return None
            return parsed
        except Exception:
            logger.exception("Backboard mission generation failed")
            return None

    async def generate_nudge(
        self,
        task: str,
        elapsed_minutes: int,
        distraction: str,
        distraction_count: int,
    ) -> dict[str, str] | None:
        prompt = f"""
The user is in a 10-minute focus session.
Task: {task}
Minutes elapsed: {elapsed_minutes}
Distraction detected: {distraction}
Distraction count in this session: {distraction_count}

Give a short intervention that gets them back to the task without shaming them.
Return ONLY valid JSON:
{{
  "message": "one or two short sentences",
  "action": "a tiny concrete action they should do next"
}}
""".strip()
        try:
            content = await self._send(prompt, json_output=True)
            if not content:
                return None
            parsed = _extract_json(content)
            if not parsed or not all(k in parsed for k in ("message", "action")):
                return None
            return {"message": str(parsed["message"]), "action": str(parsed["action"])}
        except Exception:
            logger.exception("Backboard nudge generation failed")
            return None

    async def remember_session(self, summary: str) -> bool:
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


backboard = BackboardService()
