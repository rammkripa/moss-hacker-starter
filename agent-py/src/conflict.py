"""conflict.py — Conflict detection for Mission Bay battlefield copilot.

After each accepted event (passed relevance + dedup), this module checks the last
10 events within a 5-minute sliding window in the same sector for contradictory
claims.  When a contradiction is found, a synthetic "conflict" MissionEvent is
emitted back into the gate pipeline so each soldier's AmbientHandler routes it
independently through relevance → severity → anti-chatter.

eventType union note:
  The existing MissionEvent.eventType field accepts arbitrary strings. Two new
  values are introduced here and must be accounted for in any strict union /
  Literal type annotation used elsewhere:

    "comms"    — radio transmission events from soldiers (e.g. "no contact at A4")
    "conflict" — synthetic contradiction notice emitted by this module

  Callers that enumerate eventTypes (e.g. COOLDOWN_BY_TYPE in ambient.py) should
  add entries for both; defaults are provided here as CONFLICT_COOLDOWN_S.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from uuid import uuid4

logger = logging.getLogger("conflict")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFLICT_WINDOW_S: float = 300.0   # 5 minutes
CONFLICT_LOG_SIZE: int = 10        # max recent events to check against
CONFLICT_COOLDOWN_S: float = 120.0  # suggested cooldown for conflict eventType

# ---------------------------------------------------------------------------
# Claim model
# ---------------------------------------------------------------------------


@dataclass
class Claim:
    """A normalised, comparable assertion extracted from a MissionEvent."""
    sector_id: str | None
    kind: str    # "sector_status" | "vehicle_presence" | "casualty" | "weather"
    value: str   # e.g. "clear", "contested", "present", "none", "injured"

    # Back-reference to originating event (used when building conflict summary)
    _event_id: str = field(default="", repr=False)
    _source_name: str = field(default="", repr=False)
    _timestamp: str = field(default="", repr=False)
    _urgency: str = field(default="low", repr=False)
    _confidence: float = field(default=0.5, repr=False)


# ---------------------------------------------------------------------------
# Claim extractors
# ---------------------------------------------------------------------------

def _sector_from_event(event: dict) -> str | None:
    location = event.get("location") or {}
    return location.get("sectorId") or None


def _source_name(event: dict) -> str:
    source = event.get("source") or {}
    return str(source.get("name", ""))


def _claim_meta(event: dict) -> dict:
    return {
        "_event_id": str(event.get("id", "")),
        "_source_name": _source_name(event),
        "_timestamp": str(event.get("timestamp", "")),
        "_urgency": str(event.get("urgency", "low")),
        "_confidence": float(event.get("confidence", 0.5)),
    }


def _claim_from_status(event: dict) -> list[Claim]:
    """Extract claims from status_report events (satellite: sector_clear / fog)."""
    extracted = event.get("extractedFields") or {}
    summary_lower = str(event.get("summary", "")).lower()
    meta = _claim_meta(event)
    sector = _sector_from_event(event)
    claims: list[Claim] = []

    obs_type = str(extracted.get("observation_type", "")).lower()
    obs_cat = str(extracted.get("observation_category", "")).lower()

    # Sector status: clear / contested / compromised
    if obs_type in ("sector_clear", "sector_status") or "clear" in obs_cat:
        if "clear" in summary_lower or "all clear" in summary_lower or obs_type == "sector_clear":
            claims.append(Claim(sector_id=sector, kind="sector_status", value="clear", **meta))
        elif any(w in summary_lower for w in ("contested", "compromised", "hostile", "threat")):
            claims.append(Claim(sector_id=sector, kind="sector_status", value="contested", **meta))

    # Fog / low-visibility weather claim
    if "fog" in obs_cat or "fog" in summary_lower or "low visibility" in summary_lower:
        claims.append(Claim(sector_id=sector, kind="weather", value="fog", **meta))

    # Vehicle presence via status report
    if "vehicle" in summary_lower:
        if any(w in summary_lower for w in ("no vehicle", "no vehicles", "vehicle-free")):
            claims.append(Claim(sector_id=sector, kind="vehicle_presence", value="none", **meta))
        elif any(w in summary_lower for w in ("vehicles present", "vehicle spotted", "vehicle detected")):
            claims.append(Claim(sector_id=sector, kind="vehicle_presence", value="present", **meta))

    return claims


def _claim_from_visual(event: dict) -> list[Claim]:
    """Extract claims from visual_observation, traffic, crowd, protest events (drone/camera)."""
    extracted = event.get("extractedFields") or {}
    summary_lower = str(event.get("summary", "")).lower()
    meta = _claim_meta(event)
    sector = _sector_from_event(event)
    claims: list[Claim] = []

    obs_cat = str(extracted.get("observation_category", "")).lower()
    obs_type = str(extracted.get("observation_type", "")).lower()

    # Vehicle presence
    if "vehicle" in obs_cat or "vehicle" in obs_type or "vehicle" in summary_lower:
        if any(w in summary_lower for w in ("no vehicle", "no vehicles", "vehicle-free", "vehicles_absent")):
            claims.append(Claim(sector_id=sector, kind="vehicle_presence", value="none", **meta))
        elif any(w in summary_lower for w in (
            "vehicle", "vehicles_present", "vehicles present", "truck", "car", "suv"
        )):
            claims.append(Claim(sector_id=sector, kind="vehicle_presence", value="present", **meta))

    # Sector status from visual
    if any(w in summary_lower for w in ("all clear", "sector clear", "no activity")):
        claims.append(Claim(sector_id=sector, kind="sector_status", value="clear", **meta))
    elif any(w in summary_lower for w in ("contested", "activity detected", "hostile", "crowd blocking")):
        claims.append(Claim(sector_id=sector, kind="sector_status", value="contested", **meta))

    # Casualty
    if extracted.get("casualty_indicator") is True or "casualty" in summary_lower or "injured" in summary_lower:
        claims.append(Claim(sector_id=sector, kind="casualty", value="present", **meta))

    return claims


def _claim_from_incident(event: dict) -> list[Claim]:
    """Extract claims from incident events."""
    extracted = event.get("extractedFields") or {}
    summary_lower = str(event.get("summary", "")).lower()
    meta = _claim_meta(event)
    sector = _sector_from_event(event)
    claims: list[Claim] = []

    # An incident always implies the sector is at least contested (not clear)
    claims.append(Claim(sector_id=sector, kind="sector_status", value="contested", **meta))

    # Casualty
    if extracted.get("casualty_indicator") is True or any(
        w in summary_lower for w in ("casualty", "injured", "wounded", "down")
    ):
        claims.append(Claim(sector_id=sector, kind="casualty", value="present", **meta))

    # Vehicle
    if "vehicle" in summary_lower:
        if any(w in summary_lower for w in ("no vehicle", "no vehicles")):
            claims.append(Claim(sector_id=sector, kind="vehicle_presence", value="none", **meta))
        else:
            claims.append(Claim(sector_id=sector, kind="vehicle_presence", value="present", **meta))

    return claims


def _claim_from_comms(event: dict) -> list[Claim]:
    """Extract claims from radio comms events (soldier reports 'no contact at A4')."""
    extracted = event.get("extractedFields") or {}
    summary_lower = str(event.get("summary", "")).lower()
    meta = _claim_meta(event)
    sector = _sector_from_event(event)

    # Try to extract sector from extractedFields.reported_sector if the location
    # field is missing or ambiguous
    if sector is None:
        sector = extracted.get("reported_sector") or None

    claims: list[Claim] = []

    if any(w in summary_lower for w in ("no contact", "all clear", "sector clear", "negative contact")):
        claims.append(Claim(sector_id=sector, kind="sector_status", value="clear", **meta))
    elif any(w in summary_lower for w in ("contact", "hostile", "taking fire", "engaged", "contested")):
        claims.append(Claim(sector_id=sector, kind="sector_status", value="contested", **meta))

    if "vehicle" in summary_lower:
        if any(w in summary_lower for w in ("no vehicle", "no vehicles")):
            claims.append(Claim(sector_id=sector, kind="vehicle_presence", value="none", **meta))
        else:
            claims.append(Claim(sector_id=sector, kind="vehicle_presence", value="present", **meta))

    return claims


# Registry mapping eventType -> extractor function
CLAIM_EXTRACTORS: dict[str, object] = {
    "status_report":      _claim_from_status,
    "visual_observation": _claim_from_visual,
    "traffic":            _claim_from_visual,
    "crowd":              _claim_from_visual,
    "protest":            _claim_from_visual,
    "incident":           _claim_from_incident,
    "comms":              _claim_from_comms,
}


def extract_claims(event: dict) -> list[Claim]:
    """Dispatch to the appropriate extractor for event['eventType'].

    Returns an empty list for unknown eventTypes or if no claims can be parsed.
    """
    event_type = str(event.get("eventType", ""))
    extractor = CLAIM_EXTRACTORS.get(event_type)
    if extractor is None:
        return []
    try:
        return extractor(event)  # type: ignore[operator]
    except Exception:
        logger.exception("Claim extractor failed for event %s", event.get("id"))
        return []


# ---------------------------------------------------------------------------
# Contradiction compatibility matrix
# ---------------------------------------------------------------------------

# Each kind maps to a set of (v1, v2) pairs that are contradictory.
# Entries are symmetric — the check normalises order.
_CONTRADICTIONS: dict[str, set[frozenset[str]]] = {
    "sector_status": {
        frozenset({"clear", "contested"}),
        frozenset({"clear", "vehicles_present"}),  # vehicles_present implies not clear
    },
    "vehicle_presence": {
        frozenset({"none", "present"}),
    },
    "casualty": set(),   # casualty claims are additive, not contradictory
    "weather": set(),    # skip — weather is not contradictory in this scenario
}


def _is_contradictory(kind: str, v1: str, v2: str) -> bool:
    """Return True when v1 and v2 are known contradictory values for a given kind."""
    if v1 == v2:
        return False
    matrix = _CONTRADICTIONS.get(kind, set())
    return frozenset({v1, v2}) in matrix


# ---------------------------------------------------------------------------
# Urgency ordering for max/min helpers
# ---------------------------------------------------------------------------

_URGENCY_ORDER = {"low": 0, "medium": 1, "high": 2}


def _max_urgency(u1: str, u2: str) -> str:
    if _URGENCY_ORDER.get(u2, 0) > _URGENCY_ORDER.get(u1, 0):
        return u2
    return u1


# ---------------------------------------------------------------------------
# Event log entry (lightweight; does not carry the full dict to save memory)
# ---------------------------------------------------------------------------


@dataclass
class _LogEntry:
    event: dict
    claims: list[Claim]
    accepted_at: float   # time.monotonic()


# ---------------------------------------------------------------------------
# Event log (managed by ConflictDetector, consulted by detect_conflicts)
# ---------------------------------------------------------------------------


class ConflictDetector:
    """Stateful conflict detector. One instance per AmbientHandler / per soldier.

    Usage:
        detector = ConflictDetector()

        # After an event passes relevance + dedup:
        conflicts = detector.check(new_event_dict)
        for conflict_event in conflicts:
            await ambient_handler.on_event_received(conflict_event)

        # Record regardless of whether conflicts were found so future events
        # can check against it:
        detector.record(new_event_dict)
    """

    def __init__(self) -> None:
        self._log: list[_LogEntry] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, new_event: dict) -> list[dict]:
        """Return a (possibly empty) list of synthetic conflict MissionEvent dicts.

        The new_event is NOT yet in self._log when this is called — call record()
        afterwards to append it.
        """
        self._evict_stale()
        new_claims = extract_claims(new_event)
        if not new_claims:
            return []

        conflicts: list[dict] = []
        seen_pairs: set[frozenset[str]] = set()  # avoid duplicate conflict events

        for entry in self._log:
            for new_c in new_claims:
                for old_c in entry.claims:
                    if new_c.sector_id is None or old_c.sector_id is None:
                        continue
                    if new_c.sector_id != old_c.sector_id:
                        continue
                    if new_c.kind != old_c.kind:
                        continue
                    if not _is_contradictory(new_c.kind, new_c.value, old_c.value):
                        continue

                    pair_key = frozenset({new_c._event_id, old_c._event_id})
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    conflicts.append(
                        _build_conflict_event(new_event, entry.event, new_c, old_c)
                    )

        return conflicts

    def record(self, event: dict) -> None:
        """Append event to the rolling log after it has been accepted."""
        self._evict_stale()
        claims = extract_claims(event)
        self._log.append(
            _LogEntry(event=event, claims=claims, accepted_at=time.monotonic())
        )
        # Keep at most CONFLICT_LOG_SIZE entries (beyond the time-based eviction)
        if len(self._log) > CONFLICT_LOG_SIZE:
            self._log = self._log[-CONFLICT_LOG_SIZE:]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict_stale(self) -> None:
        cutoff = time.monotonic() - CONFLICT_WINDOW_S
        self._log = [e for e in self._log if e.accepted_at >= cutoff]


# ---------------------------------------------------------------------------
# Module-level convenience wrapper (used in tests and by AmbientHandler)
# ---------------------------------------------------------------------------

def detect_conflicts(new_event: dict, log: list[dict]) -> list[dict]:
    """Stateless helper: check new_event against a caller-supplied list of recent dicts.

    This is a thin convenience layer for unit tests and one-off calls.
    Production code should use ConflictDetector (which handles time-based eviction
    and the rolling 10-event window automatically).

    Args:
        new_event: The newly accepted MissionEvent dict.
        log: Up to the last 10 accepted event dicts within the 5-minute window.
             The caller is responsible for applying the time / size filter.

    Returns:
        List of synthetic conflict MissionEvent dicts (may be empty).
    """
    new_claims = extract_claims(new_event)
    if not new_claims:
        return []

    conflicts: list[dict] = []
    seen_pairs: set[frozenset[str]] = set()

    for old_event in log:
        old_claims = extract_claims(old_event)
        for new_c in new_claims:
            for old_c in old_claims:
                if new_c.sector_id is None or old_c.sector_id is None:
                    continue
                if new_c.sector_id != old_c.sector_id:
                    continue
                if new_c.kind != old_c.kind:
                    continue
                if not _is_contradictory(new_c.kind, new_c.value, old_c.value):
                    continue

                pair_key = frozenset({new_c._event_id, old_c._event_id})
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                conflicts.append(
                    _build_conflict_event(new_event, old_event, new_c, old_c)
                )

    return conflicts


# ---------------------------------------------------------------------------
# Synthetic conflict event builder
# ---------------------------------------------------------------------------

def _build_conflict_event(
    new_event: dict,
    old_event: dict,
    new_c: Claim,
    old_c: Claim,
) -> dict:
    """Construct a synthetic MissionEvent dict representing the detected conflict."""
    sector = new_c.sector_id or "unknown sector"
    new_src = new_c._source_name or str((new_event.get("source") or {}).get("name", "unknown"))
    old_src = old_c._source_name or str((old_event.get("source") or {}).get("name", "unknown"))
    new_ts = new_c._timestamp or str(new_event.get("timestamp", ""))
    old_ts = old_c._timestamp or str(old_event.get("timestamp", ""))

    summary = (
        f"Conflict: {new_src} reports {new_c.value!r} in {sector} at {new_ts}; "
        f"{old_src} reports {old_c.value!r} in {sector} at {old_ts}. "
        f"Recommend verification."
    )

    merged_urgency = _max_urgency(new_c._urgency, old_c._urgency)
    merged_confidence = min(new_c._confidence, old_c._confidence)

    return {
        "id": f"conflict-{uuid4()}",
        "missionId": new_event.get("missionId", ""),
        "timestamp": new_c._timestamp or "",
        "eventType": "conflict",
        "source": {
            "type": "system",
            "name": "conflict_detector",
            "reliability": "high",
        },
        "summary": summary,
        "entities": [],
        "location": {"sectorId": sector},
        "confidence": round(merged_confidence, 3),
        "urgency": merged_urgency,
        "extractedFields": {
            "left_event_id": str(new_event.get("id", "")),
            "right_event_id": str(old_event.get("id", "")),
            "conflict_kind": new_c.kind,
            "left_value": new_c.value,
            "right_value": old_c.value,
        },
        "affectsWorldState": True,
    }
