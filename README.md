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

### 4. Chrome extension

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the `extension/` folder.
5. Visit a selected distraction site to test the nudge overlay.

Change `WEB_APP_URL` in `extension/config.js` when the app is deployed.

## Render deployment

This repository is designed as one Render web service running FastAPI, which directly serves the frontend (zero build step):

```text
Build:  pip install -r requirements.txt
Start:  uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set the Backboard environment variables in Render.

## Project status

Current target: Weekend Challenge MVP.
