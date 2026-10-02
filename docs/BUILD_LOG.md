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

