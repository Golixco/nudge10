#!/usr/bin/env python3
"""
verify_backboard.py — Safe assistant verification for Nudge10.

Retrieves the assistant by ID and prints only safe metadata.
Does NOT send an LLM request.
Does NOT print BACKBOARD_API_KEY.
Does NOT print the system prompt in full (prompt-leak risk).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ENV_FILE, override=False)
except ImportError:
    sys.exit("ERROR: python-dotenv not installed. Run: pip install python-dotenv")


async def _run(api_key: str, assistant_id: str) -> None:
    from backboard import BackboardClient

    client = BackboardClient(api_key=api_key)
    print(f"[verify] Fetching assistant {assistant_id} ...")

    try:
        assistant = await client.get_assistant(assistant_id)
    except Exception as exc:
        sys.exit(f"ERROR: Could not retrieve assistant — {exc}")
    finally:
        await client.aclose()

    has_system_prompt = bool((assistant.system_prompt or "").strip())
    has_fact_extraction = bool((assistant.custom_fact_extraction_prompt or "").strip())
    has_update_memory = bool((assistant.custom_update_memory_prompt or "").strip())
    system_prompt_preview = (
        (assistant.system_prompt or "")[:80].replace("\n", " ").strip() + "..."
        if has_system_prompt else "(none)"
    )

    print()
    print("=" * 60)
    print("  ASSISTANT VERIFICATION")
    print("=" * 60)
    print(f"  Name                      : {assistant.name}")
    print(f"  ID                        : {assistant.assistant_id}")
    print(f"  System prompt configured  : {'YES' if has_system_prompt else 'NO'}")
    print(f"  System prompt preview     : {system_prompt_preview}")
    print(f"  custom_fact_extraction    : {'YES' if has_fact_extraction else 'NO'}")
    print(f"  custom_update_memory      : {'YES' if has_update_memory else 'NO'}")
    print("=" * 60)

    failures = []
    if assistant.name != "Nudge10":
        failures.append(f"Name mismatch: expected 'Nudge10', got '{assistant.name}'")
    if not has_system_prompt:
        failures.append("System prompt is empty")
    if not has_fact_extraction:
        failures.append("custom_fact_extraction_prompt is empty")
    if not has_update_memory:
        failures.append("custom_update_memory_prompt is empty")

    if failures:
        print("\n[verify] FAILED checks:")
        for f in failures:
            print(f"  x {f}")
        sys.exit(1)

    print("\n[verify] All checks PASSED.")


def main() -> None:
    api_key = os.environ.get("BACKBOARD_API_KEY", "")
    assistant_id = os.environ.get("BACKBOARD_ASSISTANT_ID", "")

    if not api_key:
        sys.exit("ERROR: BACKBOARD_API_KEY is not set.")
    if not assistant_id:
        sys.exit(
            "ERROR: BACKBOARD_ASSISTANT_ID is not set.\n"
            "Run  python scripts/setup_backboard.py  first."
        )

    try:
        from backboard import BackboardClient  # noqa: F401
    except ImportError:
        sys.exit("ERROR: backboard-sdk not installed.")

    asyncio.run(_run(api_key, assistant_id))


if __name__ == "__main__":
    main()
