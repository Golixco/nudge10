# Build Log

## 2026-10-02 — MVP scaffold

- Created new Nudge10 project during the Hacktoberfest Weekend Challenge window.
- Switched to zero-build vanilla HTML/CSS/JS served directly by FastAPI for minimal deployment friction.
- Added a 10-minute mission loop.
- Added deterministic fallback behavior so the app can be demoed before API keys are configured.
- Added Backboard adapter for Gemma + persistent memory.
- Added Chrome extension prototype for distraction-site intervention.

## 2026-10-02 — Architecture audit & scaffold preparation

- Performed full repository audit for Hacktoberfest 2026 Weekend Challenge.
- Removed stray `__pycache__` and bytecode artifacts.
- Hardened `.gitignore` against caches, environments, IDEs, and OS artifacts.
- Fixed `requirements.txt` (`backboard-sdk>=1.5.14,<2` to support `send_message` and avoid unresolvable `<1` constraint).
- Hardened FastAPI frontend static serving against path traversal.
- Enhanced Backboard adapter to pass `SYSTEM_PROMPT`, enable `json_output`, and robustly parse JSON fences.
- Synced Chrome extension `WEB_APP_URL` to FastAPI port 8000 and wired navigation message listener.

## 2026-10-02 — Backboard assistant provisioned

- Introspected `backboard-sdk==1.5.19` to obtain exact async method signatures before writing any code.
- Created `scripts/setup_backboard.py` — idempotent provisioning script:
  - Calls `list_assistants(name="Nudge10")` to avoid duplicate creation.
  - Calls `create_assistant(...)` with system prompt, description, and custom memory prompts.
  - Calls `update_assistant(...)` when prompts differ on rerun.
  - Writes `BACKBOARD_ASSISTANT_ID` back to `.env` automatically.
- Created `scripts/verify_backboard.py` — safe metadata-only check via `get_assistant()`. No LLM call.
- Provisioned assistant `Nudge10` (stored securely in local `.env`).
- Configured Backboard persistent memory with:
  - `custom_fact_extraction_prompt`: restricts extraction to productivity/work habits, blocks PII and browsing history.
  - `custom_update_memory_prompt`: keeps memory concise and refuses to store raw browsing events.
- Updated `SYSTEM_PROMPT` in `app/backboard_service.py` to match the canonical provisioned prompt exactly.
- Added `docs/BACKBOARD_SETUP.md` covering creation, memory, idempotency, and SDK reference.
- Confirmed setup script is idempotent (second run: "Prompts are already up to date. No update needed.").
- All Python syntax checks passed (`py_compile` on all 7 source files).
- Verification passed: name=Nudge10, system_prompt=YES, custom_fact_extraction=YES, custom_update_memory=YES.

## 2026-10-02 — Stage 8: Real Nudge10 focus-session experience

- Implemented lightweight focus-session model in `app/session_service.py` with statuses: `created`, `active`, `completed`, `abandoned`.
- Added 4 session lifecycle endpoints in `app/main.py` while preserving existing API compatibility:
  - `POST /api/session/start`: validates input, generates real AI mission through Backboard, assigns UUID session_id.
  - `POST /api/session/complete`: records completion, computes elapsed time, conditionally commits behavioral patterns to memory.
  - `POST /api/session/abandon`: no-shame exit with supportive messaging and an AI-suggested smaller next step.
  - `POST /api/session/distraction`: logs normalized domain (no raw URLs/PII) and requests AI intervention nudge.
- Implemented behavioral memory gating (`should_remember_completion`, `should_remember_abandonment`): writes to Backboard memory only for recurring distraction patterns (>=2) over meaningful session duration (>=120s).
- Rebuilt frontend (`frontend/index.html`, `frontend/styles.css`):
  - Five distinct views: Home, Mission Preview, Focus Timer, Complete, Abandon.
  - Timestamp-based (`Date.now()`) countdown timer with circular SVG progress ring, accurate across backgrounded/minimized tabs and visibility changes.
  - Session restoration via `localStorage`: page refresh seamlessly restores active timer or auto-completes expired sessions.
  - No-shame abandonment flow offering "Make the task smaller" prefilled input or return to task list.
  - Real-time distraction simulation buttons for YouTube, Instagram, Reddit, X.
  - Daily momentum dashboard tracking Today's Missions, Focus Minutes, Completed, Abandoned, and Distractions.
- Hardened backend with try-except safety nets to ensure external AI/memory failures never crash the user's session loop.
- Added comprehensive test suite in `tests/test_session.py` (13 tests) covering lifecycle, validations, resilience, memory gating, privacy, and localStorage compatibility. Total test suite expanded to 78 passing tests.
- Performed end-to-end smoke test (`scripts/smoke_test_session_api.py`) verifying real Backboard Gemma 3 27B AI interactions across all 4 session endpoints.

## 2026-10-02 — Stage 9: Chrome Extension focus-session integration

- Connected Manifest V3 Chrome Extension to real Nudge10 focus-session lifecycle without direct localStorage coupling:
  - Web App Bridge: dispatches `window.postMessage` (`NUDGE10_SESSION_START`, `NUDGE10_SESSION_END`) on start, complete, and abandon events.
  - Content Script Bridge: validates event origin (`source === window`, `data.source === 'nudge10-web'`) and securely forwards sanitized messages to the service worker via `chrome.runtime.sendMessage`.
  - Service Worker: stores `{ activeSessionId, startedAt, task, missionTitle, enabled }` in `chrome.storage.local` to survive service worker suspension/restart.
- Scoped distraction detection:
  - Normalized allowlist for `youtube.com`, `instagram.com`, `reddit.com`, `x.com`, and `twitter.com`.
  - Zero surveillance: sends strictly the normalized domain category and computed elapsed seconds to `POST /api/session/distraction`. No full URLs, query strings, page titles, cookies, or history.
  - Tab navigation listener (`chrome.tabs.onUpdated`): triggers only on navigation completion for distraction domains when a session is active.
  - Duplicate suppression: tracks `lastTabDistraction` map per tab, preventing repeated alerts while browsing within the same distraction category.
- Non-blocking intervention overlay:
  - Content script renders focused dark-mode overlay displaying active mission, AI message, and AI corrective action.
  - "Back to work" navigates tab directly to Nudge10 web app URL; "Dismiss" or `Escape` key closes overlay cleanly.
  - Non-judgmental tone with no shame language.
  - Fallback intervention if backend unavailable: "You're outside your focus session. Return to the task you started."
- Permissions minimized to least-privilege:
  - Permissions: strictly `["storage"]`.
  - Explicit host permissions only for web app origins and the 5 distraction domains. Removed broad `<all_urls>` and `tabs` permission.
- Development diagnostics:
  - Web app demo panel displays real-time connection status pill (`Browser protection: ON` / `Extension not detected`), active session ID, and distraction count.
- Added automated test suite `tests/test_extension.py` covering MV3 schema, permission auditing, secret leakage checks, hostname normalization, and service worker lifecycle simulation. Total test suite passing: 82/82.

## 2026-10-02 — Stage 10A: Production release & Render deployment preparation

- Comprehensive Git & Secret Audit:
  - Confirmed `.env` is ignored by `.gitignore` along with `.pytest_cache/`, `__pycache__/`, `.venv/`, and editor artifacts.
  - Automated recursive secret audit verified 0 leaked API keys, tokens, or credentials across all tracked and untracked files.
  - Verified no secret IDs or sensitive configuration exposed.
- Render Deployment Configuration:
  - Updated `render.yaml` with explicit health check path (`healthCheckPath: /api/health`).
  - Configured start command to use Render's dynamic `$PORT` environment variable (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
  - Runtime: Python with `pip install -r requirements.txt`.
- Production Hardening & CORS:
  - Added `is_production` property to `app/config.py`.
  - Restricted `/api/health` in production mode (`APP_ENV=production`) to return only `{"ok": true, "ai_enabled": true}`, suppressing `assistant_id` and internal service topology.
  - Hardened CORS: eliminated wildcard CORS (`allow_origins=["*"]`) in production mode; restricted origins to Chrome extension origin regex (`chrome-extension://*`) for extension communication while keeping localhost origins enabled for development.
- Dependencies & Extension Config:
  - Verified `requirements.txt` contains only strictly necessary, compatible dependencies (`fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `backboard-sdk`, `python-dotenv`).
  - Documented production Render URL placeholder in `extension/config.js` with guidance for updating host permissions once the service URL is created.
- Verification & Test Suite:
  - All Python files verified via `python3 -m py_compile`.
  - All extension JavaScript files verified via `node -c`.
  - Extension `manifest.json` validated as valid JSON Manifest V3.
  - Render startup simulated on port 10000 with `APP_ENV=production`; verified `GET /api/health` returns 200 OK and `GET /` serves HTML frontend.
  - Expanded test suite to 85 passing tests.

