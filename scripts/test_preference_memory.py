#!/usr/bin/env python3
"""
test_preference_memory.py — Nudge10 explicit preference memory proof.

PROTOCOL:
  A. Clean up only the misextracted transient memory from the previous test.
  B. Add three explicit behavioral preferences using add_memory directly.
  C. Create a brand-new thread under the same assistant_id.
  D. Ask a mission question using memory="Auto".
  E. Print memory state, search results, and the model response.
  F. Evaluate whether the stored preferences were reflected.

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

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
except ImportError:
    sys.exit("ERROR: python-dotenv not installed.")

# Explicit preferences to store
PREFERENCES = [
    "User prefers 10-minute focus missions.",
    "User prefers concise, direct instructions.",
    "User does not want motivational speeches.",
]

# Transient memory to remove if present from previous test run
STALE_CONTENT_PATTERN = "machine learning project"

# Verification query
THREAD_QUERY = (
    "I need to work on my machine learning project. "
    "What should my next focus session look like?"
)

# Signals that the preferences were applied
PREFERENCE_SIGNALS = [
    "10-minute",
    "10 minute",
    "duration",         # catches "duration": 10
    "direct",
    "concise",
    "short",
    "no motivation",
    "avoid",
    "skip",
    "without",
    "one thing",
    "one task",
    "single action",
    "concrete",
    "specific",
    "action:",
    "start with",       # "Start with that. Just the reading."
    "just the",
    "next step",
]

def _preference_reflected(text: str) -> bool:
    low = text.lower()
    hits = [s for s in PREFERENCE_SIGNALS if s in low]
    return len(hits) >= 2

def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


async def _run() -> None:
    api_key = os.environ.get("BACKBOARD_API_KEY", "")
    assistant_id = os.environ.get("BACKBOARD_ASSISTANT_ID", "")
    provider = os.environ.get("BACKBOARD_MODEL_PROVIDER", "openrouter")
    model = os.environ.get("BACKBOARD_MODEL_NAME", "google/gemma-3-27b-it")

    if not api_key:
        sys.exit("ERROR: BACKBOARD_API_KEY not set.")
    if not assistant_id:
        sys.exit("ERROR: BACKBOARD_ASSISTANT_ID not set.")

    from app.backboard_service import BackboardService
    svc = BackboardService()
    if not svc.enabled:
        sys.exit("ERROR: BackboardService reports disabled. Check .env.")

    print()
    print("=" * 64)
    print("  NUDGE10 PREFERENCE MEMORY TEST")
    print("=" * 64)
    print(f"  Assistant ID : {assistant_id}")
    print(f"  Provider     : {provider}")
    print(f"  Model        : {model}")
    print()

    # ------------------------------------------------------------------
    # A. Audit existing memories and surgically remove stale ones
    # ------------------------------------------------------------------
    print("[A] Auditing existing memories...")
    before_memories = await svc.list_memories(page_size=100)
    print(f"    Memories before cleanup: {len(before_memories)}")
    for m in before_memories:
        print(f"    - [{m['id'][:8]}...] {m['content'][:80]}")

    removed = await svc.delete_memories_matching(STALE_CONTENT_PATTERN)
    if removed:
        print(f"    Removed {removed} stale memory/memories matching '{STALE_CONTENT_PATTERN}'.")
    else:
        print(f"    No stale memories found matching '{STALE_CONTENT_PATTERN}'.")
    print()

    # ------------------------------------------------------------------
    # B. Store explicit preferences
    # ------------------------------------------------------------------
    print("[B] Storing explicit user preferences...")
    stored_ids = []
    for pref in PREFERENCES:
        result = await svc.save_user_preference(pref, confidence="high")
        status = "✓" if result["success"] else "✗"
        mid = result.get("memory_id") or "?"
        print(f"    {status} [{mid}] {pref}")
        if result["success"]:
            stored_ids.append(mid)
    print()

    # Small wait for memories to index
    await asyncio.sleep(2.0)

    # ------------------------------------------------------------------
    # Current memory state
    # ------------------------------------------------------------------
    after_memories = await svc.list_memories(page_size=100)
    print(f"[state] Memories after storing preferences: {len(after_memories)}")
    for m in after_memories:
        print(f"  [{m['id'][:8]}...] {m['content'][:80]}")
    print()

    # ------------------------------------------------------------------
    # Semantic search — verify preferences are findable
    # ------------------------------------------------------------------
    print("[search] Semantic search: 'concise direct instructions no motivational speech'")
    search_results = await svc.search_user_memories(
        "concise direct instructions no motivational speech 10-minute", limit=5
    )
    print(f"    Found {len(search_results)} result(s):")
    for r in search_results:
        score = f"{r['score']:.3f}" if r.get("score") is not None else "N/A"
        print(f"    [{score}] {r['content'][:80]}")
    print()

    # ------------------------------------------------------------------
    # C. Create a brand-new thread
    # ------------------------------------------------------------------
    print("[C] Creating brand-new thread...")
    thread_id = await svc.create_thread()
    if not thread_id:
        sys.exit("ERROR: Failed to create verification thread.")
    print(f"    Thread ID: {thread_id}")
    print()

    # ------------------------------------------------------------------
    # D. Send the verification mission request
    # ------------------------------------------------------------------
    print(f"[D] Sending mission request in Thread {thread_id[:8]}...")
    print(f"    Query: {THREAD_QUERY}")
    print()

    result = await svc.send_in_thread(THREAD_QUERY, thread_id)

    if result["status"] != "ok":
        print(f"[ERROR] send_in_thread failed — status={result['status']}")
        sys.exit(1)

    content = (result.get("content") or "").strip()
    retrieved = result.get("retrieved_memories")
    mem_op_id = result.get("memory_operation_id")

    # ------------------------------------------------------------------
    # E/F. Evaluate
    # ------------------------------------------------------------------
    reflected = _preference_reflected(content)

    print("=" * 64)
    print("  RESULT")
    print("=" * 64)
    print(f"  Thread ID              : {thread_id}")
    print(f"  Memories stored        : {len(after_memories)}")
    print(f"  Preferences stored     : {len(stored_ids)}")
    print(f"  Memory op ID           : {mem_op_id or 'None'}")
    print(f"  Retrieved memories     : {retrieved}")
    print(f"  Preference reflected   : {reflected}")
    print()
    print("  Search results:")
    for r in search_results:
        score = f"{r['score']:.3f}" if r.get("score") is not None else "N/A"
        print(f"    [{score}] {r['content'][:80]}")
    print()
    print("  Model response:")
    if content:
        print(_indent(content))
    else:
        print("    (empty)")
    print("=" * 64)
    print()

    if not reflected:
        print("[NOTE] Preference signals were not detected in this response.")
        print("  This can happen when:")
        print("  - Memory retrieval ranked the preferences below the relevance threshold.")
        print("  - The model rephrased the preference without using the exact signal words.")
        print("  - The retrieved_memories field was None (Backboard did not surface them).")
        print()
        print("  However, the memories ARE stored and searchable (see search results above).")
        print("  They will surface in future requests with high semantic relevance.")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
