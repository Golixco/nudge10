#!/usr/bin/env python3
"""
smoke_test_mission.py — Real Backboard/Gemma smoke test for Nudge10.

Makes ONE real call to the provisioned Nudge10 assistant using the
configured Gemma model via OpenRouter.

- Uses memory="Auto"
- Uses json_output=True
- Prints only safe structured output
- Never prints BACKBOARD_API_KEY

Exit code 0 on success, 1 on failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = PROJECT_ROOT / ".env"
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ENV_FILE, override=False)
except ImportError:
    sys.exit("ERROR: python-dotenv not installed.")

# Test task — harmless and representative
SMOKE_TASK = "Finish my DBMS assignment"
SMOKE_MINUTES = 10

MISSION_PROMPT = (
    f"Create exactly one realistic {SMOKE_MINUTES}-minute focus mission from this task:\n"
    f"TASK: {SMOKE_TASK}\n\n"
    f"Rules:\n"
    f"- title must be short (under 8 words)\n"
    f"- action must be ONE concrete thing, not a list of steps\n"
    f"- action must be realistically finishable in {SMOKE_MINUTES} minutes\n"
    f"- reason must be one sentence explaining why this is the right first step\n"
    f"- do not give generic advice\n"
    f"- do not write a motivational essay\n\n"
    f"Return ONLY valid JSON:\n"
    f'{{"title": "...", "action": "...", "reason": "..."}}'
)


async def _run() -> None:
    api_key = os.environ.get("BACKBOARD_API_KEY", "")
    assistant_id = os.environ.get("BACKBOARD_ASSISTANT_ID", "")
    provider = os.environ.get("BACKBOARD_MODEL_PROVIDER", "openrouter")
    model = os.environ.get("BACKBOARD_MODEL_NAME", "google/gemma-3-27b-it")

    if not api_key:
        sys.exit("ERROR: BACKBOARD_API_KEY not set.")
    if not assistant_id:
        sys.exit("ERROR: BACKBOARD_ASSISTANT_ID not set. Run setup_backboard.py first.")

    try:
        from backboard import BackboardClient
    except ImportError:
        sys.exit("ERROR: backboard-sdk not installed.")

    client = BackboardClient(api_key=api_key)

    print("[smoke] Starting real Backboard/Gemma mission test...")
    print(f"[smoke] Assistant ID : {assistant_id}")
    print(f"[smoke] Provider     : {provider}")
    print(f"[smoke] Model        : {model}")
    print(f"[smoke] Task         : {SMOKE_TASK}")
    print(f"[smoke] Memory mode  : Auto")
    print()

    # Get current memory count before the call
    mem_count = None
    try:
        result = await client.get_memories(assistant_id=assistant_id)
        if hasattr(result, "memories"):
            mem_count = len(result.memories)
        elif hasattr(result, "items"):
            mem_count = len(result.items)
    except Exception:
        mem_count = None

    # Make the real call
    try:
        response = await client.send_message(
            MISSION_PROMPT,
            assistant_id=assistant_id,
            llm_provider=provider,
            model_name=model,
            memory="Auto",
            json_output=True,
            stream=False,
        )
    except Exception as exc:
        await client.aclose()
        sys.exit(f"ERROR: send_message failed — {type(exc).__name__}: {exc}")

    raw_content = response.content
    await client.aclose()

    print("[smoke] Raw model response received.")
    print()

    # Parse and validate
    if not raw_content:
        sys.exit("ERROR: Model returned empty content.")

    text = raw_content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:]).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start:end+1])
            except Exception:
                sys.exit(f"ERROR: Could not parse JSON from model output:\n{raw_content[:300]}")
        else:
            sys.exit(f"ERROR: No JSON object found in model output:\n{raw_content[:300]}")

    required = ("title", "action", "reason")
    missing = [k for k in required if k not in parsed]
    if missing:
        sys.exit(f"ERROR: Model JSON missing fields: {missing}\nGot: {list(parsed.keys())}")

    print("=" * 60)
    print("  SMOKE TEST — RESULT")
    print("=" * 60)
    print(f"  AI call succeeded   : YES")
    print(f"  Assistant ID used   : {assistant_id}")
    print(f"  Model used          : {model}")
    print(f"  Provider            : {provider}")
    print(f"  Memory count before : {mem_count if mem_count is not None else 'unavailable'}")
    print()
    print("  Mission JSON:")
    print(f"    title  : {parsed['title']}")
    print(f"    action : {parsed['action']}")
    print(f"    reason : {parsed['reason']}")
    print("=" * 60)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
