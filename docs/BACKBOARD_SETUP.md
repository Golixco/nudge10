# Backboard Setup — Nudge10

## Overview

Nudge10 uses [Backboard](https://backboard.io) as its AI backend: it provides
persistent per-user memory, access to OpenRouter-hosted open-weight models, and
a managed conversation thread system.

The assistant is a **long-lived server-side resource** identified by a stable
`assistant_id`. All LLM calls made by the backend reference this single
assistant ID, which is why consistency of the ID matters for persistent memory.

---

## How the assistant is created

Run the idempotent provisioning script once:

```bash
python scripts/setup_backboard.py
```

The script:
1. Loads `BACKBOARD_API_KEY` from your `.env` file (never exposes it).
2. Calls `list_assistants(name="Nudge10")` to search for an existing assistant.
3. If **not found** → calls `create_assistant(...)` with the full system prompt
   and memory configuration.
4. If **found** → compares current vs desired prompts and calls
   `update_assistant(...)` only if they differ.
5. Writes `BACKBOARD_ASSISTANT_ID=<uuid>` into your local `.env` automatically.

---

## Why the same assistant_id matters for persistent memory

Backboard's memory is **scoped to a single assistant**. The assistant accumulates
long-term facts about the user across separate conversation threads. If you
accidentally create a second assistant with a different ID:

- The new assistant starts with **zero memory** — the user's history is lost.
- The old assistant's accumulated facts become orphaned.
- The two assistants cannot share memory.

**Always use the same `assistant_id` in production.** The setup script prevents
duplicates by name-matching before creating.

---

## How to rerun setup safely

The script is idempotent — you can run it at any time:

```bash
python scripts/setup_backboard.py
```

- If the assistant already exists with correct prompts → no-op (skips update).
- If the system prompt has changed → updates the assistant in place, preserving
  its existing memory.
- If the assistant is missing (e.g. after an accidental delete) → recreates it.

> **Note:** Recreating after a delete will produce a **new assistant_id** and
> lose accumulated memory. Treat your assistant_id like production data.

---

## How to verify the assistant

Run the lightweight verification script (no LLM call made):

```bash
python scripts/verify_backboard.py
```

It fetches the assistant by ID and checks:
- ✓ Name is "Nudge10"
- ✓ System prompt is set
- ✓ `custom_fact_extraction_prompt` is configured
- ✓ `custom_update_memory_prompt` is configured

Exit code is `0` on success, `1` on any failure.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `BACKBOARD_API_KEY` | Yes | Your Backboard API key. Server-side only. |
| `BACKBOARD_ASSISTANT_ID` | Yes | UUID written by setup script. |
| `BACKBOARD_MODEL_PROVIDER` | No | Defaults to `openrouter`. |
| `BACKBOARD_MODEL_NAME` | No | Defaults to `google/gemma-3-27b-it`. |
| `APP_ENV` | No | `development` or `production`. |

Copy `.env.example` to `.env` and fill in `BACKBOARD_API_KEY`. The setup
script fills in `BACKBOARD_ASSISTANT_ID` automatically.

---

## Memory configuration

The assistant is created with:

- **`memory="Auto"`** on every `send_message()` call — the assistant reads
  and writes its own memory automatically.
- **`custom_fact_extraction_prompt`** — instructs the memory system to extract
  only durable productivity preferences and work habits. Explicitly avoids
  storing browsing history, secrets, financial data.
- **`custom_update_memory_prompt`** — instructs the memory system to keep facts
  concise and merge/overwrite outdated information cleanly.

---

## SDK reference (backboard-sdk==1.5.19)

All client methods used by Nudge10 are **async**:

| Method | Purpose |
|---|---|
| `list_assistants(limit, name)` | Find existing assistant by name |
| `create_assistant(name, system_prompt, ...)` | Create new assistant |
| `update_assistant(assistant_id, system_prompt, ...)` | Update prompts in place |
| `get_assistant(assistant_id)` | Retrieve metadata (no LLM call) |
| `send_message(content, assistant_id, memory, ...)` | Chat with memory |
| `add_memory(assistant_id, content)` | Inject a session summary into memory |
