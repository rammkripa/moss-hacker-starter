"""demo_script.py — Central source of truth for the Operation South Beach demo timeline.

Every scripted event is listed here with (feed_name, offset_s, event_payload).
Mock feeds import SCRIPTED_EVENTS and filter by feed_name + offset_s. On each
cadence tick the feed emits any event whose offset_s has elapsed and has not yet
been emitted. This guarantees repeatable, deterministic demos regardless of
individual feed timing jitter.

Sector grid (AO centered on 680 2nd St, SF):
  A1: 2nd/Howard      37.7869, -122.3971
  A2: 2nd/Folsom      37.7851, -122.3964
  A3: 2nd/Harrison    37.7834, -122.3957
  A4: 2nd/Bryant      37.7816, -122.3950
  A5: 2nd/Brannan     37.7800, -122.3942
  A6: 2nd/Townsend    37.7784, -122.3934
  A7: 2nd/King        37.7768, -122.3927
  Z1: South Beach Marina  37.7751, -122.3878

Demo duration: 10 minutes (600s).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Type alias for readability
# ---------------------------------------------------------------------------
ScriptEntry = tuple[str, int, dict[str, Any]]

# ---------------------------------------------------------------------------
# SCRIPTED_EVENTS
# Each tuple: (feed_name, offset_s, event_payload_dict)
# event_payload_dict is the full MissionEvent JSON body (sans id/timestamp
# which are injected at emit time).
# ---------------------------------------------------------------------------

SCRIPTED_EVENTS: list[ScriptEntry] = [
    # -----------------------------------------------------------------------
    # T+0:30 — Satellite: A5 sector_clear (sets up conflict at T+5:30)
    # -----------------------------------------------------------------------
    (
        "satellite_mock",
        30,
        {
            "eventType": "status_report",
            "summary": "Satellite pass alpha-1: Sector A5 (2nd/Brannan) reads sector_clear. No vehicle disposition detected. Confidence 0.92.",
            "confidence": 0.92,
            "urgency": "medium",
            "source": {"type": "system", "name": "satellite"},
            "location": {
                "sectorId": "A5",
                "coordinates": {"lat": 37.7800, "lng": -122.3942},
                "description": "2nd St / Brannan St intersection",
            },
            "extractedFields": {
                "observation_type": "sector_clear",
                "pass_id": "alpha-1",
                "imagery_age_s": 0,
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+1:00 — Location: Bravo-3 departs Z1, heading toward A7
    # -----------------------------------------------------------------------
    (
        "location_mock",
        60,
        {
            "eventType": "position_update",
            "summary": "Bravo-3 departing staging Z1 (South Beach Marina). Moving north on 2nd St toward A7.",
            "confidence": 0.99,
            "urgency": "medium",
            "source": {"type": "system", "name": "biosensor:Bravo-3"},
            "location": {
                "sectorId": "Z1",
                "coordinates": {"lat": 37.7751, "lng": -122.3878},
                "description": "South Beach Marina staging area",
            },
            "extractedFields": {
                "callsign": "Bravo-3",
                "role": "recon",
                "movement_vector": "north",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+1:30 — Biosensor: Bravo-3 baseline (first reading after movement starts)
    # -----------------------------------------------------------------------
    (
        "biosensor_mock",
        90,
        {
            "eventType": "status_report",
            "summary": "Bravo-3 biosensor nominal: HR 72 bpm, mobility index 1.0. En route to A7.",
            "confidence": 0.97,
            "urgency": "low",
            "source": {"type": "system", "name": "biosensor:Bravo-3"},
            "location": {
                "sectorId": "Z1",
                "coordinates": {"lat": 37.7751, "lng": -122.3878},
                "description": "South Beach Marina",
            },
            "extractedFields": {
                "callsign": "Bravo-3",
                "heart_rate": 72,
                "mobility_index": 1.0,
                "last_movement_at": "T+90s",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+2:00 — OPFOR intercept: RF/voice activity near anchorage
    # -----------------------------------------------------------------------
    (
        "opfor_intercept_mock",
        120,
        {
            "eventType": "incident",
            "summary": "SIGINT: Voice traffic intercept references 'package' near Bay Bridge anchorage. Transmission bearing 047 degrees. Low confidence — unverified.",
            "confidence": 0.55,
            "urgency": "medium",
            "source": {"type": "system", "name": "sigint_mock"},
            "location": {
                "sectorId": "A7",
                "coordinates": {"lat": 37.7768, "lng": -122.3927},
                "description": "2nd St / King St — nearest AO grid to Bay Bridge anchorage bearing",
            },
            "extractedFields": {
                "intercept_type": "voice",
                "bearing_deg": 47,
                "keyword_hit": "package",
                "verification_status": "unverified",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+2:30 — Location: Bravo-3 arrives A7
    # -----------------------------------------------------------------------
    (
        "location_mock",
        150,
        {
            "eventType": "position_update",
            "summary": "Bravo-3 arrived A7 (2nd/King). Conducting sector assessment.",
            "confidence": 0.99,
            "urgency": "medium",
            "source": {"type": "system", "name": "biosensor:Bravo-3"},
            "location": {
                "sectorId": "A7",
                "coordinates": {"lat": 37.7768, "lng": -122.3927},
                "description": "2nd St / King St",
            },
            "extractedFields": {
                "callsign": "Bravo-3",
                "role": "recon",
                "sector_reached": "A7",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+3:30 — Satellite: Most sectors clear, FOG starting over bay
    # -----------------------------------------------------------------------
    (
        "satellite_mock",
        210,
        {
            "eventType": "visual_observation",
            "summary": "Satellite pass beta-1: Sectors A4-A7 appear clear. Weather visibility degrading — marine fog bank observed advancing from bay. Sector A5 still clear at this pass. ETA fog contact AO: 90s.",
            "confidence": 0.88,
            "urgency": "medium",
            "source": {"type": "system", "name": "satellite"},
            "location": {
                "sectorId": "A6",
                "coordinates": {"lat": 37.7784, "lng": -122.3934},
                "description": "2nd St / Townsend — AO-wide visibility observation",
            },
            "extractedFields": {
                "observation_type": "weather_visibility",
                "pass_id": "beta-1",
                "fog_ata_s": 90,
                "sectors_clear": ["A4", "A5", "A6", "A7"],
                "imagery_age_s": 0,
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+4:00 — Location: Bravo-3 arrives A6
    # -----------------------------------------------------------------------
    (
        "location_mock",
        240,
        {
            "eventType": "position_update",
            "summary": "Bravo-3 at A6 (2nd/Townsend). Continuing north toward A5.",
            "confidence": 0.99,
            "urgency": "medium",
            "source": {"type": "system", "name": "biosensor:Bravo-3"},
            "location": {
                "sectorId": "A6",
                "coordinates": {"lat": 37.7784, "lng": -122.3934},
                "description": "2nd St / Townsend St",
            },
            "extractedFields": {
                "callsign": "Bravo-3",
                "role": "recon",
                "sector_reached": "A6",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+4:30 — Biosensor: Singh baseline check-in
    # -----------------------------------------------------------------------
    (
        "biosensor_mock",
        270,
        {
            "eventType": "status_report",
            "summary": "Singh biosensor nominal: HR 68 bpm, mobility index 0.95. Holding at Z1.",
            "confidence": 0.97,
            "urgency": "low",
            "source": {"type": "system", "name": "biosensor:Singh"},
            "location": {
                "sectorId": "Z1",
                "coordinates": {"lat": 37.7751, "lng": -122.3878},
                "description": "South Beach Marina staging",
            },
            "extractedFields": {
                "callsign": "Singh",
                "heart_rate": 68,
                "mobility_index": 0.95,
                "last_movement_at": "T+0s",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+5:00 — NWS fog advisory (scripted fallback — real NWS may not fire at
    #           this exact offset, but if real feed is running it will coalesce)
    # -----------------------------------------------------------------------
    (
        "nws_weather",
        300,
        {
            "eventType": "status_report",
            "summary": "NWS MTR advisory: Marine fog advisory in effect for San Francisco Bay shore. Visibility dropping below 0.25 miles in fog patches. Wind SSE 8 kt. Affects ISR drone ceiling and visual sector assessment.",
            "confidence": 0.91,
            "urgency": "medium",
            "source": {"type": "system", "name": "nws_weather"},
            "location": {
                "sectorId": "A5",
                "coordinates": {"lat": 37.7800, "lng": -122.3942},
                "description": "South Beach / 2nd St corridor — NWS MTR gridpoint 84,127",
            },
            "extractedFields": {
                "wind_mph": 9,
                "precip_pct": 10,
                "fog": True,
                "visibility_miles": 0.25,
                "wx_condition": "fog",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+5:30 — Satellite: CONFLICT — possible vehicle disposition in A5
    #           (contradicts T+0:30 sector_clear read)
    # -----------------------------------------------------------------------
    (
        "satellite_mock",
        330,
        {
            "eventType": "visual_observation",
            "summary": "Satellite pass gamma-1: CONFLICT ALERT — Sector A5 (2nd/Brannan) now shows possible vehicle disposition. Two heat signatures, stationary, 4m spacing consistent with parked vehicles. CONFLICTS with prior sector_clear read at T+30s.",
            "confidence": 0.87,
            "urgency": "high",
            "source": {"type": "system", "name": "satellite"},
            "location": {
                "sectorId": "A5",
                "coordinates": {"lat": 37.7800, "lng": -122.3942},
                "description": "2nd St / Brannan St — conflict with prior sector_clear",
            },
            "extractedFields": {
                "observation_type": "vehicle_disposition",
                "pass_id": "gamma-1",
                "heat_signatures": 2,
                "spacing_m": 4,
                "conflicts_pass_id": "alpha-1",
                "conflicts_observation_type": "sector_clear",
                "imagery_age_s": 0,
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+6:00 — Location: Bravo-3 arrives A5 (should hear the conflict)
    # -----------------------------------------------------------------------
    (
        "location_mock",
        360,
        {
            "eventType": "position_update",
            "summary": "Bravo-3 entering A5 (2nd/Brannan). CAUTION: Conflicting intelligence on this sector — satellite detected possible vehicles at T+5:30. Recommend visual verification.",
            "confidence": 0.99,
            "urgency": "high",
            "source": {"type": "system", "name": "biosensor:Bravo-3"},
            "location": {
                "sectorId": "A5",
                "coordinates": {"lat": 37.7800, "lng": -122.3942},
                "description": "2nd St / Brannan St",
            },
            "extractedFields": {
                "callsign": "Bravo-3",
                "role": "recon",
                "sector_reached": "A5",
                "conflict_flag": True,
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+7:00 — Satellite: Terrain change observation (fog obscuring A4/A3)
    # -----------------------------------------------------------------------
    (
        "satellite_mock",
        420,
        {
            "eventType": "visual_observation",
            "summary": "Satellite pass delta-1: Sectors A3 and A4 imagery degraded due to fog overcast. Terrain change from prior pass — cannot confirm prior clear status. ISR effectiveness reduced 60 percent over northern AO.",
            "confidence": 0.79,
            "urgency": "medium",
            "source": {"type": "system", "name": "satellite"},
            "location": {
                "sectorId": "A3",
                "coordinates": {"lat": 37.7834, "lng": -122.3957},
                "description": "2nd St / Harrison — fog-degraded imagery sector",
            },
            "extractedFields": {
                "observation_type": "terrain_change",
                "pass_id": "delta-1",
                "fog_degraded_sectors": ["A3", "A4"],
                "isr_effectiveness_pct": 40,
                "imagery_age_s": 0,
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+7:30 — FAA NOTAM: TFR over SFO bayside — rotary support degraded
    # -----------------------------------------------------------------------
    (
        "faa_notams",
        450,
        {
            "eventType": "status_report",
            "summary": "FAA NOTAM: Temporary Flight Restriction (TFR) active over SFO bayside corridor until 14:30 local. Altitude floor 3000 ft AGL. Affects rotary ISR support and MEDEVAC routing. Coordinate with TOC for alternate overflight window.",
            "confidence": 0.99,
            "urgency": "high",
            "source": {"type": "system", "name": "faa_notams"},
            "location": {
                "sectorId": "Z1",
                "coordinates": {"lat": 37.7751, "lng": -122.3878},
                "description": "SFO bayside — affects approach corridor to AO",
            },
            "extractedFields": {
                "notam_type": "TFR",
                "altitude_floor_ft_agl": 3000,
                "expiry_local": "14:30",
                "impact": "rotary_isr_degraded",
                "affects_medevac": True,
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+8:00 — Biosensor: Bravo-3 HR spike — medic alert for Singh
    # -----------------------------------------------------------------------
    (
        "biosensor_mock",
        480,
        {
            "eventType": "status_report",
            "summary": "ALERT: Bravo-3 biosensor anomaly — HR 138 bpm (elevated from 72 bpm baseline). Mobility index dropped to 0.4. Possible injury or contact stress. Singh (medic) should prepare for possible forward response.",
            "confidence": 0.96,
            "urgency": "high",
            "source": {"type": "system", "name": "biosensor:Bravo-3"},
            "location": {
                "sectorId": "A5",
                "coordinates": {"lat": 37.7800, "lng": -122.3942},
                "description": "2nd St / Brannan — Bravo-3 last known position",
            },
            "extractedFields": {
                "callsign": "Bravo-3",
                "heart_rate": 138,
                "mobility_index": 0.4,
                "last_movement_at": "T+480s",
                "spike_threshold_exceeded": True,
                "medic_alert": "Singh",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+8:30 — Location: Singh begins moving toward A5 (medic response)
    # -----------------------------------------------------------------------
    (
        "location_mock",
        510,
        {
            "eventType": "position_update",
            "summary": "Singh departing Z1 toward A5 in response to Bravo-3 biosensor alert. ETA A5 approximately 4 minutes.",
            "confidence": 0.99,
            "urgency": "high",
            "source": {"type": "system", "name": "biosensor:Singh"},
            "location": {
                "sectorId": "Z1",
                "coordinates": {"lat": 37.7751, "lng": -122.3878},
                "description": "South Beach Marina — Singh departing",
            },
            "extractedFields": {
                "callsign": "Singh",
                "role": "medic",
                "movement_vector": "north",
                "responding_to": "Bravo-3",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+9:00 — OPFOR intercept #2: escalating intel
    # -----------------------------------------------------------------------
    (
        "opfor_intercept_mock",
        540,
        {
            "eventType": "incident",
            "summary": "SIGINT ESCALATION: RF signature consistent with handheld tactical radio detected in Sector A5. Frequency 154.280 MHz. Transmission duration 8s. Corroborates vehicle disposition observation and prior anchorage intercept. Confidence upgraded.",
            "confidence": 0.68,
            "urgency": "high",
            "source": {"type": "system", "name": "sigint_mock"},
            "location": {
                "sectorId": "A5",
                "coordinates": {"lat": 37.7800, "lng": -122.3942},
                "description": "2nd St / Brannan — RF emission source bearing",
            },
            "extractedFields": {
                "intercept_type": "rf_signature",
                "frequency_mhz": 154.280,
                "transmission_duration_s": 8,
                "keyword_hit": None,
                "corroborates": ["vehicle_disposition_gamma-1", "anchorage_intercept_T120"],
                "verification_status": "corroborated",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+9:30 — Biosensor: Bravo-3 HR stabilizing
    # -----------------------------------------------------------------------
    (
        "biosensor_mock",
        570,
        {
            "eventType": "status_report",
            "summary": "Bravo-3 biosensor update: HR stabilizing at 104 bpm, trending down. Mobility index 0.6. Singh ETA to position approximately 90s.",
            "confidence": 0.96,
            "urgency": "medium",
            "source": {"type": "system", "name": "biosensor:Bravo-3"},
            "location": {
                "sectorId": "A5",
                "coordinates": {"lat": 37.7800, "lng": -122.3942},
                "description": "2nd St / Brannan",
            },
            "extractedFields": {
                "callsign": "Bravo-3",
                "heart_rate": 104,
                "mobility_index": 0.6,
                "last_movement_at": "T+570s",
                "spike_threshold_exceeded": False,
                "trend": "stabilizing",
            },
        },
    ),
    # -----------------------------------------------------------------------
    # T+10:00 — Satellite: Final pass, AO summary
    # -----------------------------------------------------------------------
    (
        "satellite_mock",
        600,
        {
            "eventType": "status_report",
            "summary": "Satellite pass epsilon-1: AO final assessment. A5 vehicle disposition confirmed — 2 vehicles stationary. Singh en route. A3/A4 fog still obscuring. A6/A7 clear. NOTAM TFR active. Recommend maintain visual contact A5.",
            "confidence": 0.90,
            "urgency": "medium",
            "source": {"type": "system", "name": "satellite"},
            "location": {
                "sectorId": "A5",
                "coordinates": {"lat": 37.7800, "lng": -122.3942},
                "description": "A5 sector — AO summary pass",
            },
            "extractedFields": {
                "observation_type": "vehicle_disposition",
                "pass_id": "epsilon-1",
                "vehicle_count": 2,
                "fog_sectors": ["A3", "A4"],
                "clear_sectors": ["A6", "A7"],
                "imagery_age_s": 0,
            },
        },
    ),
]


# ---------------------------------------------------------------------------
# Helper: filter events by feed name
# ---------------------------------------------------------------------------

def events_for_feed(feed_name: str) -> list[tuple[int, dict[str, Any]]]:
    """Return [(offset_s, payload), ...] for the given feed, sorted by offset."""
    return sorted(
        [(offset_s, payload) for (fn, offset_s, payload) in SCRIPTED_EVENTS if fn == feed_name],
        key=lambda x: x[0],
    )


# ---------------------------------------------------------------------------
# Demo timeline table (for documentation / printing)
# ---------------------------------------------------------------------------

TIMELINE_TABLE = """
| Time   | Feed                  | Sector | Event Summary                                               |
|--------|-----------------------|--------|-------------------------------------------------------------|
| T+0:30 | satellite_mock        | A5     | sector_clear — sets up conflict at T+5:30                   |
| T+1:00 | location_mock         | Z1     | Bravo-3 departs staging, heading to A7                      |
| T+1:30 | biosensor_mock        | Z1     | Bravo-3 baseline: HR 72, mobility 1.0                       |
| T+2:00 | opfor_intercept_mock  | A7     | Voice traffic near Bay Bridge anchorage mentions 'package'  |
| T+2:30 | location_mock         | A7     | Bravo-3 arrives A7                                          |
| T+3:30 | satellite_mock        | A6     | Sectors clear but FOG bank advancing from bay               |
| T+4:00 | location_mock         | A6     | Bravo-3 arrives A6                                          |
| T+4:30 | biosensor_mock        | Z1     | Singh baseline: HR 68, mobility 0.95                        |
| T+5:00 | nws_weather           | A5     | Fog advisory — visibility < 0.25 mi, affects ISR            |
| T+5:30 | satellite_mock        | A5     | CONFLICT: vehicle disposition in A5 (was sector_clear)      |
| T+6:00 | location_mock         | A5     | Bravo-3 enters A5 — agent should surface the conflict       |
| T+7:00 | satellite_mock        | A3     | Terrain change — A3/A4 imagery degraded by fog              |
| T+7:30 | faa_notams            | Z1     | TFR over SFO bayside — rotary ISR degraded until 14:30      |
| T+8:00 | biosensor_mock        | A5     | ALERT: Bravo-3 HR 138, mobility 0.4 — medic alert to Singh  |
| T+8:30 | location_mock         | Z1     | Singh departs Z1 toward A5 (medic response)                 |
| T+9:00 | opfor_intercept_mock  | A5     | ESCALATION: RF signature 154.280 MHz in A5, corroborated    |
| T+9:30 | biosensor_mock        | A5     | Bravo-3 HR stabilizing at 104, Singh ETA ~90s               |
| T+10:00| satellite_mock        | A5     | Final pass: 2 vehicles confirmed, fog on A3/A4              |
"""


if __name__ == "__main__":
    print(TIMELINE_TABLE)
    print(f"\nTotal scripted events: {len(SCRIPTED_EVENTS)}")
    feeds = sorted({fn for fn, _, _ in SCRIPTED_EVENTS})
    for feed in feeds:
        evts = events_for_feed(feed)
        print(f"  {feed}: {len(evts)} events at offsets {[o for o, _ in evts]}")
