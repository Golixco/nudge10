from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .backboard_service import backboard
from .schemas import MissionRequest, MissionResponse, NudgeRequest, NudgeResponse

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="Nudge10", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {"ok": True, "ai_enabled": backboard.enabled}


@app.post("/api/mission", response_model=MissionResponse)
async def create_mission(payload: MissionRequest) -> MissionResponse:
    generated = await backboard.create_mission(payload.task, payload.minutes)
    if generated:
        return MissionResponse(**generated, minutes=payload.minutes, source="backboard")
    return MissionResponse(
        title="Start with one tiny step",
        action=f"Work only on the first concrete step of: {payload.task}",
        why="Starting small lowers the friction to begin.",
        minutes=payload.minutes,
        source="demo-fallback",
    )


@app.post("/api/nudge", response_model=NudgeResponse)
async def create_nudge(payload: NudgeRequest) -> NudgeResponse:
    generated = await backboard.generate_nudge(payload.task, payload.elapsed_minutes, payload.distraction, payload.distraction_count)
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
