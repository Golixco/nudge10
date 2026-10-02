from pydantic import BaseModel, Field


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
