"""
main.py — Nudge10 FastAPI application.

/api/health              — lightweight health check.
/api/mission             — generates a 10-minute focus mission (existing).
/api/nudge               — generates a distraction intervention (existing).
/api/session-memory      — records a session summary (existing).
/api/session/start       — start a new focus session.
/api/session/complete    — mark session completed.
/api/session/abandon     — mark session abandoned.
/api/session/distraction — record a distraction and return an AI nudge.
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .backboard_service import backboard
from .config import settings
from .schemas import (
    MissionRequest, MissionResponse,
    NudgeRequest, NudgeResponse,
    SessionStartRequest, SessionStartResponse,
    SessionCompleteRequest, SessionCompleteResponse,
    SessionAbandonRequest, SessionAbandonResponse,
    SessionDistractionRequest, SessionDistractionResponse,
    MissionPayload,
)
from . import session_service as svc

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(
    title="Nudge10",
    version="0.3.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
)

if settings.is_production:
    # In production, web app is served same-origin by FastAPI.
    # No wildcard CORS. Allow extension origin regex for Chrome extension requests.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^chrome-extension://[a-z]+$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
else:
    # Development: allow localhost origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": True,
        "ai_enabled": backboard.enabled,
    }
    # In production, never expose internal assistant IDs or service config to the browser
    if not settings.is_production:
        payload["assistant_id"] = settings.backboard_assistant_id if backboard.enabled else None
    return payload


# ---------------------------------------------------------------------------
# Existing mission / nudge routes (preserved exactly)
# ---------------------------------------------------------------------------

@app.post("/api/mission", response_model=MissionResponse)
async def create_mission(payload: MissionRequest) -> MissionResponse:
    generated = await backboard.create_mission(payload.task, payload.minutes)

    if generated:
        why = generated.get("reason") or generated.get("why", "")
        logger.info(
            "mission SUCCESS | assistant=%s | provider=%s | model=%s | task=%.60r",
            settings.backboard_assistant_id,
            settings.backboard_model_provider,
            settings.backboard_model_name,
            payload.task,
        )
        return MissionResponse(
            title=generated["title"],
            action=generated["action"],
            why=why,
            minutes=payload.minutes,
            source="backboard",
        )

    logger.info(
        "mission FALLBACK | assistant=%s | task=%.60r",
        settings.backboard_assistant_id,
        payload.task,
    )
    return MissionResponse(
        title="Start with one tiny step",
        action=f"Work only on the first concrete step of: {payload.task}",
        why="Starting small lowers the friction to begin.",
        minutes=payload.minutes,
        source="demo-fallback",
    )


@app.post("/api/nudge", response_model=NudgeResponse)
async def create_nudge(payload: NudgeRequest) -> NudgeResponse:
    generated = await backboard.generate_nudge(
        payload.task,
        payload.elapsed_minutes,
        payload.distraction,
        payload.distraction_count,
    )
    if generated:
        return NudgeResponse(**generated, source="backboard")

    if payload.distraction_count >= 3:
        message = "Third distraction. Don't restart the whole day — restart the next 60 seconds."
        action = "Close the distraction and do one tiny action on your task."
    else:
        message = "You left the mission. That's okay — just come back before the 10 minutes are up."
        action = "Return to your task and work for the next 60 seconds."

    return NudgeResponse(message=message, action=action, source="demo-fallback")


@app.post("/api/session-memory")
async def session_memory(summary: dict[str, str]) -> dict[str, bool]:
    saved = await backboard.remember_session(summary.get("summary", ""))
    return {"saved": saved}


# ---------------------------------------------------------------------------
# Session lifecycle routes
# ---------------------------------------------------------------------------

@app.post("/api/session/start", response_model=SessionStartResponse)
async def session_start(payload: SessionStartRequest) -> SessionStartResponse:
    """Start a new focus session with an AI-generated mission."""
    task = payload.task.strip()
    duration = payload.duration_minutes

    generated = None
    if backboard.enabled:
        try:
            generated = await backboard.create_mission(task, duration)
        except Exception as err:
            logger.warning("session/start | create_mission failed: %s", err)

    if generated:
        title = generated["title"]
        action = generated["action"]
        reason = generated.get("reason") or generated.get("why", "")
        source = "backboard"
    else:
        title = "Start with one tiny step"
        action = f"Work only on the first concrete step of: {task}"
        reason = "Starting small lowers the friction to begin."
        source = "demo-fallback"

    session = svc.create_session(
        task=task,
        mission_title=title,
        mission_action=action,
        mission_reason=reason,
        mission_source=source,
        duration_minutes=duration,
    )

    return SessionStartResponse(
        session_id=session["session_id"],
        mission=MissionPayload(title=title, action=action, reason=reason, source=source),
        duration_minutes=duration,
        started_at=session["started_at"],
    )


@app.post("/api/session/complete", response_model=SessionCompleteResponse)
async def session_complete(payload: SessionCompleteRequest) -> SessionCompleteResponse:
    """Mark a session completed. Conditionally saves behavioral signal to memory."""
    session = svc.get_session(payload.session_id)
    if session is None:
        logger.info("session/complete | unknown id=%s (accepted gracefully)", payload.session_id)
        return SessionCompleteResponse(
            session_id=payload.session_id,
            status="completed",
            elapsed_seconds=payload.elapsed_seconds,
            message="Session complete. That's a win.",
            source="demo-fallback",
        )

    svc.mark_complete(payload.session_id, payload.elapsed_seconds)

    should_save, memory_text = svc.should_remember_completion(session)
    if should_save and memory_text:
        try:
            saved = await backboard.remember_session(memory_text)
            logger.info("session/complete | memory_write=%s | text=%.80r", saved, memory_text)
        except Exception as err:
            logger.warning("session/complete | memory_write failed: %s", err)

    elapsed_min = payload.elapsed_seconds // 60
    elapsed_sec = payload.elapsed_seconds % 60

    return SessionCompleteResponse(
        session_id=payload.session_id,
        status="completed",
        elapsed_seconds=payload.elapsed_seconds,
        message=f"Mission complete. {elapsed_min}:{elapsed_sec:02d} of focused work.",
        source="backboard" if backboard.enabled else "demo-fallback",
    )


@app.post("/api/session/abandon", response_model=SessionAbandonResponse)
async def session_abandon(payload: SessionAbandonRequest) -> SessionAbandonResponse:
    """Mark a session abandoned. Responds without shame."""
    session = svc.get_session(payload.session_id)
    if session is None:
        logger.info("session/abandon | unknown id=%s (accepted gracefully)", payload.session_id)
        return SessionAbandonResponse(
            session_id=payload.session_id,
            status="abandoned",
            message="Session stopped. That's okay.",
            next_step="Try a smaller version of the same task next time.",
            source="demo-fallback",
        )

    svc.mark_abandoned(payload.session_id, payload.elapsed_seconds, payload.reason)

    should_save, memory_text = svc.should_remember_abandonment(session)
    if should_save and memory_text:
        try:
            saved = await backboard.remember_session(memory_text)
            logger.info("session/abandon | memory_write=%s | text=%.80r", saved, memory_text)
        except Exception as err:
            logger.warning("session/abandon | memory_write failed: %s", err)

    task = session.get("original_task", "your task")
    next_step: str | None = None
    if backboard.enabled:
        try:
            nudge = await backboard.generate_nudge(
                task,
                elapsed_minutes=payload.elapsed_seconds // 60,
                distraction=payload.reason or "stopped",
                distraction_count=session.get("distraction_count", 0) + 1,
            )
            if nudge:
                next_step = nudge.get("action")
        except Exception as err:
            logger.warning("session/abandon | generate_nudge failed: %s", err)

    if not next_step:
        next_step = f"Try working on just the first sentence / first line of: {task}"

    return SessionAbandonResponse(
        session_id=payload.session_id,
        status="abandoned",
        message="Session stopped. That's okay.",
        next_step=next_step,
        source="backboard" if backboard.enabled else "demo-fallback",
    )


@app.post("/api/session/distraction", response_model=SessionDistractionResponse)
async def session_distraction(payload: SessionDistractionRequest) -> SessionDistractionResponse:
    """
    Record a distraction event and return a context-aware AI nudge.
    Only normalized hostnames are accepted — never raw URLs.
    """
    session = svc.get_session(payload.session_id)
    task = "your current task"
    distraction_count = 1

    if session:
        count = svc.record_distraction(payload.session_id, payload.site, payload.elapsed_seconds)
        distraction_count = count
        task = session.get("original_task", task)
    else:
        logger.info("session/distraction | unknown session_id=%s", payload.session_id)

    generated = None
    if backboard.enabled:
        try:
            generated = await backboard.generate_nudge(
                task,
                elapsed_minutes=payload.elapsed_seconds // 60,
                distraction=payload.site,
                distraction_count=distraction_count,
            )
        except Exception as err:
            logger.warning("session/distraction | generate_nudge failed: %s", err)

    if generated:
        return SessionDistractionResponse(
            message=generated["message"],
            action=generated["action"],
            source="backboard",
        )

    # Deterministic fallback
    if distraction_count >= 3:
        msg = f"Third time visiting {payload.site}. Just close it."
        act = "Return to your task and do one small thing right now."
    else:
        msg = f"You opened {payload.site}. Your mission is still waiting."
        act = "Close the tab and finish the next 60 seconds of your task."

    return SessionDistractionResponse(message=msg, action=act, source="demo-fallback")


# ---------------------------------------------------------------------------
# Frontend catch-all (must be last)
# ---------------------------------------------------------------------------

@app.get("/{path:path}")
async def frontend(path: str):
    if path:
        requested = (FRONTEND_DIR / path).resolve()
        if requested.is_file() and requested.is_relative_to(FRONTEND_DIR.resolve()):
            return FileResponse(requested)
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"name": "Nudge10", "message": "Frontend files missing."}
