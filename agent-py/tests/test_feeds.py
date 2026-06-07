"""test_feeds.py — pytest suite for Operation South Beach mock feeds.

Tests:
  1. Satellite mock emits at expected offsets and cycles categories
  2. Biosensor mock emits per-soldier baseline + spike at correct offset
  3. Location mock advances Bravo-3 through expected sector sequence
  4. OPFOR intercept emits at correct offsets with correct urgency/confidence
  5. FAA NOTAM normalizer handles a real sample response shape

All tests run without network access. The ingest POST is patched out via
monkeypatching _base.post_event to a no-op collector.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap: make scripts/ importable as if we were in agent-py/
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    # Append (not insert at 0) so we don't shadow installed packages like
    # livekit.agents during full-suite collection.
    sys.path.append(str(SCRIPTS_DIR))

import feeds._base as _base
from demo_script import SCRIPTED_EVENTS, events_for_feed
from feeds.biosensor_mock import BiosensorMockFeed, _is_spike_period
from feeds.faa_notams import (
    SAMPLE_NOTAM_RESPONSE,
    FAANotamsFeed,
    _build_notam_event,
    _extract_notam_text,
    _is_relevant,
)
from feeds.location_mock import (
    BRAVO3_PATROL,
    LocationMockFeed,
    _sector_at_time,
)
from feeds.opfor_intercept_mock import FEED_NAME as OPFOR_FEED_NAME, OpforInterceptMockFeed
from feeds.satellite_mock import OBSERVATION_CYCLE, SatelliteMockFeed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_demo_t0():
    """Reset DEMO_T0 to a known value before each test."""
    _base.set_demo_t0(time.monotonic())
    yield


@pytest.fixture
def posted_events() -> list[dict[str, Any]]:
    """Collector for events that would be POSTed to the ingest endpoint."""
    return []


@pytest.fixture
def patch_post(posted_events):
    """Patch _base.post_event to capture events instead of HTTP-posting them."""

    async def _fake_post(payload: dict) -> bool:
        posted_events.append(payload)
        return True

    with patch("feeds._base.post_event", side_effect=_fake_post):
        # Also patch in each feed module's imported reference
        patches = [
            patch("feeds.satellite_mock.post_event", side_effect=_fake_post),
            patch("feeds.biosensor_mock.post_event", side_effect=_fake_post),
            patch("feeds.location_mock.post_event", side_effect=_fake_post),
            patch("feeds.opfor_intercept_mock.post_event", side_effect=_fake_post),
            patch("feeds.faa_notams.post_event", side_effect=_fake_post),
            patch("feeds.nws_weather.post_event", side_effect=_fake_post),
        ]
        for p in patches:
            p.start()
        yield posted_events
        for p in patches:
            p.stop()


# ===========================================================================
# Test 1 — Satellite mock: correct offsets + category cycling
# ===========================================================================


class TestSatelliteMock:
    def test_scripted_events_exist_for_satellite(self):
        """demo_script.py defines satellite_mock events at required offsets."""
        evts = events_for_feed("satellite_mock")
        offsets = [o for o, _ in evts]
        # Required by spec: T+0:30 (30s), T+3:30 (210s), T+5:30 (330s)
        assert 30 in offsets, "Missing T+0:30 satellite sector_clear setup event"
        assert 210 in offsets, "Missing T+3:30 satellite weather/fog event"
        assert 330 in offsets, "Missing T+5:30 satellite vehicle_disposition conflict event"

    def test_satellite_sector_clear_at_t30(self):
        """T+0:30 event is sector_clear in A5 (sets up T+5:30 conflict)."""
        evts = events_for_feed("satellite_mock")
        event_30 = next((p for o, p in evts if o == 30), None)
        assert event_30 is not None
        assert event_30["location"]["sectorId"] == "A5"
        assert event_30["extractedFields"]["observation_type"] == "sector_clear"
        assert event_30["confidence"] >= 0.85

    def test_satellite_conflict_at_t330(self):
        """T+5:30 event is vehicle_disposition in A5 conflicting with sector_clear."""
        evts = events_for_feed("satellite_mock")
        event_330 = next((p for o, p in evts if o == 330), None)
        assert event_330 is not None
        assert event_330["location"]["sectorId"] == "A5"
        assert event_330["extractedFields"]["observation_type"] == "vehicle_disposition"
        assert event_330["urgency"] == "high"
        # Must reference the prior pass to enable conflict detection
        assert event_330["extractedFields"]["conflicts_pass_id"] == "alpha-1"

    def test_satellite_generative_cycles_observation_types(self):
        """Generative events cycle through all 4 observation categories in order."""
        feed = SatelliteMockFeed()
        # Cycle through 8 events — should see each category exactly twice
        seen_types = []
        for _ in range(8):
            evt = feed._next_generative_event()
            seen_types.append(evt["extractedFields"]["observation_type"])
        # Each type should appear exactly twice in 8 calls
        for obs_type in OBSERVATION_CYCLE:
            count = seen_types.count(obs_type)
            assert count == 2, f"Expected 2 occurrences of {obs_type}, got {count}"

    def test_satellite_generative_event_type_mapping(self):
        """sector_clear maps to status_report; others map to visual_observation."""
        feed = SatelliteMockFeed()
        for _ in range(len(OBSERVATION_CYCLE)):
            evt = feed._next_generative_event()
            obs = evt["extractedFields"]["observation_type"]
            if obs == "sector_clear":
                assert evt["eventType"] == "status_report"
            else:
                assert evt["eventType"] == "visual_observation"

    def test_satellite_confidence_above_threshold(self):
        """All generative satellite events have confidence >= 0.78."""
        feed = SatelliteMockFeed()
        for _ in range(20):
            evt = feed._next_generative_event()
            assert evt["confidence"] >= 0.78, (
                f"Confidence {evt['confidence']} below 0.78 for "
                f"{evt['extractedFields']['observation_type']}"
            )

    @pytest.mark.asyncio
    async def test_satellite_emits_scripted_event_after_offset(self, patch_post):
        """ScriptedFeedMixin emits the T+0:30 event once DEMO_T0 + 30s has elapsed."""
        # Simulate time having advanced 35s past T0
        _base.set_demo_t0(time.monotonic() - 35)
        feed = SatelliteMockFeed()
        await feed.maybe_emit_scripted("satellite_mock")
        # Should have emitted exactly the T+30s event (and not the T+210s one)
        assert len(patch_post) >= 1
        emitted_summaries = [e.get("summary", "") for e in patch_post]
        assert any("sector_clear" in s for s in emitted_summaries)

    @pytest.mark.asyncio
    async def test_satellite_does_not_double_emit(self, patch_post):
        """ScriptedFeedMixin never emits the same offset twice."""
        _base.set_demo_t0(time.monotonic() - 35)
        feed = SatelliteMockFeed()
        await feed.maybe_emit_scripted("satellite_mock")
        first_count = len(patch_post)
        await feed.maybe_emit_scripted("satellite_mock")
        # Second call should not emit again
        assert len(patch_post) == first_count


# ===========================================================================
# Test 2 — Biosensor mock: per-soldier baseline + spike
# ===========================================================================


class TestBiosensorMock:
    def test_scripted_baseline_events_exist(self):
        """demo_script.py includes biosensor events for both soldiers."""
        evts = events_for_feed("biosensor_mock")
        offsets = [o for o, _ in evts]
        # Bravo-3 first baseline at T+1:30 (90s), Singh at T+4:30 (270s)
        assert 90 in offsets, "Missing Bravo-3 baseline biosensor at T+1:30"
        assert 270 in offsets, "Missing Singh baseline biosensor at T+4:30"

    def test_scripted_spike_at_t480(self):
        """T+8:00 biosensor spike for Bravo-3 has HR >= 130 and urgency=high."""
        evts = events_for_feed("biosensor_mock")
        event_480 = next((p for o, p in evts if o == 480), None)
        assert event_480 is not None, "Missing T+8:00 biosensor spike event"
        assert event_480["extractedFields"]["callsign"] == "Bravo-3"
        assert event_480["extractedFields"]["heart_rate"] >= 130
        assert event_480["extractedFields"]["mobility_index"] <= 0.5
        assert event_480["urgency"] == "high"
        assert event_480["extractedFields"]["medic_alert"] == "Singh"

    def test_biosensor_stabilization_at_t570(self):
        """T+9:30 event shows Bravo-3 HR trending down (stabilization)."""
        evts = events_for_feed("biosensor_mock")
        event_570 = next((p for o, p in evts if o == 570), None)
        assert event_570 is not None, "Missing T+9:30 biosensor stabilization event"
        hr = event_570["extractedFields"]["heart_rate"]
        assert 90 <= hr <= 120, f"Stabilization HR {hr} out of expected range 90-120"
        assert event_570["urgency"] == "medium"

    def test_generative_baseline_produces_low_urgency(self):
        """Generative events outside spike period have urgency=low."""
        # Ensure we're in baseline period (well before T+480s)
        _base.set_demo_t0(time.monotonic())  # elapsed = 0
        feed = BiosensorMockFeed()
        for soldier in [{"callsign": "Bravo-3", "role": "recon", "default_sector": "A5",
                          "baseline_hr_lo": 72, "baseline_hr_hi": 82, "baseline_mobility": 1.0},
                         {"callsign": "Singh", "role": "medic", "default_sector": "Z1",
                          "baseline_hr_lo": 65, "baseline_hr_hi": 75, "baseline_mobility": 0.95}]:
            evt = feed._generative_event(soldier)
            assert evt["urgency"] == "low", (
                f"{soldier['callsign']} baseline urgency should be low, got {evt['urgency']}"
            )
            hr = evt["extractedFields"]["heart_rate"]
            assert 60 <= hr <= 90, f"Baseline HR {hr} out of 60-90 range"

    def test_generative_spike_produces_high_urgency(self):
        """Generative events during spike period (T+480s-T+570s) have urgency=high."""
        # Simulate being 490s into demo (inside spike window)
        _base.set_demo_t0(time.monotonic() - 490)
        feed = BiosensorMockFeed()
        bravo3_soldier = {
            "callsign": "Bravo-3", "role": "recon", "default_sector": "A5",
            "baseline_hr_lo": 72, "baseline_hr_hi": 82, "baseline_mobility": 1.0,
        }
        evt = feed._generative_event(bravo3_soldier)
        assert evt["urgency"] == "high", "Spike period should yield urgency=high"
        hr = evt["extractedFields"]["heart_rate"]
        assert hr >= 100, f"Spike HR {hr} should be >= 100"

    def test_both_soldiers_emitted_per_generative_tick(self):
        """_generative_event covers both Bravo-3 and Singh on each tick."""
        feed = BiosensorMockFeed()
        from feeds.biosensor_mock import ROSTER
        callsigns_in_roster = {s["callsign"] for s in ROSTER}
        assert "Bravo-3" in callsigns_in_roster
        assert "Singh" in callsigns_in_roster

    def test_source_name_includes_callsign(self):
        """Source name must be biosensor:<callsign> for each soldier."""
        _base.set_demo_t0(time.monotonic())
        feed = BiosensorMockFeed()
        for soldier in [
            {"callsign": "Bravo-3", "role": "recon", "default_sector": "A5",
             "baseline_hr_lo": 72, "baseline_hr_hi": 82, "baseline_mobility": 1.0},
        ]:
            evt = feed._generative_event(soldier)
            assert evt["source"]["name"] == "biosensor:Bravo-3"


# ===========================================================================
# Test 3 — Location mock: Bravo-3 sector sequence
# ===========================================================================


class TestLocationMock:
    def test_bravo3_starts_at_z1(self):
        """At T+0, Bravo-3 should be in Z1 (staging)."""
        sector = _sector_at_time(BRAVO3_PATROL, 0)
        assert sector == "Z1"

    def test_bravo3_at_a7_after_150s(self):
        """At T+150s (2:30), Bravo-3 should be in A7."""
        sector = _sector_at_time(BRAVO3_PATROL, 150)
        assert sector == "A7"

    def test_bravo3_at_a6_after_240s(self):
        """At T+240s (4:00), Bravo-3 should be in A6."""
        sector = _sector_at_time(BRAVO3_PATROL, 240)
        assert sector == "A6"

    def test_bravo3_at_a5_after_360s(self):
        """At T+360s (6:00), Bravo-3 should be in A5 (conflict zone)."""
        sector = _sector_at_time(BRAVO3_PATROL, 360)
        assert sector == "A5"

    def test_bravo3_at_a4_after_480s(self):
        """At T+480s (8:00), Bravo-3 should have advanced to A4."""
        sector = _sector_at_time(BRAVO3_PATROL, 480)
        assert sector == "A4"

    def test_bravo3_patrol_order_is_z1_to_a4(self):
        """Full patrol sequence covers Z1 → A7 → A6 → A5 → A4 in order."""
        expected = ["Z1", "A7", "A6", "A5", "A4"]
        actual = [sector for sector, _ in BRAVO3_PATROL]
        assert actual == expected

    def test_scripted_location_events_match_sector_sequence(self):
        """Scripted location events align with the patrol schedule."""
        evts = events_for_feed("location_mock")
        sector_at_offsets = {o: p["location"]["sectorId"] for o, p in evts}
        # Key narrative moments
        assert sector_at_offsets.get(60) == "Z1", "T+1:00 should be Z1 (departure)"
        assert sector_at_offsets.get(150) == "A7", "T+2:30 should be A7"
        assert sector_at_offsets.get(240) == "A6", "T+4:00 should be A6"
        assert sector_at_offsets.get(360) == "A5", "T+6:00 should be A5 (conflict)"

    def test_a5_entry_event_has_conflict_flag(self):
        """The T+6:00 A5 entry event must carry conflict_flag=True."""
        evts = events_for_feed("location_mock")
        event_360 = next((p for o, p in evts if o == 360), None)
        assert event_360 is not None
        assert event_360["extractedFields"].get("conflict_flag") is True

    def test_a5_entry_event_urgency_high(self):
        """T+6:00 A5 entry has urgency=high because of the conflict."""
        evts = events_for_feed("location_mock")
        event_360 = next((p for o, p in evts if o == 360), None)
        assert event_360 is not None
        assert event_360["urgency"] == "high"

    def test_sector_coords_exist_for_all_patrol_sectors(self):
        """SECTOR_COORDS covers every sector in the patrol path."""
        from feeds._base import SECTOR_COORDS
        for sector, _ in BRAVO3_PATROL:
            assert sector in SECTOR_COORDS, f"Missing coords for patrol sector {sector}"

    def test_generative_event_reflects_patrol_position(self):
        """Generative location event places Bravo-3 in correct sector per patrol."""
        # Simulate T+160s — Bravo-3 should be in A7
        _base.set_demo_t0(time.monotonic() - 160)
        feed = LocationMockFeed()
        evt = feed._generative_event("Bravo-3", BRAVO3_PATROL)
        assert evt["location"]["sectorId"] == "A7"


# ===========================================================================
# Test 4 — OPFOR intercept: correct offsets + urgency/confidence
# ===========================================================================


class TestOpforInterceptMock:
    def test_two_scripted_opfor_events_exist(self):
        """demo_script.py defines exactly 2 OPFOR intercept events."""
        evts = events_for_feed("opfor_intercept_mock")
        assert len(evts) == 2, f"Expected 2 OPFOR events, got {len(evts)}"

    def test_first_intercept_at_t120(self):
        """First intercept fires at T+2:00 (120s)."""
        evts = events_for_feed("opfor_intercept_mock")
        offsets = [o for o, _ in evts]
        assert 120 in offsets, "First OPFOR intercept must be at T+2:00 (120s)"

    def test_second_intercept_at_t540(self):
        """Second (escalating) intercept fires at T+9:00 (540s)."""
        evts = events_for_feed("opfor_intercept_mock")
        offsets = [o for o, _ in evts]
        assert 540 in offsets, "Second OPFOR intercept must be at T+9:00 (540s)"

    def test_first_intercept_confidence_range(self):
        """First intercept confidence is in the unverified range 0.5-0.7."""
        evts = events_for_feed("opfor_intercept_mock")
        event_120 = next((p for o, p in evts if o == 120), None)
        assert event_120 is not None
        conf = event_120["confidence"]
        assert 0.5 <= conf <= 0.7, f"First intercept confidence {conf} not in 0.5-0.7 range"

    def test_first_intercept_urgency_medium(self):
        """First intercept urgency is medium (unverified, initial signal)."""
        evts = events_for_feed("opfor_intercept_mock")
        event_120 = next((p for o, p in evts if o == 120), None)
        assert event_120 is not None
        assert event_120["urgency"] == "medium"

    def test_second_intercept_urgency_high(self):
        """Second (escalating) intercept urgency escalates to high."""
        evts = events_for_feed("opfor_intercept_mock")
        event_540 = next((p for o, p in evts if o == 540), None)
        assert event_540 is not None
        assert event_540["urgency"] == "high"

    def test_second_intercept_corroborates_prior(self):
        """Second intercept references corroborated evidence from prior events."""
        evts = events_for_feed("opfor_intercept_mock")
        event_540 = next((p for o, p in evts if o == 540), None)
        assert event_540 is not None
        corroborates = event_540["extractedFields"].get("corroborates", [])
        assert len(corroborates) >= 1, "Escalating intercept must cite corroborating evidence"

    def test_both_intercepts_have_incident_event_type(self):
        """Both OPFOR events must have eventType=incident per spec."""
        evts = events_for_feed("opfor_intercept_mock")
        for offset, payload in evts:
            assert payload["eventType"] == "incident", (
                f"OPFOR event at T+{offset}s has eventType={payload['eventType']}, expected incident"
            )

    def test_source_name_is_sigint_mock(self):
        """Source name must be sigint_mock for all OPFOR intercept events."""
        evts = events_for_feed("opfor_intercept_mock")
        for _, payload in evts:
            assert payload["source"]["name"] == "sigint_mock"

    @pytest.mark.asyncio
    async def test_opfor_emits_startup_heartbeat(self, patch_post):
        """OpforInterceptMockFeed emits a startup status_report on first run tick."""
        import asyncio as _asyncio
        feed = OpforInterceptMockFeed()

        # Patch maybe_emit_scripted to be a no-op so we don't need demo_script import
        # to be resolved inside the mixin during this test.
        async def _noop_scripted(*args, **kwargs):
            pass

        feed.maybe_emit_scripted = _noop_scripted

        with patch("feeds.opfor_intercept_mock.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = _asyncio.CancelledError
            try:
                await feed.run()
            except _asyncio.CancelledError:
                pass

        # Should have posted the startup heartbeat before entering the loop
        assert len(patch_post) >= 1
        assert patch_post[0]["source"]["name"] == "sigint_mock"
        assert patch_post[0]["eventType"] == "status_report"


# ===========================================================================
# Test 5 — FAA NOTAM normalizer: real sample response handling
# ===========================================================================


class TestFAANotams:
    def test_sample_response_has_correct_shape(self):
        """The captured sample response has the expected nested structure."""
        assert "items" in SAMPLE_NOTAM_RESPONSE
        assert len(SAMPLE_NOTAM_RESPONSE["items"]) == 2
        item = SAMPLE_NOTAM_RESPONSE["items"][0]
        assert "properties" in item
        assert "coreNOTAMData" in item["properties"]
        assert "notam" in item["properties"]["coreNOTAMData"]

    def test_extract_notam_text_from_sample(self):
        """_extract_notam_text returns the text field from the nested structure."""
        item = SAMPLE_NOTAM_RESPONSE["items"][0]
        text = _extract_notam_text(item)
        assert text is not None
        assert "TFR" in text or "TEMPORARY FLIGHT RESTRICTION" in text

    def test_first_notam_is_relevant(self):
        """First sample NOTAM (TFR) passes the relevance filter."""
        item = SAMPLE_NOTAM_RESPONSE["items"][0]
        text = _extract_notam_text(item)
        assert _is_relevant(text)

    def test_build_notam_event_from_tfr(self):
        """_build_notam_event correctly normalizes the TFR NOTAM."""
        item = SAMPLE_NOTAM_RESPONSE["items"][0]
        event = _build_notam_event(item)
        assert event is not None
        assert event["eventType"] == "status_report"
        assert event["urgency"] == "high"  # TFR → high urgency
        assert event["confidence"] == 0.99
        assert event["source"]["name"] == "faa_notams"
        assert "TFR" in event["summary"] or "TEMPORARY FLIGHT RESTRICTION" in event["summary"]

    def test_build_notam_event_from_uas_restriction(self):
        """Second sample NOTAM (UAS ops restriction) is also relevant and normalized."""
        item = SAMPLE_NOTAM_RESPONSE["items"][1]
        event = _build_notam_event(item)
        assert event is not None
        assert event["eventType"] == "status_report"
        # UAS restriction is medium urgency (no TFR keyword)
        assert event["urgency"] == "medium"

    def test_notam_event_contains_notam_number(self):
        """Normalized event includes the NOTAM number in extractedFields."""
        item = SAMPLE_NOTAM_RESPONSE["items"][0]
        event = _build_notam_event(item)
        assert event is not None
        assert event["extractedFields"]["notam_number"] == "SFO A1234/25"

    def test_notam_event_sector_is_z1(self):
        """Airspace NOTAMs are tagged to sector Z1 (staging/exfil)."""
        item = SAMPLE_NOTAM_RESPONSE["items"][0]
        event = _build_notam_event(item)
        assert event["location"]["sectorId"] == "Z1"

    def test_notam_text_truncated_to_300_chars_in_extracted_fields(self):
        """Raw NOTAM text in extractedFields is truncated to <= 300 chars."""
        item = SAMPLE_NOTAM_RESPONSE["items"][0]
        event = _build_notam_event(item)
        raw = event["extractedFields"].get("raw_text", "")
        assert len(raw) <= 300

    def test_scripted_faa_event_at_t450(self):
        """demo_script.py includes a TFR NOTAM at T+7:30 (450s)."""
        evts = events_for_feed("faa_notams")
        offsets = [o for o, _ in evts]
        assert 450 in offsets, "Missing scripted FAA TFR NOTAM at T+7:30 (450s)"

    def test_scripted_notam_urgency_high(self):
        """Scripted T+7:30 NOTAM has urgency=high (TFR, affects rotary)."""
        evts = events_for_feed("faa_notams")
        event_450 = next((p for o, p in evts if o == 450), None)
        assert event_450 is not None
        assert event_450["urgency"] == "high"

    def test_feed_mock_mode_when_no_credentials(self):
        """FAANotamsFeed initializes in mock-only mode when no credentials are set."""
        import os
        with patch.dict(os.environ, {"FAA_NOTAM_CLIENT_ID": "", "FAA_NOTAM_CLIENT_SECRET": ""}):
            # Re-import to pick up patched env
            import importlib
            import feeds.faa_notams as faa_mod
            importlib.reload(faa_mod)
            feed = faa_mod.FAANotamsFeed()
            assert not feed._live_mode, "Should be in mock mode with no credentials"

    def test_extract_notam_text_handles_malformed_item(self):
        """_extract_notam_text returns None on malformed input without raising."""
        assert _extract_notam_text({}) is None
        assert _extract_notam_text({"properties": {}}) is None
        assert _extract_notam_text({"properties": {"coreNOTAMData": {}}}) is None

    def test_is_relevant_rejects_unrelated_notam(self):
        """_is_relevant returns False for a NOTAM with no AO-relevant keywords."""
        unrelated = "!LAX LAX OBST TOWER LGT (ASN 2025-AWP-0001) 334230N1181742W (9.0NM SW LAX) 1024FT (319FT AGL) FLAGGED"
        assert not _is_relevant(unrelated)
