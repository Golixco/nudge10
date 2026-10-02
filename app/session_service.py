"""
session_service.py — Nudge10 focus-session lifecycle.

Design decisions:
  - No database. Sessions are kept in a process-level dict for the duration of
    the request cycle. The browser's localStorage is the durable client store.
  - The backend receives lifecycle events (complete / abandon / distraction) so
    the AI can learn from them, but does not need to store the full session tree.
  - Memory writes to Backboard are gated by should_remember_event() — only
    durable, recurring signals are persisted. Individual isolated events are not.

Session statuses: created | active | completed | abandoned
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process session registry (lifespan of the server process only)
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}


def create_session(
    task: str,
    mission_title: str,
    mission_action: str,
    mission_reason: str,
    mission_source: str,
    duration_minutes: int,
) -> dict[str, Any]:
    """Create and register a new session. Returns the session dict."""
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    session: dict[str, Any] = {
        "session_id": session_id,
        "original_task": task,
        "mission_title": mission_title,
        "mission_action": mission_action,
        "mission_reason": mission_reason,
        "mission_source": mission_source,
        "duration_minutes": duration_minutes,
        "started_at": now,
        "ended_at": None,
        "status": "created",
        "distractions": [],
        "distraction_count": 0,
    }
    _sessions[session_id] = session
    logger.info("session created | id=%s | task=%.60r", session_id, task)
    return session


def get_session(session_id: str) -> dict[str, Any] | None:
    """Return session dict or None if not found."""
    return _sessions.get(session_id)


def mark_complete(session_id: str, elapsed_seconds: int) -> bool:
    s = _sessions.get(session_id)
    if not s:
        return False
    s["status"] = "completed"
    s["elapsed_seconds"] = elapsed_seconds
    s["ended_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "session completed | id=%s | elapsed=%ds | distractions=%d",
        session_id, elapsed_seconds, s["distraction_count"],
    )
    return True


def mark_abandoned(session_id: str, elapsed_seconds: int, reason: Optional[str]) -> bool:
    s = _sessions.get(session_id)
    if not s:
        return False
    s["status"] = "abandoned"
    s["elapsed_seconds"] = elapsed_seconds
    s["abandon_reason"] = reason
    s["ended_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "session abandoned | id=%s | elapsed=%ds | reason=%.60r",
        session_id, elapsed_seconds, reason,
    )
    return True


def record_distraction(session_id: str, site: str, elapsed_seconds: int) -> int:
    """
    Record a distraction event. Returns new distraction count.
    site must be a normalized hostname — never a raw URL.
    """
    s = _sessions.get(session_id)
    if not s:
        return 0
    normalized = site.lower().strip()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    s["distractions"].append({"site": normalized, "at_seconds": elapsed_seconds})
    s["distraction_count"] = len(s["distractions"])
    logger.info(
        "distraction | id=%s | site=%s | elapsed=%ds | count=%d",
        session_id, normalized, elapsed_seconds, s["distraction_count"],
    )
    return s["distraction_count"]


# ---------------------------------------------------------------------------
# Behavioral memory gating
# ---------------------------------------------------------------------------

_MIN_MEANINGFUL_SECONDS = 120
_DISTRACTION_PATTERN_THRESHOLD = 2


def should_remember_completion(session: dict[str, Any]) -> tuple[bool, str]:
    """
    Decide whether a completed session is worth committing to Backboard memory.
    Only recurring distraction patterns qualify — single events do not.
    """
    elapsed = session.get("elapsed_seconds", 0)
    distractions = session.get("distractions", [])
    duration_min = session.get("duration_minutes", 10)

    if elapsed < _MIN_MEANINGFUL_SECONDS:
        return False, ""

    site_counts: dict[str, int] = {}
    for d in distractions:
        site = d.get("site", "unknown")
        site_counts[site] = site_counts.get(site, 0) + 1

    recurring_sites = [s for s, c in site_counts.items() if c >= _DISTRACTION_PATTERN_THRESHOLD]

    if recurring_sites:
        sites_str = ", ".join(recurring_sites)
        return True, (
            f"User completed a {duration_min}-minute focus session but was repeatedly "
            f"distracted by: {sites_str}."
        )

    return False, ""


def should_remember_abandonment(session: dict[str, Any]) -> tuple[bool, str]:
    """
    Decide whether an abandoned session is worth committing to memory.
    Conservative: only recurring distraction patterns with meaningful elapsed time.
    """
    elapsed = session.get("elapsed_seconds", 0)
    distractions = session.get("distractions", [])
    duration_min = session.get("duration_minutes", 10)

    if elapsed < _MIN_MEANINGFUL_SECONDS:
        return False, ""

    site_counts: dict[str, int] = {}
    for d in distractions:
        site = d.get("site", "unknown")
        site_counts[site] = site_counts.get(site, 0) + 1

    recurring_sites = [s for s, c in site_counts.items() if c >= _DISTRACTION_PATTERN_THRESHOLD]

    if recurring_sites:
        sites_str = ", ".join(recurring_sites)
        return True, (
            f"User abandoned a {duration_min}-minute focus session after "
            f"approximately {elapsed // 60} minutes; "
            f"was repeatedly distracted by: {sites_str}."
        )

    return False, ""


def should_remember_distraction(
    session: dict[str, Any],
    site: str,
    elapsed_seconds: int,
) -> tuple[bool, str]:
    """
    Per-event distraction memory is ALWAYS disabled by design.
    Patterns are handled at complete/abandon time only.
    """
    return False, ""
