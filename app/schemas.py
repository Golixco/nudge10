from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Existing mission/nudge schemas (preserved exactly)
# ---------------------------------------------------------------------------

class MissionRequest(BaseModel):
    task: str = Field(min_length=1, max_length=500)
    minutes: int = Field(default=10, ge=5, le=25)


class MissionResponse(BaseModel):
    title: str
    action: str
    why: str
    minutes: int
    source: str


class NudgeRequest(BaseModel):
    task: str = Field(min_length=1, max_length=500)
    elapsed_minutes: int = Field(ge=0, le=120)
    distraction: str = Field(default="unknown", max_length=100)
    distraction_count: int = Field(default=1, ge=1, le=50)


class NudgeResponse(BaseModel):
    message: str
    action: str
    source: str


# ---------------------------------------------------------------------------
# Session schemas
# ---------------------------------------------------------------------------

class MissionPayload(BaseModel):
    """Embedded mission data inside a session response."""
    title: str
    action: str
    reason: str
    source: str


class SessionStartRequest(BaseModel):
    task: str = Field(min_length=1, max_length=500)
    duration_minutes: int = Field(default=10, ge=5, le=25)


class SessionStartResponse(BaseModel):
    session_id: str
    mission: MissionPayload
    duration_minutes: int
    started_at: str  # ISO-8601


class SessionCompleteRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    elapsed_seconds: int = Field(ge=0, le=1800)


class SessionCompleteResponse(BaseModel):
    session_id: str
    status: str  # "completed"
    elapsed_seconds: int
    message: str
    source: str


class SessionAbandonRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    elapsed_seconds: int = Field(ge=0, le=1800)
    reason: Optional[str] = Field(default=None, max_length=300)


class SessionAbandonResponse(BaseModel):
    session_id: str
    status: str  # "abandoned"
    message: str
    next_step: Optional[str] = None
    source: str


class SessionDistractionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    # normalized hostname only — never raw URLs or page content
    site: str = Field(min_length=1, max_length=100)
    elapsed_seconds: int = Field(ge=0, le=1800)


class SessionDistractionResponse(BaseModel):
    message: str
    action: str
    source: str
