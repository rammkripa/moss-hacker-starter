"""relevance.py — Per-soldier relevance filter for Mission Bay battlefield copilot.

Runs BEFORE the existing severity gate in ambient.py. Pure rule-based, no LLM cost.

Design note: kept as a separate module (not folded into ambient.py) for three reasons:
  1. Unit-testable in isolation without instantiating AmbientHandler or any async code.
  2. The adjacency map and role-affinity tables are domain data that will grow; a
     dedicated file keeps ambient.py focused on gate + anti-chatter mechanics.
  3. The conflict detector (conflict.py) also imports ADJACENT_SECTORS to compute
     two-hop reach; having it here avoids a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


# ---------------------------------------------------------------------------
# Soldier profile (treat as given — passed in from agent.py entrypoint)
# ---------------------------------------------------------------------------


@dataclass
class SoldierProfile:
    callsign: str          # e.g. "Bravo-3" or "Singh"
    role: Literal["recon", "medic", "comms", "command", "logistics"]
    unit: str              # e.g. "bravo" or "alpha"
    current_sector: str    # e.g. "A5" or "Z1"


# ---------------------------------------------------------------------------
# Sector adjacency graph (2nd Street corridor + South Beach Marina)
#
# Canonical sector grid:
#   A1: 2nd/Howard     A2: 2nd/Folsom    A3: 2nd/Harrison
#   A4: 2nd/Bryant     A5: 2nd/Brannan   A6: 2nd/Townsend
#   A7: 2nd/King       Z1: South Beach Marina
#
# Adjacency is symmetric and represents immediate 1-hop neighbours.
# ---------------------------------------------------------------------------

ADJACENT_SECTORS: dict[str, set[str]] = {
    "A1": {"A2"},
    "A2": {"A1", "A3"},
    "A3": {"A2", "A4"},
    "A4": {"A3", "A5"},
    "A5": {"A4", "A6"},
    "A6": {"A5", "A7"},
    "A7": {"A6", "Z1"},
    "Z1": {"A7"},
}


def _two_hop_reach(sector: str) -> set[str]:
    """Return all sectors reachable within 2 hops (not including the sector itself)."""
    one_hop: set[str] = ADJACENT_SECTORS.get(sector, set())
    two_hop: set[str] = set()
    for neighbour in one_hop:
        two_hop |= ADJACENT_SECTORS.get(neighbour, set())
    # exclude the origin sector itself
    return (one_hop | two_hop) - {sector}


# ---------------------------------------------------------------------------
# Role affinity: which eventTypes are directly relevant by role
# ---------------------------------------------------------------------------

ROLE_AFFINITY: dict[str, set[str]] = {
    "recon": {
        "visual_observation",
        "traffic",
        "crowd",
        "protest",
        "incident",
        "status_report",   # satellite status reports matter for recon
    },
    "medic": {
        "status_report",   # only when source is biosensor — enforced in is_relevant_to
        "incident",
        # casualty_indicator handled dynamically via extractedFields
    },
    "comms": {
        "comms",
        "status_report",
    },
    "command": {
        # command gets everything through normal severity — no extra affinity filter
    },
    "logistics": {
        "traffic",
        "route_change",
        "weather",
    },
}

# eventTypes that are always at least ADJACENT (general mission-wide updates)
GENERAL_MISSION_TYPES: set[str] = {"weather", "notam", "admin", "mission_update"}


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


class RelevanceVerdict(Enum):
    DIRECT = "direct"
    ADJACENT = "adjacent"
    UNRELATED = "unrelated"


# ---------------------------------------------------------------------------
# Main filter function
# ---------------------------------------------------------------------------


def is_relevant_to(event: dict, soldier: SoldierProfile) -> RelevanceVerdict:
    """Classify an event's relevance to a specific soldier.

    Args:
        event: Raw MissionEvent dict (wire-format fields).
        soldier: The SoldierProfile for the soldier receiving this event.

    Returns:
        RelevanceVerdict.DIRECT     — normal severity gate applies
        RelevanceVerdict.ADJACENT   — stricter SPEAK threshold
        RelevanceVerdict.UNRELATED  — forced DROP before gate
    """
    event_type: str = str(event.get("eventType", ""))
    location: dict = event.get("location") or {}
    event_sector: str | None = location.get("sectorId") or None
    source: dict = event.get("source") or {}
    source_name: str = str(source.get("name", ""))
    extracted: dict = event.get("extractedFields") or {}
    speaker_callsign: str = str(extracted.get("speaker_callsign", ""))

    # -----------------------------------------------------------------------
    # DIRECT checks — own comms flag is noted in docstring; we still return
    # DIRECT so the gate can decide (it may DROP as self-chatter, but that is
    # the gate's responsibility, not the relevance filter's).
    # -----------------------------------------------------------------------

    # 1a. Event sector matches soldier's current sector OR its direct neighbour
    if event_sector:
        if event_sector == soldier.current_sector:
            return RelevanceVerdict.DIRECT
        if event_sector in ADJACENT_SECTORS.get(soldier.current_sector, set()):
            return RelevanceVerdict.DIRECT

    # 1b. Event's speaker_callsign == this soldier (own comms — flag, still DIRECT)
    if speaker_callsign and speaker_callsign == soldier.callsign:
        return RelevanceVerdict.DIRECT

    # 1c. Source name explicitly references this soldier's callsign
    #     e.g.  "biosensor:Bravo-3"  or  "radio:Singh"
    if soldier.callsign.lower() in source_name.lower():
        return RelevanceVerdict.DIRECT

    # 1d. Role affinity match.
    #
    # Role affinity makes an event DIRECT only when the event EITHER has no
    # sector (mission-wide information) OR its sector is already close enough
    # to the soldier (same sector or direct 1-hop neighbour — caught above).
    # If a sector IS present and it is beyond 1 hop, role affinity alone does
    # not override geographic distance; the event may still be ADJACENT (step 2).
    # This prevents a recon soldier from receiving DIRECT for a visual_observation
    # that is 4 hops away just because the eventType matches their affinity.
    affinity = ROLE_AFFINITY.get(soldier.role, set())
    if event_type in affinity:
        # Sector present AND beyond 1 hop -> affinity cannot grant DIRECT
        if event_sector is not None:
            one_hop = ADJACENT_SECTORS.get(soldier.current_sector, set())
            if event_sector != soldier.current_sector and event_sector not in one_hop:
                pass  # fall through to ADJACENT checks
            else:
                # sector is present and is 0 or 1 hop — already handled above
                # (lines 1a caught same-sector/1-hop); this branch is unreachable
                # but kept for clarity.
                pass
        else:
            # No sector — role affinity fires for mission-wide events
            if soldier.role == "medic" and event_type == "status_report":
                # Medic only cares about biosensor status reports without a sector
                source_type: str = str(source.get("type", ""))
                if "biosensor" in source_name.lower() or "biosensor" in source_type.lower():
                    return RelevanceVerdict.DIRECT
                # Fall through — may still qualify as ADJACENT
            else:
                return RelevanceVerdict.DIRECT

    # Role affinity with sector (close sectors caught by 1a; distant fall through)
    # This separate block handles events where sector is present AND within 1 hop
    # but were not already returned above (edge case guard — in practice 1a covers this).
    # Medic biosensor restriction applied here too for sectorised events.
    if event_type in affinity and event_sector is not None:
        one_hop = ADJACENT_SECTORS.get(soldier.current_sector, set())
        in_range = (event_sector == soldier.current_sector) or (event_sector in one_hop)
        if in_range:
            if soldier.role == "medic" and event_type == "status_report":
                source_type = str(source.get("type", ""))
                is_biosensor = (
                    "biosensor" in source_name.lower()
                    or "biosensor" in source_type.lower()
                )
                if is_biosensor:
                    # Only DIRECT if the biosensor is for THIS soldier
                    if soldier.callsign.lower() not in source_name.lower():
                        pass  # other soldier's biosensor -> fall to ADJACENT
                    # else: soldier's own biosensor already caught in 1c
                # non-biosensor status_report for medic -> fall through
            elif soldier.role == "recon" and event_type == "status_report":
                # Recon gets status_report DIRECT only from satellite, not biosensor
                source_type = str(source.get("type", ""))
                is_biosensor = (
                    "biosensor" in source_name.lower()
                    or "biosensor" in source_type.lower()
                )
                if not is_biosensor:
                    return RelevanceVerdict.DIRECT
                # biosensor status_report for recon -> fall to ADJACENT
            else:
                return RelevanceVerdict.DIRECT

    # 1e. Casualty indicator in extractedFields (medic always DIRECT; others ADJACENT)
    if extracted.get("casualty_indicator") is True:
        if soldier.role == "medic":
            return RelevanceVerdict.DIRECT
        # Other roles fall through — will be caught as ADJACENT below

    # -----------------------------------------------------------------------
    # ADJACENT checks
    # -----------------------------------------------------------------------

    # 2a. Event sector is within 2 hops of soldier's current sector
    if event_sector and event_sector in _two_hop_reach(soldier.current_sector):
        return RelevanceVerdict.ADJACENT

    # 2b. Event references the soldier's unit (teammate data, not directly this soldier)
    #     e.g.  "biosensor:Singh"  is ADJACENT for Bravo-3 (different unit, but ally)
    unit_lower = soldier.unit.lower()
    # Any source name that contains a known unit prefix but NOT this soldier's callsign
    if unit_lower and unit_lower in source_name.lower():
        if soldier.callsign.lower() not in source_name.lower():
            return RelevanceVerdict.ADJACENT

    # 2c. Casualty indicator outside medic role
    if extracted.get("casualty_indicator") is True:
        return RelevanceVerdict.ADJACENT

    # 2d. General mission update types (weather, NOTAMs, admin)
    if event_type in GENERAL_MISSION_TYPES:
        return RelevanceVerdict.ADJACENT

    # 2e. Non-biosensor status_report for medic (fell through from 1d)
    if soldier.role == "medic" and event_type == "status_report":
        return RelevanceVerdict.ADJACENT

    # 2f. Biosensor data from another soldier in the AO (not own callsign).
    #     "biosensor:Singh" is ADJACENT for Bravo-3 — teammate health is always
    #     worth monitoring even if the sector is beyond 2 hops.
    #     The own-callsign case is handled earlier (rule 1c -> DIRECT).
    source_name_lower = source_name.lower()
    if "biosensor" in source_name_lower and soldier.callsign.lower() not in source_name_lower:
        return RelevanceVerdict.ADJACENT

    # -----------------------------------------------------------------------
    # UNRELATED — nothing matched
    # -----------------------------------------------------------------------
    return RelevanceVerdict.UNRELATED
