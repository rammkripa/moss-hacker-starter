"""_base.py — Shared utilities for all Operation South Beach feed workers.

All feeds:
  - POST normalized MissionEvent JSON to MISSION_INGEST_URL
  - Authenticate with Authorization: Bearer $MISSION_INGEST_SECRET
  - Use DEMO_T0 (set by worker.py at startup) for deterministic offset logic
  - Emit scripted events from demo_script.py as their offset_s elapses
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp

logger = logging.getLogger("feeds.base")

# ---------------------------------------------------------------------------
# Runtime configuration (read from environment / set by worker.py)
# ---------------------------------------------------------------------------

MISSION_INGEST_URL: str = os.getenv("MISSION_INGEST_URL", "http://localhost:3000/api/mission/ingest")
MISSION_INGEST_SECRET: str = os.getenv("MISSION_INGEST_SECRET", "dev-secret")

# Set by worker.py before launching feeds. Monotonic start time so offsets are
# stable across any wall-clock skew.
DEMO_T0: float = 0.0


def set_demo_t0(t0: float) -> None:
    """Called by worker.py once at startup."""
    global DEMO_T0
    DEMO_T0 = t0


def elapsed_s() -> float:
    """Seconds since DEMO_T0."""
    return time.monotonic() - DEMO_T0


# ---------------------------------------------------------------------------
# Sector coordinate lookup
# ---------------------------------------------------------------------------

SECTOR_COORDS: dict[str, dict[str, float]] = {
    "A1": {"lat": 37.7869, "lng": -122.3971},  # 2nd & Howard
    "A2": {"lat": 37.7851, "lng": -122.3964},  # 2nd & Folsom
    "A3": {"lat": 37.7834, "lng": -122.3957},  # 2nd & Harrison
    "A4": {"lat": 37.7816, "lng": -122.3950},  # 2nd & Bryant
    "A5": {"lat": 37.7800, "lng": -122.3942},  # 2nd & Brannan (South Park block)
    "A6": {"lat": 37.7784, "lng": -122.3934},  # 2nd & Townsend
    "A7": {"lat": 37.7768, "lng": -122.3927},  # 2nd & King
    "Z1": {"lat": 37.7751, "lng": -122.3878},  # South Beach Marina
}

SECTOR_DESCRIPTIONS: dict[str, str] = {
    "A1": "2nd St / Howard St",
    "A2": "2nd St / Folsom St",
    "A3": "2nd St / Harrison St",
    "A4": "2nd St / Bryant St",
    "A5": "2nd St / Brannan St (South Park block)",
    "A6": "2nd St / Townsend St",
    "A7": "2nd St / King St",
    "Z1": "South Beach Marina (staging)",
}


# ---------------------------------------------------------------------------
# MissionEvent builder
# ---------------------------------------------------------------------------

MISSION_ID = "operation-south-beach"


def build_event(
    event_type: str,
    summary: str,
    confidence: float,
    urgency: str,
    source_name: str,
    sector_id: str,
    extracted_fields: dict[str, Any] | None = None,
    risk_assessment: str = "",
    source_type: str = "system",
    source_reliability: str = "high",
    affects_world_state: bool = True,
) -> dict[str, Any]:
    """Build a normalized MissionEvent dict matching the Zod schema at
    /api/mission/ingest. All fields required by the schema are populated.
    """
    coords = SECTOR_COORDS.get(sector_id, {"lat": 37.7800, "lng": -122.3942})
    # Zod schema expects coordinates as {x, y} — x=lng, y=lat.
    coordinates = {"x": coords.get("lng", 0.0), "y": coords.get("lat", 0.0)}
    desc = SECTOR_DESCRIPTIONS.get(sector_id, sector_id)
    fields = dict(extracted_fields or {})
    if risk_assessment:
        fields["risk_assessment"] = risk_assessment
    return {
        "id": str(uuid.uuid4()),
        "missionId": MISSION_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "eventType": event_type,
        "summary": summary,
        "entities": [],
        "confidence": round(confidence, 3),
        "urgency": urgency,
        "source": {
            "type": source_type,
            "name": source_name,
            "reliability": source_reliability,
        },
        "location": {
            "sectorId": sector_id,
            "coordinates": coordinates,
            "description": desc,
        },
        "extractedFields": fields,
        "affectsWorldState": affects_world_state,
    }


def _inject_ids(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure a scripted payload satisfies the Zod MissionEventSchema.

    Adds a fresh id + timestamp, and idempotently backfills the required
    fields that scripted payloads in demo_script.py don't carry: missionId,
    entities, affectsWorldState, source.reliability, and translates
    location.coordinates from {lat,lng} to {x,y}.
    """
    result = dict(payload)
    result["id"] = str(uuid.uuid4())
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    result.setdefault("missionId", MISSION_ID)
    result.setdefault("entities", [])
    result.setdefault("affectsWorldState", True)

    src = dict(result.get("source") or {})
    src.setdefault("type", "system")
    src.setdefault("name", "scripted")
    src.setdefault("reliability", "high")
    result["source"] = src

    loc = result.get("location")
    if isinstance(loc, dict):
        coords = loc.get("coordinates")
        if isinstance(coords, dict) and "lat" in coords and "lng" in coords and "x" not in coords:
            loc = dict(loc)
            loc["coordinates"] = {"x": coords["lng"], "y": coords["lat"]}
            result["location"] = loc

    return result


# ---------------------------------------------------------------------------
# HTTP ingest poster
# ---------------------------------------------------------------------------

_SESSION: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        _SESSION = aiohttp.ClientSession()
    return _SESSION


async def post_event(payload: dict[str, Any]) -> bool:
    """POST a MissionEvent to the ingest endpoint. Returns True on success.

    The ingest endpoint at /api/mission/ingest expects `{ "event": <MissionEvent> }`,
    so we wrap here rather than at every feed call site.
    """
    headers = {
        "Authorization": f"Bearer {MISSION_INGEST_SECRET}",
        "Content-Type": "application/json",
    }
    try:
        session = await _get_session()
        async with session.post(
            MISSION_INGEST_URL,
            json={"event": payload},
            headers=headers,
            # The ingest route writes to Moss (~2-4s) AND pushes to LiveKit
            # (~0.3s), so allow a generous timeout for the initial calls
            # before the Moss connection is warm.
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status in (200, 201, 202):
                logger.debug("Posted event %s → %s", payload.get("id"), resp.status)
                return True
            body = await resp.text()
            logger.warning(
                "Ingest returned %s for event %s: %s",
                resp.status,
                payload.get("id"),
                body[:200],
            )
            return False
    except aiohttp.ClientError as exc:
        logger.error("HTTP error posting event %s: %s", payload.get("id"), exc)
        return False
    except asyncio.TimeoutError:
        logger.error("Timeout posting event %s", payload.get("id"))
        return False


# ---------------------------------------------------------------------------
# Scripted-event dispatcher mixin
# ---------------------------------------------------------------------------

class ScriptedFeedMixin:
    """Mixin that tracks which scripted events have been emitted.

    Usage: subclass this and call `maybe_emit_scripted(feed_name)` on each
    cadence tick. It will emit any scripted event whose offset_s has elapsed
    and that hasn't been posted yet.
    """

    def __init__(self) -> None:
        self._emitted_offsets: set[int] = set()

    async def maybe_emit_scripted(self, feed_name: str) -> None:
        """Emit any pending scripted events for this feed."""
        # Import demo_script from the scripts package root (sys.path includes
        # the scripts/ directory when running via worker.py or tests).
        try:
            from demo_script import events_for_feed  # scripts/ is on sys.path
        except ImportError:
            from scripts.demo_script import events_for_feed  # fallback for other callers

        now = elapsed_s()
        for offset_s, payload in events_for_feed(feed_name):
            if offset_s <= now and offset_s not in self._emitted_offsets:
                self._emitted_offsets.add(offset_s)
                enriched = _inject_ids(payload)
                logger.info(
                    "[%s] Emitting scripted event offset=%ds: %s",
                    feed_name,
                    offset_s,
                    enriched.get("summary", "")[:80],
                )
                await post_event(enriched)
