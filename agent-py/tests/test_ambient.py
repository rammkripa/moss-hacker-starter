"""Tests for the ambient proactive-speech severity gate.

These are deterministic unit tests. The LLM classifier path is stubbed so
no network or API credentials are required. Run with:

    cd agent-py && uv run pytest tests/test_ambient.py -v
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ambient import (
    Action,
    AmbientHandler,
    AntiChatter,
    GateDecision,
    MissionEvent,
    build_reply_instructions,
    rule_gate,
    run_gate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_event(
    *,
    event_id: str = "evt-001",
    event_type: str = "road_closure",
    summary: str = "Bay Bridge eastbound closed after crash",
    confidence: float = 0.85,
    urgency: str = "high",
    risk_assessment: str = "Blocks primary route",
    location_guess: str = "Bay Bridge",
    source: str = "sfpd",
    timestamp: str = "2026-06-06T13:05:00Z",
) -> MissionEvent:
    return MissionEvent(
        id=event_id,
        timestamp=timestamp,
        eventType=event_type,
        summary=summary,
        confidence=confidence,
        urgency=urgency,
        risk_assessment=risk_assessment,
        location_guess=location_guess,
        source=source,
    )


def make_session_mock() -> MagicMock:
    session = MagicMock()
    session.generate_reply = AsyncMock(return_value=None)
    # No chat context by default
    session.chat_ctx = None
    return session


def make_assistant_mock(world_state: dict | None = None) -> MagicMock:
    assistant = MagicMock()
    state = world_state or {
        "worldState": {
            "currentObjective": "Reach Moscone by 14:30",
            "routeStatus": {"route-a": {"status": "clear"}},
            "knownRisks": [],
            "recentChanges": [],
        },
        "injectedEvents": [],
    }
    assistant._read_persisted_mission_state.return_value = state
    return assistant


# ---------------------------------------------------------------------------
# 1. Rule gate — basic routing
# ---------------------------------------------------------------------------


class TestRuleGate:
    def test_high_urgency_high_confidence_speaks(self):
        event = make_event(urgency="high", confidence=0.85)
        decision = rule_gate(event)
        assert decision is not None
        assert decision.action == Action.SPEAK
        assert decision.severity_score >= 0.85

    def test_high_urgency_confidence_exactly_05_speaks(self):
        event = make_event(urgency="high", confidence=0.5)
        decision = rule_gate(event)
        assert decision is not None
        assert decision.action == Action.SPEAK

    def test_high_urgency_below_threshold_goes_to_llm(self):
        """High urgency but confidence=0.40 is below the DIRECT speak threshold
        of 0.45 — rule defers to LLM."""
        event = make_event(urgency="high", confidence=0.40)
        decision = rule_gate(event)
        assert decision is None  # LLM gate needed

    def test_low_urgency_high_confidence_stashes_for_direct_soldier(self):
        """DIRECT mode: a low-urgency but credible event is kept available
        silently (stash) so the soldier can ask about it, but the agent
        doesn't proactively interrupt them."""
        event = make_event(
            urgency="low",
            confidence=0.9,
            summary="Bravo-3 biosensor: HR 78, mobility nominal",
        )
        decision = rule_gate(event)
        assert decision is not None
        assert decision.action == Action.STASH

    def test_low_urgency_low_confidence_drops(self):
        event = make_event(urgency="low", confidence=0.4)
        decision = rule_gate(event)
        assert decision is not None
        assert decision.action == Action.DROP

    def test_low_confidence_drops_regardless_of_urgency(self):
        """Confidence below noise floor (0.3) drops even for medium urgency."""
        event = make_event(urgency="medium", confidence=0.25)
        decision = rule_gate(event)
        assert decision is not None
        assert decision.action == Action.DROP

    def test_medium_urgency_direct_speaks(self):
        """DIRECT mode: medium urgency events relevant to the soldier are
        spoken proactively — that's the point of per-soldier relevance."""
        event = make_event(urgency="medium", confidence=0.6)
        decision = rule_gate(event)
        assert decision is not None
        assert decision.action == Action.SPEAK

    def test_confidence_zero_drops(self):
        event = make_event(urgency="high", confidence=0.0)
        decision = rule_gate(event)
        assert decision is not None
        assert decision.action == Action.DROP


# ---------------------------------------------------------------------------
# 2. run_gate — gate returns DROP for a low-urgency noise event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_drops_low_urgency_noise_event():
    """REQUIRED: Gate returns DROP for a low-urgency, low-confidence noise event."""
    event = make_event(
        event_id="noise-001",
        event_type="weather",
        summary="Fog advisory issued for Twin Peaks — no route impact expected",
        confidence=0.20,
        urgency="low",
    )
    decision = await run_gate(event)
    assert decision.action == Action.DROP
    assert decision.severity_score < 0.35


@pytest.mark.asyncio
async def test_gate_drops_distant_311_complaint():
    """311 noise complaint unrelated to routes is dropped by rules."""
    event = make_event(
        event_id="noise-002",
        event_type="noise_complaint",
        summary="311 noise complaint filed near Ocean Beach — no route relevance",
        confidence=0.15,
        urgency="low",
    )
    decision = await run_gate(event)
    assert decision.action == Action.DROP


# ---------------------------------------------------------------------------
# 3. run_gate — gate returns SPEAK for high-urgency on-route event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_speaks_for_high_urgency_on_route_event():
    """REQUIRED: Gate returns SPEAK for a high-urgency on-route event."""
    event = make_event(
        event_id="critical-001",
        event_type="road_closure",
        summary="Bay Bridge eastbound fully closed after multi-vehicle crash at toll plaza",
        confidence=0.9,
        urgency="high",
        risk_assessment="Blocks Route A entirely — reroute to Route C required",
        location_guess="Bay Bridge toll plaza",
    )
    decision = await run_gate(event)
    assert decision.action == Action.SPEAK
    assert decision.severity_score >= 0.85


@pytest.mark.asyncio
async def test_gate_speak_decision_has_valid_suggested_utterance():
    """A SPEAK decision from the rule gate has no suggested_utterance by default;
    the instructions builder should compensate. Verify the fallback path."""
    event = make_event(urgency="high", confidence=0.88)
    decision = await run_gate(event)
    assert decision.action == Action.SPEAK
    # Rule gate doesn't generate suggested_utterance — verify instructions builder handles it
    instructions = build_reply_instructions(event, decision)
    assert event.summary in instructions
    assert event.eventType in instructions
    # The instructions explicitly tell the agent to stay in character as
    # Mission Bay — so the literal string IS expected to appear. This is a
    # character-anchor for the model, not a leak of system identity.
    assert "Mission Bay" in instructions
    assert len(instructions) > 50


# ---------------------------------------------------------------------------
# 4. Cooldown prevents two SPEAK decisions for the same eventType within 30s
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cooldown_suppresses_second_speak_within_window():
    """REQUIRED: Cooldown prevents two SPEAK decisions within 30s for same eventType."""
    session = make_session_mock()
    assistant = make_assistant_mock()
    handler = AmbientHandler(session=session, assistant=assistant)

    event_1 = make_event(
        event_id="crowd-001",
        event_type="protest",
        summary="Howard St protest grew to 200 people blocking traffic",
        confidence=0.8,
        urgency="high",
    )
    event_2 = make_event(
        event_id="crowd-002",
        event_type="protest",
        summary="Howard St protest now 250 people, police en route",
        confidence=0.85,
        urgency="high",
    )

    # First event should speak
    await handler.on_event_received(event_1)
    assert session.generate_reply.call_count == 1

    # Second event arrives immediately (within cooldown) — should be suppressed
    await handler.on_event_received(event_2)
    assert session.generate_reply.call_count == 1  # still only 1 call


@pytest.mark.asyncio
async def test_cooldown_allows_speak_after_window_expires():
    """After cooldown expires, a second event of the same type is allowed through."""
    session = make_session_mock()
    assistant = make_assistant_mock()
    handler = AmbientHandler(session=session, assistant=assistant)

    event_1 = make_event(
        event_id="rd-001", event_type="road_closure", urgency="high", confidence=0.9
    )
    event_2 = make_event(
        event_id="rd-002",
        event_type="road_closure",
        urgency="high",
        confidence=0.9,
        summary="Second independent closure on I-80 westbound",
    )

    await handler.on_event_received(event_1)
    assert session.generate_reply.call_count == 1

    # Manually wind back the last-spoken timestamp to simulate cooldown expiry
    handler._anti_chatter._last_spoken_by_type["road_closure"] = time.monotonic() - 35.0
    handler._anti_chatter._last_spoken_global = time.monotonic() - 35.0

    await handler.on_event_received(event_2)
    assert session.generate_reply.call_count == 2


# ---------------------------------------------------------------------------
# 5. Dedup suppresses identical summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_suppresses_identical_summary():
    """Identical summary within the dedup window is suppressed even if urgency is high."""
    session = make_session_mock()
    assistant = make_assistant_mock()
    handler = AmbientHandler(session=session, assistant=assistant)

    base_summary = "Bay Bridge eastbound closed after crash"

    event_1 = make_event(
        event_id="dup-001", summary=base_summary, urgency="high", confidence=0.9
    )
    event_2 = make_event(
        event_id="dup-002", summary=base_summary, urgency="high", confidence=0.9
    )

    await handler.on_event_received(event_1)
    assert session.generate_reply.call_count == 1

    # Wind back cooldown so only the dedup prevents speech
    handler._anti_chatter._last_spoken_by_type[event_1.eventType] = (
        time.monotonic() - 35.0
    )
    handler._anti_chatter._last_spoken_global = time.monotonic() - 35.0

    await handler.on_event_received(event_2)
    assert session.generate_reply.call_count == 1  # dup suppressed


# ---------------------------------------------------------------------------
# 6. User-speaking guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_speak_deferred_while_user_is_speaking():
    """Events are queued, not spoken, while the user-speaking flag is set."""
    session = make_session_mock()
    assistant = make_assistant_mock()
    user_speaking = asyncio.Event()
    user_speaking.set()  # simulate user currently speaking

    handler = AmbientHandler(
        session=session, assistant=assistant, user_speaking_flag=user_speaking
    )

    event = make_event(urgency="high", confidence=0.9)
    await handler.on_event_received(event)

    # generate_reply must NOT be called while user is speaking
    assert session.generate_reply.call_count == 0
    # But the event should be in the pending queue
    assert len(handler._anti_chatter._pending_queue) == 1


# ---------------------------------------------------------------------------
# 7. Stash mechanism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stash_appends_to_event_log():
    """STASH action appends the event to the stash list and does not call generate_reply."""
    session = make_session_mock()
    assistant = make_assistant_mock()
    handler = AmbientHandler(session=session, assistant=assistant)

    # Medium urgency, decent confidence — rule gate returns None, LLM would be called.
    # We stub the LLM to return STASH.
    event = make_event(
        event_id="stash-001",
        event_type="weather",
        summary="Fog rolling in over Twin Peaks, may reduce visibility in one hour",
        confidence=0.65,
        urgency="medium",
    )

    stash_decision = GateDecision(
        action=Action.STASH,
        severity_score=0.45,
        reason="Developing situation, not yet operationally urgent",
    )

    with patch("ambient.run_gate", new=AsyncMock(return_value=stash_decision)):
        await handler.on_event_received(event)

    assert session.generate_reply.call_count == 0
    assert len(handler._stash) == 1
    assert handler._stash[0].id == "stash-001"


def test_get_stash_summary_formats_correctly():
    """get_stash_summary returns human-readable lines for all stashed events."""
    session = make_session_mock()
    assistant = make_assistant_mock()
    handler = AmbientHandler(session=session, assistant=assistant)

    handler._stash.append(
        make_event(
            event_id="s1",
            summary="Fog advisory near Twin Peaks",
            event_type="weather",
            confidence=0.6,
            urgency="medium",
            timestamp="2026-06-06T13:10:00Z",
        )
    )

    summary = handler.get_stash_summary()
    assert "Fog advisory" in summary
    assert "weather" in summary
    assert "STASHED EVENTS" in summary


# ---------------------------------------------------------------------------
# 8. build_reply_instructions
# ---------------------------------------------------------------------------


class TestBuildReplyInstructions:
    def test_includes_event_details(self):
        event = make_event(
            summary="Bay Bridge eastbound closed",
            event_type="road_closure",
            location_guess="Bay Bridge",
            urgency="high",
            confidence=0.9,
        )
        decision = GateDecision(
            action=Action.SPEAK,
            severity_score=0.97,
            reason="High urgency on-route closure",
            suggested_utterance="Heads up — Bay Bridge eastbound is now closed. I recommend switching to Route C immediately.",
        )
        instructions = build_reply_instructions(event, decision)
        assert "Bay Bridge eastbound closed" in instructions
        assert "road_closure" in instructions
        assert "Route C" in instructions or "Bay Bridge" in instructions

    def test_falls_back_gracefully_when_no_suggested_utterance(self):
        event = make_event()
        decision = GateDecision(
            action=Action.SPEAK,
            severity_score=0.88,
            reason="Rule: high urgency",
            suggested_utterance="",
        )
        instructions = build_reply_instructions(event, decision)
        assert (
            "1" in instructions or "3" in instructions
        )  # "1-3 sentences" in instructions
        assert event.summary in instructions


# ---------------------------------------------------------------------------
# 9. MissionEvent.from_dict
# ---------------------------------------------------------------------------


class TestMissionEventFromDict:
    def test_parses_all_fields(self):
        d = {
            "id": "e1",
            "timestamp": "2026-06-06T13:00:00Z",
            "eventType": "incident",
            "summary": "Minor fender bender on US-101",
            "confidence": 0.7,
            "urgency": "medium",
            "risk_assessment": "May slow traffic by 5 min",
            "location_guess": "US-101 northbound near 3rd St",
            "source": "chp",
        }
        event = MissionEvent.from_dict(d)
        assert event.id == "e1"
        assert event.confidence == 0.7
        assert event.urgency == "medium"

    def test_defaults_for_missing_optional_fields(self):
        d = {"id": "e2", "summary": "Test", "confidence": 0.5, "urgency": "low"}
        event = MissionEvent.from_dict(d)
        assert event.risk_assessment == ""
        assert event.location_guess == ""
        assert event.source == ""


# ---------------------------------------------------------------------------
# 10. handle_data_received — JSON parsing and routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_data_received_ignores_non_json():
    session = make_session_mock()
    assistant = make_assistant_mock()
    handler = AmbientHandler(session=session, assistant=assistant)

    await handler.handle_data_received(b"this is not json")
    assert session.generate_reply.call_count == 0


@pytest.mark.asyncio
async def test_handle_data_received_parses_wrapped_payload():
    """Accepts {"type": "mission_event", "payload": <MissionEvent dict>} envelope."""
    session = make_session_mock()
    assistant = make_assistant_mock()
    handler = AmbientHandler(session=session, assistant=assistant)

    payload = {
        "type": "mission_event",
        "payload": {
            "id": "wrap-001",
            "timestamp": "2026-06-06T13:05:00Z",
            "eventType": "road_closure",
            "summary": "Howard St blocked at 4th — VIP route affected",
            "confidence": 0.9,
            "urgency": "high",
            "risk_assessment": "Direct route impact",
            "location_guess": "Howard St at 4th",
            "source": "sfpd",
        },
    }
    await handler.handle_data_received(json.dumps(payload).encode())
    assert session.generate_reply.call_count == 1


# ---------------------------------------------------------------------------
# 11. AntiChatter unit tests
# ---------------------------------------------------------------------------


class TestAntiChatter:
    def test_no_cooldown_on_fresh_event_type(self):
        ac = AntiChatter()
        event = make_event(event_type="road_closure")
        assert ac.on_cooldown(event) is False

    def test_cooldown_immediately_after_spoken(self):
        ac = AntiChatter()
        event = make_event(event_type="road_closure")
        ac.record_spoken(event)
        assert ac.on_cooldown(event) is True

    def test_global_min_gap_blocks_different_type(self):
        ac = AntiChatter()
        event_a = make_event(event_type="road_closure")
        event_b = make_event(event_type="incident")
        ac.record_spoken(event_a)
        # Different type but within global gap window
        assert ac.on_cooldown(event_b) is True

    def test_dedup_returns_false_for_new_summary(self):
        ac = AntiChatter()
        event = make_event(summary="Something new and unique")
        assert ac.is_duplicate(event) is False

    def test_dedup_returns_true_after_spoken(self):
        ac = AntiChatter()
        event = make_event(summary="Bay Bridge eastbound closed after crash")
        ac.record_spoken(event)
        dup = make_event(
            summary="Bay Bridge eastbound closed after crash", event_id="dup"
        )
        assert ac.is_duplicate(dup) is True

    def test_dedup_case_and_whitespace_insensitive(self):
        ac = AntiChatter()
        event = make_event(summary="Bay Bridge eastbound closed after crash")
        ac.record_spoken(event)
        dup = make_event(
            summary="  BAY BRIDGE EASTBOUND CLOSED AFTER CRASH  ", event_id="dup2"
        )
        assert ac.is_duplicate(dup) is True

    def test_enqueue_pop_returns_highest_severity(self):
        ac = AntiChatter()
        low_event = make_event(event_id="low", summary="Minor event")
        low_decision = GateDecision(action=Action.SPEAK, severity_score=0.5, reason="")
        high_event = make_event(event_id="high", summary="Critical event")
        high_decision = GateDecision(
            action=Action.SPEAK, severity_score=0.95, reason=""
        )

        ac.enqueue(low_event, low_decision)
        ac.enqueue(high_event, high_decision)

        result = ac.pop_highest()
        assert result is not None
        ev, dec = result
        assert ev.id == "high"
        assert dec.severity_score == 0.95
