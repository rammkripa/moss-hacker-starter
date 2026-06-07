"""test_extensions.py — pytest tests for relevance filter, conflict detection,
and the quiet-during-comms gate integration.

Run with:
    cd agent-py && uv run pytest src/test_extensions.py -v

No external network calls are made. LiveKit and Moss are fully stubbed.
"""

from __future__ import annotations

import asyncio
import sys
import types

# ---------------------------------------------------------------------------
# Stub out livekit.agents IF AND ONLY IF the real SDK isn't installed.
# Using setdefault is not enough because pytest collects this file before
# any test imports the real livekit.agents, which would otherwise leave a
# permanent stub in sys.modules and break later tests (e.g.
# tests/test_comms_and_tracker.py which does `from agent import Assistant`
# and needs the real `Agent` symbol from livekit.agents).
# ---------------------------------------------------------------------------

try:
    import livekit.agents as _real_livekit_agents  # noqa: F401
except ImportError:
    _livekit_agents = types.ModuleType("livekit.agents")
    _livekit_agents.inference = types.SimpleNamespace(LLM=lambda **kw: None)  # type: ignore[attr-defined]
    _livekit = types.ModuleType("livekit")
    _livekit.agents = _livekit_agents  # type: ignore[attr-defined]
    sys.modules["livekit"] = _livekit
    sys.modules["livekit.agents"] = _livekit_agents
    sys.modules["livekit.agents.inference"] = types.ModuleType("livekit.agents.inference")

# ---------------------------------------------------------------------------
# Now safe to import our modules
# ---------------------------------------------------------------------------

import pytest  # noqa: E402

# Add src/ to path so bare imports work regardless of cwd
import os  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))

from ambient import (  # noqa: E402
    Action,
    AmbientHandler,
    AntiChatter,
    GateDecision,
    MissionEvent,
    build_reply_instructions,
)
from conflict import ConflictDetector, detect_conflicts  # noqa: E402
from relevance import RelevanceVerdict, SoldierProfile, is_relevant_to  # noqa: E402


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _soldier(
    callsign: str = "Bravo-3",
    role: str = "recon",
    unit: str = "bravo",
    sector: str = "A5",
) -> SoldierProfile:
    return SoldierProfile(callsign=callsign, role=role, unit=unit, current_sector=sector)


def _event(
    id: str = "ev-1",
    event_type: str = "status_report",
    sector: str | None = "A5",
    source_name: str = "satellite:orbit-1",
    source_type: str = "satellite",
    summary: str = "Sector clear.",
    confidence: float = 0.8,
    urgency: str = "medium",
    extracted: dict | None = None,
    speaker_callsign: str = "",
) -> dict:
    location: dict = {}
    if sector is not None:
        location["sectorId"] = sector
    ef = extracted or {}
    if speaker_callsign:
        ef = {**ef, "speaker_callsign": speaker_callsign}
    return {
        "id": id,
        "missionId": "op-echo",
        "timestamp": "2026-06-06T14:00:00Z",
        "eventType": event_type,
        "summary": summary,
        "confidence": confidence,
        "urgency": urgency,
        "source": {"name": source_name, "type": source_type, "reliability": "high"},
        "location": location,
        "entities": [],
        "extractedFields": ef,
    }


# ---------------------------------------------------------------------------
# Mock SpeakingTracker
# ---------------------------------------------------------------------------

class MockSpeakingTracker:
    """Minimal SpeakingTracker for testing.  Control via .speaking and .elapsed."""

    def __init__(self, speaking: bool = False, elapsed: float = 99.0) -> None:
        self.speaking = speaking
        self.elapsed = elapsed

    def any_speaking(self) -> bool:
        return self.speaking

    def seconds_since_last_change(self) -> float:
        return self.elapsed


# ---------------------------------------------------------------------------
# Mock session + assistant for AmbientHandler integration tests
# ---------------------------------------------------------------------------

class MockSession:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def generate_reply(self, *, instructions: str = "") -> None:
        self.replies.append(instructions)


class MockAssistant:
    def _read_persisted_mission_state(self) -> dict:
        return {"worldState": {}}


# ===========================================================================
# Test 1: Relevance — medic + biosensor for own callsign -> DIRECT
# ===========================================================================

def test_relevance_medic_own_biosensor_is_direct():
    """Medic receives a biosensor status_report whose source name contains
    their own callsign.  Expected: DIRECT."""
    soldier = _soldier(callsign="Singh", role="medic", unit="alpha", sector="Z1")
    event = _event(
        event_type="status_report",
        sector="Z1",
        source_name="biosensor:Singh",
        source_type="biosensor",
        summary="Heart rate elevated, Singh 120bpm.",
    )
    verdict = is_relevant_to(event, soldier)
    assert verdict == RelevanceVerdict.DIRECT, (
        f"Expected DIRECT for medic's own biosensor, got {verdict}"
    )


# ===========================================================================
# Test 2: Relevance — recon role + biosensor for OTHER soldier -> ADJACENT
# ===========================================================================

def test_relevance_recon_other_biosensor_is_adjacent():
    """Bravo-3 (recon, unit=bravo) receives a biosensor event for Singh
    (different unit=alpha).  Expected: ADJACENT because the source references
    a different unit's soldier — relevant but not direct."""
    soldier = _soldier(callsign="Bravo-3", role="recon", unit="bravo", sector="A5")
    event = _event(
        event_type="status_report",
        sector="Z1",                    # Singh's sector — 2 hops from A5 via A6,A7,Z1
        source_name="biosensor:Singh",
        source_type="biosensor",
        summary="Singh vitals nominal.",
    )
    verdict = is_relevant_to(event, soldier)
    # Z1 is within 2-hop reach of A5 (A5->A6->A7->Z1 is 3 hops, but A5->A6->A7 is 2
    # hops and Z1 is adjacent to A7 making it 3 hops total — so this will NOT trigger
    # the 2-hop rule; instead it falls through to the unit-reference rule).
    # "biosensor:Singh" does not contain "bravo" so the unit rule doesn't match.
    # It DOES contain "Singh" which is not Bravo-3's callsign.
    # The medic biosensor-source-name rule is for the soldier's own callsign only.
    # Therefore verdict should be ADJACENT (via the sector being within range or
    # via Z1 adjacency chain) or fall to the 2-hop rule which puts Z1 at 3 hops.
    # Z1 is not in two_hop_reach("A5"): A5 -> {A4,A6} -> {A3,A7} so two-hop = {A3,A4,A6,A7}.
    # Z1 is at 3 hops.  But "biosensor:Singh" — Singh is alpha unit, Bravo-3 is bravo,
    # so unit rule doesn't fire either.
    # The event does NOT match recon ROLE_AFFINITY for status_report from non-satellite.
    # Wait — status_report IS in recon affinity.  Let's re-check:
    #   ROLE_AFFINITY["recon"] includes "status_report" with no source restriction.
    # So it should be DIRECT via the role affinity path (status_report in recon affinity).
    # But the task spec says: "recon biosensor for OTHER soldier -> ADJACENT".
    # Resolution: the spec intent is that Bravo-3 should NOT get DIRECT for Singh's
    # biosensor. We enforce this by checking: if the source is biosensor and the
    # callsign in source_name is NOT this soldier, treat as ADJACENT.
    # Current implementation: recon has "status_report" in affinity WITHOUT the
    # biosensor restriction, so status_report from any source -> DIRECT.
    # The test spec says ADJACENT.  We need the implementation to NOT return DIRECT
    # for a biosensor that belongs to a different soldier.
    # The spec rule is: recon affinity includes status_report from satellite.
    # "biosensor:Singh" is NOT satellite — so for this event the role affinity
    # check should not fire because the source is biosensor, not satellite.
    # But the current ROLE_AFFINITY for recon includes "status_report" without
    # a source restriction. The medic restriction is explicit in the code.
    # We add a corresponding check: for recon, status_report from biosensor
    # where the biosensor is for a different soldier -> not DIRECT via affinity.
    # The test validates the expected ADJACENT behaviour; if implementation
    # returns DIRECT, the test catches the gap.
    assert verdict == RelevanceVerdict.ADJACENT, (
        f"Expected ADJACENT for recon seeing other soldier's biosensor, got {verdict}"
    )


# ===========================================================================
# Test 3: Relevance — weather event -> ADJACENT for either soldier
# ===========================================================================

@pytest.mark.parametrize(
    "callsign,role,unit,sector",
    [
        ("Bravo-3", "recon", "bravo", "A5"),
        ("Singh", "medic", "alpha", "Z1"),
    ],
)
def test_relevance_weather_is_adjacent(callsign, role, unit, sector):
    """Weather events should always be ADJACENT regardless of soldier or sector."""
    soldier = _soldier(callsign=callsign, role=role, unit=unit, sector=sector)
    event = _event(
        event_type="weather",
        sector=None,               # weather often has no sector
        source_name="weather:noaa",
        source_type="weather",
        summary="Dense fog advisory in South Beach area.",
        confidence=0.9,
        urgency="medium",
    )
    verdict = is_relevant_to(event, soldier)
    assert verdict == RelevanceVerdict.ADJACENT, (
        f"Expected ADJACENT for weather event, got {verdict} for {callsign}"
    )


# ===========================================================================
# Test 4: Relevance — drone visual at sector 4 hops away -> UNRELATED
# ===========================================================================

def test_relevance_distant_sector_is_unrelated():
    """Bravo-3 is at A5. A1 is 4 hops away (A5->A4->A3->A2->A1).
    A visual_observation at A1 with no other matching criteria should be UNRELATED."""
    soldier = _soldier(callsign="Bravo-3", role="recon", unit="bravo", sector="A5")
    event = _event(
        event_type="visual_observation",
        sector="A1",
        source_name="drone:alpha-1",
        source_type="drone",
        summary="No activity observed near 2nd and Howard.",
        confidence=0.7,
        urgency="low",
    )
    verdict = is_relevant_to(event, soldier)
    assert verdict == RelevanceVerdict.UNRELATED, (
        f"Expected UNRELATED for 4-hop-away sector, got {verdict}"
    )


# ===========================================================================
# Test 5: Conflict — satellite "A5 clear" then drone "vehicles_present A5"
#          within 5 min -> conflict event emitted with merged urgency/confidence
# ===========================================================================

def test_conflict_clear_vs_vehicles_present_emits_conflict():
    """A satellite status_report says A5 is clear (urgency=low, confidence=0.9).
    A drone visual_observation then reports vehicles present at A5
    (urgency=high, confidence=0.75).
    Expected: detect_conflicts returns exactly one conflict event with:
      - eventType == "conflict"
      - urgency == "high"  (max of low and high)
      - confidence == 0.75  (min of 0.9 and 0.75)
    """
    sat_event = _event(
        id="sat-1",
        event_type="status_report",
        sector="A5",
        source_name="satellite:orbit-1",
        source_type="satellite",
        summary="Sector A5 is clear. No vehicles present. All clear.",
        confidence=0.9,
        urgency="low",
        extracted={"observation_type": "sector_clear"},
    )
    drone_event = _event(
        id="drone-1",
        event_type="visual_observation",
        sector="A5",
        source_name="drone:alpha-drone",
        source_type="drone",
        summary="Vehicles present in sector A5. Multiple trucks spotted.",
        confidence=0.75,
        urgency="high",
        extracted={"observation_category": "vehicle"},
    )

    conflicts = detect_conflicts(drone_event, [sat_event])

    assert len(conflicts) == 1, f"Expected 1 conflict, got {len(conflicts)}: {conflicts}"
    c = conflicts[0]
    assert c["eventType"] == "conflict"
    assert c["urgency"] == "high", f"Expected urgency=high, got {c['urgency']}"
    assert abs(c["confidence"] - 0.75) < 1e-6, f"Expected confidence=0.75, got {c['confidence']}"
    assert c["location"]["sectorId"] == "A5"
    assert "Conflict:" in c["summary"]
    assert c["affectsWorldState"] is True


# ===========================================================================
# Test 6: Conflict — same claim twice (no contradiction) -> no conflict
# ===========================================================================

def test_conflict_same_claim_no_conflict():
    """Two events both reporting A5 as clear should NOT produce a conflict."""
    sat1 = _event(
        id="sat-1",
        event_type="status_report",
        sector="A5",
        source_name="satellite:orbit-1",
        summary="Sector A5 clear. All clear.",
        confidence=0.9,
        urgency="low",
        extracted={"observation_type": "sector_clear"},
    )
    sat2 = _event(
        id="sat-2",
        event_type="status_report",
        sector="A5",
        source_name="satellite:orbit-2",
        summary="A5 all clear. No activity.",
        confidence=0.85,
        urgency="low",
        extracted={"observation_type": "sector_clear"},
    )

    conflicts = detect_conflicts(sat2, [sat1])
    assert conflicts == [], f"Expected no conflicts, got {conflicts}"


# ===========================================================================
# Test 7: Gate — SPEAK decision while any_speaking()==True -> enqueued
# ===========================================================================

@pytest.mark.asyncio
async def test_gate_speak_while_speaking_is_enqueued():
    """When the SpeakingTracker reports any_speaking()==True, a SPEAK decision
    must be enqueued (not immediately delivered via generate_reply)."""
    session = MockSession()
    assistant = MockAssistant()

    # SpeakingTracker reports someone is speaking right now
    tracker = MockSpeakingTracker(speaking=True, elapsed=0.0)

    soldier = _soldier(callsign="Bravo-3", role="recon", unit="bravo", sector="A5")

    handler = AmbientHandler(
        session,
        assistant,
        soldier=soldier,
        speaking_tracker=tracker,
    )

    # Fabricate a high-urgency, high-confidence incident in A5 so the rule gate
    # returns SPEAK without an LLM call.
    me = MissionEvent(
        id="test-ev-1",
        timestamp="2026-06-06T14:05:00Z",
        eventType="incident",
        summary="Armed confrontation at A5.",
        confidence=0.9,
        urgency="high",
        location_guess="A5",
        source="radio:command",
    )

    # We stub run_gate so the test doesn't attempt an LLM call.
    import ambient as ambient_mod

    async def _stub_gate(event, world=None, conversation=None, adjacent=False):
        return GateDecision(
            action=Action.SPEAK,
            severity_score=0.97,
            reason="stub: high urgency",
            suggested_utterance="Armed confrontation at A5.",
        )

    original_run_gate = ambient_mod.run_gate
    ambient_mod.run_gate = _stub_gate
    try:
        # We also need to stub is_relevant_to to return DIRECT so relevance
        # doesn't drop the event before gate.
        import relevance as relevance_mod
        original_is_relevant = relevance_mod.is_relevant_to

        def _stub_relevant(event, soldier):
            return RelevanceVerdict.DIRECT

        relevance_mod.is_relevant_to = _stub_relevant
        try:
            await handler.on_event_received(me)
        finally:
            relevance_mod.is_relevant_to = original_is_relevant
    finally:
        ambient_mod.run_gate = original_run_gate

    # generate_reply must NOT have been called
    assert session.replies == [], (
        f"Expected no replies while speaking, but got: {session.replies}"
    )

    # The event should have been enqueued in the anti-chatter queue
    assert handler._anti_chatter.has_queued(), (
        "Expected the event to be in the pending queue after deferral"
    )
