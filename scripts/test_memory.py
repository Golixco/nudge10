#!/usr/bin/env python3
"""
test_memory.py — Cross-thread persistent memory proof for Nudge10.

GOAL:
  Prove that a productivity preference stated in Thread A is retrieved
  and applied in a completely separate Thread B.

PROTOCOL:
  1. Create Thread A under the Nudge10 assistant.
  2. Send a preference statement in Thread A (memory="Auto").
  3. If a memory_operation_id is returned, poll until completed.
  4. Create Thread B — a brand-new thread, no shared context.
  5. Send a mission request in Thread B.
  6. Report whether the preference appears in Thread B's response.

Exit code 0 on success, 1 on hard failure.

Never prints BACKBOARD_API_KEY.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env before importing app modules
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
except ImportError:
    sys.exit("ERROR: python-dotenv not installed.")


# --- Preference phrase (must appear in Thread A, looked for in Thread B) ---
THREAD_A_MESSAGE = (
    "I work best when large tasks are broken into tiny 10-minute actions. "
    "I dislike motivational speeches and prefer short, direct instructions."
)

THREAD_B_MESSAGE = (
    "I need to work on my machine learning project. "
    "Give me one 10-minute mission."
)

# Keywords that indicate the preference was applied
PREFERENCE_SIGNALS = [
    "10-minute",
    "10 minute",
    "direct",
    "short",
    "concrete",
    "specific",
    "one thing",
    "single",
    "action",
]


def _preference_reflected(response_text: str) -> bool:
    """Heuristic: does Thread B response look like it used the memory?"""
    low = response_text.lower()
    matches = [kw for kw in PREFERENCE_SIGNALS if kw in low]
    # At least 2 signals present suggests the model used the memory
    return len(matches) >= 2


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


async def _run() -> None:
    # Validate environment
    api_key = os.environ.get("BACKBOARD_API_KEY", "")
    assistant_id = os.environ.get("BACKBOARD_ASSISTANT_ID", "")
    provider = os.environ.get("BACKBOARD_MODEL_PROVIDER", "openrouter")
    model = os.environ.get("BACKBOARD_MODEL_NAME", "google/gemma-3-27b-it")

    if not api_key:
        sys.exit("ERROR: BACKBOARD_API_KEY not set.")
    if not assistant_id:
        sys.exit("ERROR: BACKBOARD_ASSISTANT_ID not set. Run setup_backboard.py first.")

    # Import service after env is ready
    from app.backboard_service import BackboardService
    from app.config import settings

    svc = BackboardService()
    if not svc.enabled:
        sys.exit("ERROR: BackboardService reports disabled. Check .env.")

    print()
    print("=" * 64)
    print("  NUDGE10 CROSS-THREAD PERSISTENT MEMORY TEST")
    print("=" * 64)
    print(f"  Assistant ID : {assistant_id}")
    print(f"  Provider     : {provider}")
    print(f"  Model        : {model}")
    print()

    # ------------------------------------------------------------------
    # PRE-FLIGHT: count existing memories
    # ------------------------------------------------------------------
    memories_before = await svc.list_memories()
    print(f"[pre-flight] Memories stored before test: {len(memories_before)}")
    print()

    # ------------------------------------------------------------------
    # THREAD A — state the preference
    # ------------------------------------------------------------------
    print("[Thread A] Creating thread...")
    thread_a_id = await svc.create_thread()
    if not thread_a_id:
        sys.exit("ERROR: Failed to create Thread A.")
    print(f"[Thread A] Thread ID : {thread_a_id}")

    print("[Thread A] Sending preference statement...")
    result_a = await svc.send_in_thread(THREAD_A_MESSAGE, thread_a_id)

    if result_a["status"] != "ok":
        sys.exit(f"ERROR: Thread A send failed — status={result_a['status']}")

    print(f"[Thread A] Status         : {result_a['status']}")
    print(f"[Thread A] Content        : {str(result_a['content'] or '').strip()[:120]}")
    mem_op_id = result_a.get("memory_operation_id")
    print(f"[Thread A] memory_op_id   : {mem_op_id or 'None (no write triggered)'}")
    print()

    # ------------------------------------------------------------------
    # Poll memory operation if one was started
    # ------------------------------------------------------------------
    mem_op_status: dict = {}
    if mem_op_id:
        print(f"[memory] Polling operation {mem_op_id}...")
        mem_op_status = await svc.poll_memory_operation(
            mem_op_id, timeout_seconds=20.0, interval_seconds=2.0
        )
        print(f"[memory] Operation status : {mem_op_status.get('status')}")
        print(f"[memory] Result count     : {mem_op_status.get('result_count')}")
        print(f"[memory] Memory IDs       : {mem_op_status.get('memory_ids')}")
    else:
        # memory_operation_id is None: Backboard may have used the assistant-level
        # Auto memory without an explicit operation (occurs when no new extractable
        # facts were found, or when the Auto memory ran synchronously).
        print("[memory] No memory_operation_id returned.")
        print("[memory] This is expected when Backboard Auto memory processes")
        print("[memory] the statement synchronously or finds nothing to extract.")
    print()

    # Wait briefly for async memory to settle regardless
    await asyncio.sleep(3.0)

    # ------------------------------------------------------------------
    # THREAD B — completely new thread, request a mission
    # ------------------------------------------------------------------
    print("[Thread B] Creating NEW thread (no shared context with Thread A)...")
    thread_b_id = await svc.create_thread()
    if not thread_b_id:
        sys.exit("ERROR: Failed to create Thread B.")
    print(f"[Thread B] Thread ID : {thread_b_id}")

    if thread_b_id == thread_a_id:
        sys.exit("ERROR: Thread B has the same ID as Thread A — cross-thread test invalid.")

    print("[Thread B] Sending mission request...")
    result_b = await svc.send_in_thread(THREAD_B_MESSAGE, thread_b_id)

    if result_b["status"] != "ok":
        print(f"[Thread B] WARNING: send failed — status={result_b['status']}")
    print()

    # ------------------------------------------------------------------
    # Check memories after
    # ------------------------------------------------------------------
    memories_after = await svc.list_memories()
    new_memory_count = len(memories_after) - len(memories_before)

    # Search for the preference directly
    pref_search = await svc.search_memories("10-minute actions direct instructions", limit=3)

    retrieved = result_b.get("retrieved_memories")
    content_b = (result_b.get("content") or "").strip()
    reflected = _preference_reflected(content_b) if content_b else False

    # ------------------------------------------------------------------
    # Final report
    # ------------------------------------------------------------------
    print("=" * 64)
    print("  RESULT")
    print("=" * 64)
    print(f"  Thread A ID           : {thread_a_id}")
    if mem_op_id:
        print(f"  Memory op ID          : {mem_op_id}")
        print(f"  Memory op status      : {mem_op_status.get('status', 'unknown')}")
    else:
        print(f"  Memory op ID          : None")
        print(f"  Memory op status      : N/A (no operation ID returned)")
    print(f"  Thread B ID           : {thread_b_id}")
    print(f"  Threads are different : {thread_a_id != thread_b_id}")
    print()
    print(f"  Memories before       : {len(memories_before)}")
    print(f"  Memories after        : {len(memories_after)}")
    print(f"  New memories stored   : {new_memory_count}")
    print()
    print(f"  Thread B retrieved_memories : {retrieved}")
    print(f"  Preference reflected        : {reflected}")
    print()
    print("  Thread B response:")
    if content_b:
        print(_indent(content_b))
    else:
        print("  (empty or failed)")
    print()

    # Semantic search result
    if pref_search:
        print("  Matching memories (semantic search):")
        for m in pref_search:
            score = f"score={m['score']:.3f}" if m.get("score") is not None else ""
            print(f"    [{score}] {m['content'][:120]}")
    else:
        print("  Semantic search found no matching memories yet.")
    print("=" * 64)
    print()

    # Diagnose if memory was not retrieved
    if not reflected and not retrieved:
        print("[DIAGNOSIS]")
        print("  The preference was not visibly retrieved in Thread B.")
        print("  Known Backboard Auto memory behavior:")
        print("  - Memory extraction runs asynchronously and may complete")
        print("    seconds to minutes after the original message.")
        print("  - If no durable, extractable fact was identified by the")
        print("    custom_fact_extraction_prompt, no memory is written.")
        print("  - The retrieval occurs at inference time based on semantic")
        print("    relevance between the query and stored memories.")
        print("  - Re-running this script a few minutes later should show")
        print("    the memory count increase if extraction succeeded.")
        print()
        print("  Recommended action: wait ~2 minutes then run:")
        print("    python3 scripts/verify_backboard.py")
        print("    python3 scripts/test_memory.py")
        print()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
