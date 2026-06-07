"""Tests for comms ingestion, SpeakingTracker, SoldierProfile, and flush loop.

Run with:
    cd agent-py && uv run pytest tests/test_comms_and_tracker.py -v

All tests are deterministic: no network, no LLM, no LiveKit cloud credentials
required. LiveKit objects are mocked or faked using the _FakeParticipant/
_FakeRoom helpers defined below.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ambient as ambient_module
from ambient import (
    Action,
    AmbientHandler,
    AntiChatter,
    GateDecision,
    MissionEvent,
    QUIET_GAP_S,
)
from soldier import SoldierProfile
from speaking_tracker import SpeakingTracker, _FakeParticipant

# ---------------------------------------------------------------------------
# Shared test helpers
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
    session.chat_ctx = None
    return session


def make_assistant_mock() -> MagicMock:
    assistant = MagicMock()
    assistant._read_persisted_mission_state.return_value = {
        "worldState": {
            "currentObjective": "Reach Checkpoint Echo by 14:30",
            "routeStatus": {"route-a": {"status": "clear"}},
            "knownRisks": [],
            "recentChanges": [],
        },
        "injectedEvents": [],
    }
    return assistant


class _FakeRoom:
    """Minimal stand-in for livekit.rtc.Room — just enough to call register()."""

    def __init__(self) -> None:
        self._handlers: dict[str, list] = {}

    def on(self, event: str, handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, *args) -> None:
        for h in self._handlers.get(event, []):
            h(*args)


# ---------------------------------------------------------------------------
# 1. SoldierProfile.from_metadata_json — round-trips and defaults
# ---------------------------------------------------------------------------


class TestSoldierProfileFromMetadataJson:
    def test_full_payload_round_trips(self):
        """All fields present in JSON are parsed correctly."""
        raw = json.dumps(
            {
                "user_id": "u-abc",
                "callsign": "Bravo",
                "role": "medic",
                "unit": "alpha",
                "current_sector": "C3",
            }
        )
        profile = SoldierProfile.from_metadata_json(raw)
        assert profile.callsign == "Bravo"
        assert profile.role == "medic"
        assert profile.unit == "alpha"
        assert profile.current_sector == "C3"

    def test_missing_unit_derived_from_role_recon(self):
        """unit defaults to 'bravo' when role is 'recon' and unit is absent."""
        raw = json.dumps({"callsign": "Alpha", "role": "recon"})
        profile = SoldierProfile.from_metadata_json(raw)
        assert profile.unit == "bravo"

    def test_missing_unit_derived_from_role_medic(self):
        """unit defaults to 'alpha' when role is 'medic' and unit is absent."""
        raw = json.dumps({"callsign": "Bravo", "role": "medic"})
        profile = SoldierProfile.from_metadata_json(raw)
        assert profile.unit == "alpha"

    def test_none_input_returns_default(self):
        """None (console mode, no metadata) returns the hardcoded default."""
        profile = SoldierProfile.from_metadata_json(None)
        assert profile.callsign == "Alpha"
        assert profile.role == "recon"
        assert profile.unit == "bravo"
        assert profile.current_sector == "M1"

    def test_empty_string_returns_default(self):
        """Empty string is treated like None."""
        profile = SoldierProfile.from_metadata_json("")
        assert profile.callsign == "Alpha"

    def test_invalid_json_returns_default(self):
        """Non-JSON gibberish falls back to default without raising."""
        profile = SoldierProfile.from_metadata_json("not-json")
        assert profile.callsign == "Alpha"
        assert profile.role == "recon"

    def test_only_user_id_present_fills_all_defaults(self):
        """Metadata with only user_id uses field defaults for all soldier fields.

        current_sector is None (not "M1") because the key is absent in the
        JSON dict — "M1" only appears in the hardcoded console-mode default
        which is used when raw is None or empty, not for a valid JSON dict.
        """
        raw = json.dumps({"user_id": "u-legacy"})
        profile = SoldierProfile.from_metadata_json(raw)
        assert profile.callsign == "Alpha"
        assert profile.role == "recon"
        assert profile.unit == "bravo"
        assert profile.current_sector is None

    def test_current_sector_none_when_absent(self):
        """current_sector is None (not the string 'None') when the key is absent."""
        raw = json.dumps({"callsign": "Alpha", "role": "recon"})
        profile = SoldierProfile.from_metadata_json(raw)
        assert profile.current_sector is None

    def test_current_sector_preserved_as_none_when_explicitly_null(self):
        """Explicit JSON null → Python None, not the string 'null'."""
        raw = json.dumps({"callsign": "Alpha", "role": "recon", "current_sector": None})
        profile = SoldierProfile.from_metadata_json(raw)
        assert profile.current_sector is None

    def test_to_dict_round_trips(self):
        """to_dict() produces a serialisable dict matching the original fields."""
        profile = SoldierProfile(
            callsign="Alpha", role="recon", unit="bravo", current_sector="M1"
        )
        d = profile.to_dict()
        assert d["callsign"] == "Alpha"
        assert d["role"] == "recon"
        assert d["unit"] == "bravo"
        assert d["current_sector"] == "M1"


# ---------------------------------------------------------------------------
# 2. Self-comms publish builds correct envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_comms_event_builds_correct_envelope():
    """Assistant._publish_comms_event publishes exactly the right JSON shape."""
    # Import here to avoid circular issues; agent.py imports ambient.
    from agent import Assistant
    from soldier import SoldierProfile

    soldier = SoldierProfile(
        callsign="Alpha", role="recon", unit="bravo", current_sector="M1"
    )

    # Build a fake room whose local_participant.publish_data we can inspect.
    fake_local_participant = MagicMock()
    fake_local_participant.publish_data = AsyncMock()
    fake_room = MagicMock()
    fake_room.local_participant = fake_local_participant

    assistant = Assistant(room=fake_room, soldier=soldier)

    transcript = "Sector A5 looks clear, no contacts spotted."
    await assistant._publish_comms_event(transcript)

    # publish_data must have been called exactly once
    fake_local_participant.publish_data.assert_awaited_once()
    call_kwargs = fake_local_participant.publish_data.call_args

    # Extract the payload bytes
    payload_bytes: bytes = (
        call_kwargs.kwargs.get("payload") or call_kwargs.args[0]
        if call_kwargs.args
        else call_kwargs.kwargs["payload"]
    )
    envelope = json.loads(payload_bytes.decode("utf-8"))

    # Outer envelope
    assert envelope["type"] == "mission_event"
    event = envelope["event"]

    # Core fields
    assert event["eventType"] == "comms"
    assert event["summary"] == transcript
    assert event["missionId"] == "operation-pier-glass"
    assert event["confidence"] == 0.95
    assert event["urgency"] == "low"
    assert event["affectsWorldState"] is False

    # Source block
    assert event["source"]["type"] == "comms"
    assert event["source"]["name"] == "comms:Alpha"
    assert event["source"]["reliability"] == "high"

    # Raw input
    assert event["rawInput"]["modality"] == "audio"
    assert event["rawInput"]["transcript"] == transcript

    # Extracted fields
    assert event["extractedFields"]["speaker_callsign"] == "Alpha"
    assert event["extractedFields"]["speaker_role"] == "recon"

    # topic must be "mission_event"
    topic = call_kwargs.kwargs.get("topic") or (
        call_kwargs.args[2] if len(call_kwargs.args) > 2 else None
    )
    assert topic == "mission_event"

    # reliable must be True
    reliable = call_kwargs.kwargs.get("reliable", True)
    assert reliable is True


@pytest.mark.asyncio
async def test_publish_comms_event_skips_when_no_room():
    """No publish attempt is made when the room is None (console mode)."""
    from agent import Assistant
    from soldier import SoldierProfile

    soldier = SoldierProfile(
        callsign="Alpha", role="recon", unit="bravo", current_sector=None
    )
    assistant = Assistant(room=None, soldier=soldier)

    # Should complete without error and make no network call
    await assistant._publish_comms_event("some text")
    # No assertion needed — if it raises it fails; if it completes it passes


# ---------------------------------------------------------------------------
# 3. SpeakingTracker.any_speaking() reflects active_speakers_changed
# ---------------------------------------------------------------------------


class TestSpeakingTracker:
    def test_any_speaking_false_initially(self):
        tracker = SpeakingTracker()
        assert tracker.any_speaking() is False

    def test_any_speaking_true_after_speaker_injected(self):
        tracker = SpeakingTracker()
        tracker._inject_speakers(["sid-001"])
        assert tracker.any_speaking() is True

    def test_any_speaking_false_after_all_speakers_clear(self):
        tracker = SpeakingTracker()
        tracker._inject_speakers(["sid-001"])
        tracker._inject_speakers([])  # empty set = silence
        assert tracker.any_speaking() is False

    def test_multiple_speakers_all_tracked(self):
        tracker = SpeakingTracker()
        tracker._inject_speakers(["sid-001", "sid-002"])
        assert tracker.any_speaking() is True
        assert len(tracker._active_speakers) == 2

    def test_seconds_since_last_change_increases_after_event(self):
        tracker = SpeakingTracker()
        tracker._inject_speakers(["sid-001"])
        elapsed = tracker.seconds_since_last_change()
        assert 0.0 <= elapsed < 1.0  # just fired — should be near-zero

    def test_seconds_since_last_change_large_when_no_event(self):
        tracker = SpeakingTracker()
        # Never received any event
        assert tracker.seconds_since_last_change() >= 1e6

    def test_register_wires_room_event(self):
        tracker = SpeakingTracker()
        fake_room = _FakeRoom()
        tracker.register(fake_room)

        # Simulate room emitting the event with a list of participants
        participants = [_FakeParticipant("sid-abc")]
        fake_room.emit("active_speakers_changed", participants)

        assert tracker.any_speaking() is True
        assert "sid-abc" in tracker._active_speakers

    def test_register_then_silence_clears_speakers(self):
        tracker = SpeakingTracker()
        fake_room = _FakeRoom()
        tracker.register(fake_room)

        fake_room.emit("active_speakers_changed", [_FakeParticipant("sid-abc")])
        assert tracker.any_speaking() is True

        fake_room.emit("active_speakers_changed", [])
        assert tracker.any_speaking() is False

    def test_participant_without_sid_is_ignored(self):
        """Participants with no .sid attribute must not crash the handler."""
        tracker = SpeakingTracker()
        bad_participant = MagicMock(spec=[])  # no .sid attribute
        tracker._on_active_speakers_changed([bad_participant])
        assert tracker.any_speaking() is False


# ---------------------------------------------------------------------------
# 4. AmbientHandler queues SPEAK while any_speaking() is True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ambient_queues_speak_while_any_speaking():
    """SPEAK events are enqueued, not delivered, while SpeakingTracker reports speaking."""
    session = make_session_mock()
    assistant = make_assistant_mock()

    tracker = SpeakingTracker()
    tracker._inject_speakers(["sid-bravo-3"])  # someone is speaking

    handler = AmbientHandler(
        session=session,
        assistant=assistant,
        speaking_tracker=tracker,
    )
    # Don't start the flush loop — we want to test the queue-only path
    # without background delivery.

    event = make_event(urgency="high", confidence=0.9)
    await handler.on_event_received(event)

    # generate_reply must NOT have been called
    assert session.generate_reply.call_count == 0
    # The event must be buffered in the pending queue
    assert handler._anti_chatter.has_queued()


@pytest.mark.asyncio
async def test_ambient_speaks_immediately_when_nobody_speaking():
    """SPEAK events are delivered immediately when SpeakingTracker reports silence."""
    session = make_session_mock()
    assistant = make_assistant_mock()

    tracker = SpeakingTracker()
    # No injection — tracker reports silence

    handler = AmbientHandler(
        session=session,
        assistant=assistant,
        speaking_tracker=tracker,
    )

    event = make_event(urgency="high", confidence=0.9)
    await handler.on_event_received(event)

    assert session.generate_reply.call_count == 1


@pytest.mark.asyncio
async def test_ambient_falls_back_to_user_speaking_flag_when_no_tracker():
    """Legacy user_speaking_flag path still works when no SpeakingTracker is provided."""
    session = make_session_mock()
    assistant = make_assistant_mock()

    legacy_flag = asyncio.Event()
    legacy_flag.set()  # user is speaking

    handler = AmbientHandler(
        session=session,
        assistant=assistant,
        user_speaking_flag=legacy_flag,
    )

    event = make_event(urgency="high", confidence=0.9)
    await handler.on_event_received(event)

    assert session.generate_reply.call_count == 0
    assert handler._anti_chatter.has_queued()


# ---------------------------------------------------------------------------
# 5. Flush loop pops queue after QUIET_GAP_S of silence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_loop_delivers_after_quiet_gap():
    """After QUIET_GAP_S seconds of silence the flush loop pops and speaks."""
    session = make_session_mock()
    assistant = make_assistant_mock()

    tracker = SpeakingTracker()
    # Someone was speaking — simulate they stopped just over QUIET_GAP_S ago.
    tracker._inject_speakers(["sid-001"])
    tracker._inject_speakers([])  # they stopped
    # Wind the clock so seconds_since_last_change() > QUIET_GAP_S
    tracker._last_change_at = time.monotonic() - (QUIET_GAP_S + 0.1)

    handler = AmbientHandler(
        session=session,
        assistant=assistant,
        speaking_tracker=tracker,
    )

    # Manually pre-load the queue with a high-urgency event so we bypass the
    # gate (which would make a network call in the real path).
    event = make_event(urgency="high", confidence=0.9, event_id="queued-001")
    decision = GateDecision(action=Action.SPEAK, severity_score=0.97, reason="test")
    handler._anti_chatter.enqueue(event, decision)

    # Start the flush loop and give it one full tick (0.5 s sleep + margin).
    await handler.start()
    try:
        await asyncio.sleep(0.7)
    finally:
        await handler.stop()

    assert session.generate_reply.call_count == 1


@pytest.mark.asyncio
async def test_flush_loop_does_not_deliver_while_speaking():
    """Flush loop must NOT deliver while any_speaking() is True."""
    session = make_session_mock()
    assistant = make_assistant_mock()

    tracker = SpeakingTracker()
    tracker._inject_speakers(["sid-001"])  # still speaking

    handler = AmbientHandler(
        session=session,
        assistant=assistant,
        speaking_tracker=tracker,
    )

    event = make_event(urgency="high", confidence=0.9, event_id="queued-002")
    decision = GateDecision(action=Action.SPEAK, severity_score=0.97, reason="test")
    handler._anti_chatter.enqueue(event, decision)

    await handler.start()
    try:
        await asyncio.sleep(0.7)
    finally:
        await handler.stop()

    # Still speaking — flush loop must have stayed dormant
    assert session.generate_reply.call_count == 0


@pytest.mark.asyncio
async def test_flush_loop_does_not_deliver_within_quiet_gap():
    """Flush loop must wait the full QUIET_GAP_S before delivering."""
    session = make_session_mock()
    assistant = make_assistant_mock()

    tracker = SpeakingTracker()
    tracker._inject_speakers(["sid-001"])
    tracker._inject_speakers([])  # stopped NOW — not enough time yet
    # Do NOT wind the clock; seconds_since_last_change() is near-zero

    handler = AmbientHandler(
        session=session,
        assistant=assistant,
        speaking_tracker=tracker,
    )

    event = make_event(urgency="high", confidence=0.9, event_id="queued-003")
    decision = GateDecision(action=Action.SPEAK, severity_score=0.97, reason="test")
    handler._anti_chatter.enqueue(event, decision)

    await handler.start()
    try:
        # Run for one flush tick — not long enough for QUIET_GAP_S (2.5 s)
        await asyncio.sleep(0.7)
    finally:
        await handler.stop()

    assert session.generate_reply.call_count == 0


@pytest.mark.asyncio
async def test_flush_loop_stop_cancels_task():
    """stop() cancels the flush task cleanly without raising."""
    session = make_session_mock()
    assistant = make_assistant_mock()
    tracker = SpeakingTracker()

    handler = AmbientHandler(session=session, assistant=assistant, speaking_tracker=tracker)
    await handler.start()
    assert handler._flush_task is not None
    assert not handler._flush_task.done()

    await handler.stop()
    # Task should be done after stop()
    assert handler._flush_task is None or handler._flush_task.done()


# ---------------------------------------------------------------------------
# 6. Comms event received by other soldier's agent appends to _event_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comms_event_appended_to_event_log():
    """A comms MissionEvent arriving via data_received is appended to _event_log."""
    session = make_session_mock()
    assistant = make_assistant_mock()

    handler = AmbientHandler(session=session, assistant=assistant)

    # Build the exact envelope produced by Assistant._publish_comms_event
    envelope = {
        "type": "mission_event",
        "event": {
            "id": "comms-test-001",
            "missionId": "operation-pier-glass",
            "timestamp": "2026-06-06T14:00:00.000Z",
            "source": {
                "type": "comms",
                "name": "comms:Bravo",
                "reliability": "high",
            },
            "eventType": "comms",
            "summary": "Sector B7 clear, proceeding to checkpoint.",
            "entities": [],
            "confidence": 0.95,
            "urgency": "low",
            "rawInput": {"modality": "audio", "transcript": "Sector B7 clear."},
            "extractedFields": {"speaker_callsign": "Bravo", "speaker_role": "medic"},
            "affectsWorldState": False,
        },
    }

    data = json.dumps(envelope).encode("utf-8")
    # Comms events have urgency=low → rule gate drops them, but they must still
    # appear in _event_log BEFORE the gate runs.
    await handler.handle_data_received(data)

    assert len(handler._event_log) == 1
    assert handler._event_log[0].id == "comms-test-001"
    assert handler._event_log[0].eventType == "comms"


# ---------------------------------------------------------------------------
# 7. AntiChatter.has_queued()
# ---------------------------------------------------------------------------


class TestAntiChatterHasQueued:
    def test_false_when_empty(self):
        ac = AntiChatter()
        assert ac.has_queued() is False

    def test_true_after_enqueue(self):
        ac = AntiChatter()
        event = make_event()
        decision = GateDecision(action=Action.SPEAK, severity_score=0.9, reason="")
        ac.enqueue(event, decision)
        assert ac.has_queued() is True

    def test_false_after_pop(self):
        ac = AntiChatter()
        event = make_event()
        decision = GateDecision(action=Action.SPEAK, severity_score=0.9, reason="")
        ac.enqueue(event, decision)
        ac.pop_highest()
        assert ac.has_queued() is False
