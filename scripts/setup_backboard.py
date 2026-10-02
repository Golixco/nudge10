#!/usr/bin/env python3
"""
setup_backboard.py — Nudge10 assistant provisioning script.

Idempotent: safe to run multiple times.
- Searches for an existing assistant named "Nudge10".
- Creates one if it does not exist.
- Updates its system prompt and memory prompts if they differ.
- Writes BACKBOARD_ASSISTANT_ID to the local .env file.
- Never prints or exposes BACKBOARD_API_KEY.

SDK: backboard-sdk==1.5.19  (all client methods are async).
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate the project root (.env lives there, not in scripts/)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ENV_FILE, override=False)
except ImportError:
    sys.exit("ERROR: python-dotenv is not installed. Run: pip install python-dotenv")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ASSISTANT_NAME = "Nudge10"

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

CUSTOM_FACT_EXTRACTION_PROMPT = (
    "You are a memory extraction agent for a productivity tool. "
    "Extract ONLY the following categories of durable facts, in priority order:\n"
    "1. EXPLICIT PREFERENCES: Statements where the user says what they like, dislike, prefer, or want. "
    "Example: 'User prefers short, direct instructions.' "
    "Example: 'User dislikes motivational speeches.' "
    "Example: 'User wants tasks broken into 10-minute actions.'\n"
    "2. RECURRING PRODUCTIVITY PATTERNS: Behaviors that repeat across sessions. "
    "Example: 'User frequently abandons sessions after 7 minutes.' "
    "Example: 'User works best in the morning.'\n"
    "3. STABLE WORKING HABITS: Long-term facts about how the user works. "
    "Example: 'User is a computer science student.' "
    "Example: 'User uses a Pomodoro-style timer.'\n"
    "DO NOT EXTRACT:\n"
    "- What the user is currently working on in this session (transient task context). "
    "- Browsing history, URLs, or app usage. "
    "- Passwords, secrets, financial information, or health data. "
    "- Single-session facts with no lasting value (e.g., 'User opened chapter 3 today'). "
    "If nothing qualifies, extract nothing."
)

CUSTOM_UPDATE_MEMORY_PROMPT = (
    "Keep memory concise and useful. "
    "ADD: Durable new preferences or recurring behavioral patterns not already stored. "
    "UPDATE: Existing facts only when the user explicitly corrects or changes a preference. "
    "REMOVE: Facts that are explicitly contradicted by the user. "
    "SKIP: Transient task context (what the user is working on today), "
    "single-session observations, raw browsing events, and sensitive data. "
    "Do not create duplicate memories for preferences already stored. "
    "Do not convert temporary task mentions into lasting memories."
)

ASSISTANT_DESCRIPTION = (
    "Anti-doomscrolling focus companion. Breaks large tasks into 10-minute "
    "missions and delivers gentle distraction nudges."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_env_value(key: str, value: str, env_path: Path) -> None:
    """Write or update a single KEY=value line in .env. Preserves all other lines."""
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")
        return
    content = env_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(content):
        updated = pattern.sub(f"{key}={value}", content)
    else:
        updated = content.rstrip("\n") + f"\n{key}={value}\n"
    env_path.write_text(updated, encoding="utf-8")


def _prompts_differ(assistant, desired_system: str, desired_fact: str, desired_update: str) -> bool:
    return (
        (assistant.system_prompt or "").strip() != desired_system.strip()
        or (assistant.custom_fact_extraction_prompt or "").strip() != desired_fact.strip()
        or (assistant.custom_update_memory_prompt or "").strip() != desired_update.strip()
    )


# ---------------------------------------------------------------------------
# Async main
# ---------------------------------------------------------------------------

async def _run(api_key: str) -> None:
    from backboard import BackboardClient

    client = BackboardClient(api_key=api_key)
    print(f"[setup] Connected to Backboard API (key ending ...{api_key[-4:]})")

    print(f'[setup] Searching for existing assistant named "{ASSISTANT_NAME}"...')
    try:
        matches = await client.list_assistants(limit=100, name=ASSISTANT_NAME)
    except Exception as exc:
        sys.exit(f"ERROR: Could not list assistants — {exc}")

    existing = next((a for a in matches if a.name == ASSISTANT_NAME), None)

    if existing:
        assistant_id = str(existing.assistant_id)
        print(f"[setup] Found existing assistant.")
        print(f"  Name : {existing.name}")
        print(f"  ID   : {assistant_id}")
        action = "reused"

        if _prompts_differ(existing, SYSTEM_PROMPT, CUSTOM_FACT_EXTRACTION_PROMPT, CUSTOM_UPDATE_MEMORY_PROMPT):
            print("[setup] Prompts differ — updating assistant...")
            try:
                updated = await client.update_assistant(
                    assistant_id=assistant_id,
                    system_prompt=SYSTEM_PROMPT,
                    custom_fact_extraction_prompt=CUSTOM_FACT_EXTRACTION_PROMPT,
                    custom_update_memory_prompt=CUSTOM_UPDATE_MEMORY_PROMPT,
                )
                assistant_id = str(updated.assistant_id)
                print("[setup] Assistant prompts updated successfully.")
                action = "updated"
            except Exception as exc:
                print(f"[setup] WARNING: Could not update assistant — {exc}")
        else:
            print("[setup] Prompts are already up to date. No update needed.")
    else:
        print(f'[setup] No existing assistant found. Creating "{ASSISTANT_NAME}"...')
        try:
            created = await client.create_assistant(
                name=ASSISTANT_NAME,
                description=ASSISTANT_DESCRIPTION,
                system_prompt=SYSTEM_PROMPT,
                custom_fact_extraction_prompt=CUSTOM_FACT_EXTRACTION_PROMPT,
                custom_update_memory_prompt=CUSTOM_UPDATE_MEMORY_PROMPT,
            )
        except Exception as exc:
            sys.exit(f"ERROR: Could not create assistant — {exc}")

        assistant_id = str(created.assistant_id)
        print(f"[setup] Assistant created successfully.")
        print(f"  Name : {created.name}")
        print(f"  ID   : {assistant_id}")
        action = "created"

    # Write assistant ID back to .env
    print(f"\n[setup] Writing BACKBOARD_ASSISTANT_ID to {ENV_FILE} ...")
    try:
        _write_env_value("BACKBOARD_ASSISTANT_ID", assistant_id, ENV_FILE)
        print(f"[setup] .env updated.")
    except Exception as exc:
        print(f"[setup] WARNING: Could not update .env — {exc}")
        print(f"[setup] Add manually:  BACKBOARD_ASSISTANT_ID={assistant_id}")

    print("\n" + "=" * 60)
    print("  SETUP COMPLETE")
    print("=" * 60)
    print(f"  Assistant name : {ASSISTANT_NAME}")
    print(f"  Assistant ID   : {assistant_id}")
    print(f"  Action taken   : {action}")
    print(f"  Memory prompts : configured (custom_fact_extraction_prompt,")
    print(f"                               custom_update_memory_prompt)")
    print(f"  .env file      : {ENV_FILE}")
    print("=" * 60)
    print()
    print("Next step: run  python scripts/verify_backboard.py")

    await client.aclose()


def main() -> None:
    api_key = os.environ.get("BACKBOARD_API_KEY", "")
    if not api_key:
        sys.exit("ERROR: BACKBOARD_API_KEY is not set. Check your .env file.")

    try:
        from backboard import BackboardClient  # noqa: F401
    except ImportError:
        sys.exit("ERROR: backboard-sdk is not installed. Run: pip install 'backboard-sdk>=1.5.14,<2'")

    asyncio.run(_run(api_key))


if __name__ == "__main__":
    main()
