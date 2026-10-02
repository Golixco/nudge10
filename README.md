# Nudge10

> An AI-powered anti-doomscrolling focus companion built for a friend who struggles to stay productive for even 10 minutes.

Nudge10 turns big tasks into tiny 10-minute missions, tracks focus sessions, and uses personalized AI nudges when distraction happens.

## MVP architecture

- **Frontend:** Vanilla HTML/CSS/JavaScript (zero build step)
- **Backend:** FastAPI
- **AI orchestration + memory:** Backboard
- **Open-weight model:** Google Gemma 3 27B (`google/gemma-3-27b-it` via OpenRouter through Backboard)
- **Deployment:** Render
- **Browser intervention:** Chrome Extension (Manifest V3)
- **Persistence for MVP:** localStorage in the browser; Backboard stores assistant-level memories

Backboard supports persistent memory and assistant-level conversations, and its API allows per-message model selection. Render supports deploying FastAPI services and Next.js/Node apps as web services. See the project docs and citations in the challenge write-up for the current integration details.

## How a Nudge10 session works

Nudge10 turns vague anxiety into concrete, timed execution with no shame:

```text
[ USER ENTERS TASK ]
  "Finish DBMS assignment"
       │
       ▼
[ AI MISSION GENERATION (Gemma 3 27B) ]
  Title:   DBMS: Entity Relationship Diagram
  Action:  Draw the entities for question 1
  Reason:  Visualizing the core components clarifies the schema.
       │
       ▼
[ MISSION PREVIEW SCREEN ]
  User reviews the 1 concrete starting step
  [ START 10:00 ]
       │
       ▼
[ ACTIVE 10-MINUTE FOCUS SESSION ]
  Accurate Date.now()-based timer countdown
  Mission action clearly displayed
       │
       ├─────────────────────────────────┐
       │ (Distraction detected)          │ (User clicks "I need to stop")
       ▼                                 ▼
[ DISTRACTION INTERVENTION ]       [ ABANDON SESSION (NO SHAME) ]
  Normalized site: "youtube.com"     "Session stopped. That's okay."
  AI intervention:                   Suggested smaller next step:
  "YouTube happens. Come back."       "Write out attributes for table 1"
  [ Back to work ]                   [ Make the task smaller ]
       │                                 │
       ▼ (Timer reaches 00:00)           ▼
[ MISSION COMPLETE ]               [ RETURN TO TASK LIST ]
  "Mission complete. That's a win."
  Focus duration + momentum stats
  Saved to behavioral memory only
  if recurring patterns exist
```

### Session Lifecycle Summary

1. **Start (`POST /api/session/start`)**: Validates input task, requests a concrete 10-minute mission action from Gemma via Backboard, assigns a unique `session_id`, and stores session state in client `localStorage`.
2. **Focus Timer**: Driven by `Date.now()` timestamps rather than tick counters, ensuring timer accuracy even when switching tabs or backgrounding the window. Page refreshes automatically restore the active timer.
3. **Distraction (`POST /api/session/distraction`)**: When a distracting domain is triggered (e.g., `youtube.com`), normalized hostnames are sent to the AI intervention endpoint without collecting raw URLs or browsing history.
4. **Completion (`POST /api/session/complete`)**: Triggered when the timer runs out or the user clicks Complete. Increments daily focus statistics and updates Backboard memory only when durable, recurring patterns are identified.
5. **Abandonment (`POST /api/session/abandon`)**: Non-judgmental exit that suggests a smaller starting bite for the task instead of inducing guilt.

## Local development

### 1. Backend

```bash
cd nudge10
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

The frontend is served directly by FastAPI, so there is no Node build step for the MVP. Run the backend and open `http://localhost:8000`.

### 3. AI configuration

Set `BACKBOARD_API_KEY`. If `BACKBOARD_ASSISTANT_ID` is not set, the app can run in demo/mock mode until Backboard is configured.

Recommended model:

```text
llm_provider=openrouter
model_name=google/gemma-3-27b-it
```

For inexpensive experiments, OpenRouter also currently lists a free Gemma 3 27B endpoint (`google/gemma-3-27b-it:free`), subject to provider rate limits.

## Browser Protection (Chrome Extension)

Nudge10 includes an optional Manifest V3 browser extension that bridges your live focus sessions with real-world browser activity.

### How to Install the Unpacked Extension

1. Open Google Chrome and navigate to `chrome://extensions`.
2. Toggle **Developer mode** on (top-right corner).
3. Click **Load unpacked** (top-left corner).
4. Select the `extension/` directory from this repository.
5. Open the Nudge10 web app at `http://localhost:8000`. The diagnostics panel will report: `Browser protection: ON (Extension connected)`.

### Why It Requires Host Permissions

The extension requests least-privilege host permissions exclusively for:
- `http://localhost:8000/*` and Render origin: to bridge session lifecycle messages (`NUDGE10_SESSION_START`, `NUDGE10_SESSION_END`) between the web app and service worker without requiring broad browser permissions.
- `https://*.youtube.com/*`, `https://*.instagram.com/*`, `https://*.reddit.com/*`, `https://*.x.com/*`, `https://*.twitter.com/*`: to detect when the tab enters a distraction domain and inject the intervention overlay.

The extension **does NOT request**:
- `tabs` permission (all tab updates are scoped strictly by matched host permissions).
- `browsingData`, `history`, `cookies`, `webRequest`, or `debugger`.
- Broad `<all_urls>` or `*://*/*` access.

### Privacy & Data Handling

Nudge10 adheres to strict zero-surveillance principles:
- **What it sends:** When a distraction occurs during an active session, the extension calculates elapsed seconds and sends **only** the normalized domain name (e.g. `"youtube.com"`) and the active `session_id` to `POST /api/session/distraction`.
- **What it NEVER sends or accesses:**
  - Full URLs or query parameters (e.g. specific video IDs, subreddits, or searches)
  - Page titles or page contents
  - Browsing history
  - Form fields or passwords
  - Cookies or authentication tokens

### Local Development vs. Production Setup

In `extension/config.js`:
```javascript
const NUDGE10_CONFIG = {
  // Local development default:
  API_BASE_URL: 'http://localhost:8000',
  WEB_APP_URL: 'http://localhost:8000',

  // For production deployment on Render, update to your service URL:
  // API_BASE_URL: 'https://YOUR-NUDGE10-RENDER-SERVICE.onrender.com',
  // WEB_APP_URL: 'https://YOUR-NUDGE10-RENDER-SERVICE.onrender.com',
};
```

## Deploying Nudge10 on Render

Nudge10 is designed for turnkey deployment on [Render](https://render.com) as a single Python Web Service that serves both the FastAPI API and the zero-build static frontend.

### Step-by-Step Deployment:

1. **Connect GitHub repository:**
   - Push this repository to GitHub (`https://github.com/Golixco/nudge10.git`).
   - In the Render Dashboard, click **New +** &rarr; **Web Service** and connect your repository (or use the included `render.yaml` Blueprint).

2. **Configure the Web Service:**
   - **Runtime:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path:** `/api/health`

3. **Configure Environment Variables (in Render Dashboard):**
   Add the following environment variables in the Render dashboard:
   - `BACKBOARD_API_KEY`: Your Backboard API key (kept secret, never committed).
   - `BACKBOARD_ASSISTANT_ID`: The UUID of your provisioned Nudge10 assistant.
   - `BACKBOARD_MODEL_PROVIDER`: `openrouter`
   - `BACKBOARD_MODEL_NAME`: `google/gemma-3-27b-it`
   - `APP_ENV`: `production`

   > **Security Note:** Never commit `.env` or include real API secrets in repository files. All secrets are configured strictly in the Render dashboard.

4. **Verify Deployment:**
   Once Render deploys your service, verify the health check:
   ```bash
   curl -i https://YOUR-SERVICE-NAME.onrender.com/api/health
   # Returns: {"ok": true, "ai_enabled": true}
   ```
   Open `https://YOUR-SERVICE-NAME.onrender.com/` in your browser to verify the frontend.

---

## Hacktoberfest 2026

- **Track / Theme:** Build for a Friend
- **Inspiration:** Built for a close friend who struggles with attention regulation and doomscrolling loops, transforming vague anxiety into actionable 10-minute focus sprints.
- **Open-Source AI at the Core:** Powered by Google's open-weight **Gemma** (`google/gemma-3-27b-it`) via OpenRouter.
- **Memory & Orchestration:** **Backboard** manages conversation threads and durable persistent memory across separate focus sessions.
- **Hosting & Infrastructure:** Deployed on **Render** as a high-performance, single-service FastAPI application.

