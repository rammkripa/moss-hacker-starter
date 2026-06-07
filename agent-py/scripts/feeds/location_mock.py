"""location_mock.py — Per-soldier location mock feed for Operation South Beach.

Emits every 15s for each soldier.

Bravo-3 scripted patrol path: Z1 → A7 → A6 → A5 → A4
  Each sector transition takes ~90s (one step per 90s of demo time).

Singh stays at Z1 with tiny coordinate drift until T+8:30 when he begins
moving toward A5 (scripted response to biosensor spike).

All generative position events use the current sector from the patrol
path. Scripted position events from demo_script.py override at exact
demo offsets (these carry the narrative-critical conflict flag at T+6:00).
"""

from __future__ import annotations

import asyncio
import logging
import random

from feeds._base import (
    SECTOR_COORDS,
    ScriptedFeedMixin,
    build_event,
    elapsed_s,
    post_event,
)

logger = logging.getLogger("feeds.location_mock")

FEED_NAME = "location_mock"
CADENCE_S = 15

# Bravo-3 patrol waypoints with approximate wall-clock offsets into the demo.
# Each (sector_id, arrival_offset_s) entry means Bravo-3 should be IN that
# sector once the clock passes arrival_offset_s.
BRAVO3_PATROL: list[tuple[str, int]] = [
    ("Z1", 0),    # T+0:00 — starting position
    ("A7", 150),  # T+2:30 — arrives A7
    ("A6", 240),  # T+4:00 — arrives A6
    ("A5", 360),  # T+6:00 — arrives A5 (conflict zone)
    ("A4", 480),  # T+8:00 — advances to A4 (post-spike)
]

# Singh patrol: stays at Z1 until T+8:30 (510s), then moves toward A5
SINGH_PATROL: list[tuple[str, int]] = [
    ("Z1", 0),    # T+0:00 — staging
    ("A7", 510),  # T+8:30 — begins moving (scripted medic response)
    ("A6", 570),  # T+9:30 — reaches A6
    ("A5", 630),  # T+10:30 — reaches A5 (beyond demo end, but prep'd)
]


def _sector_at_time(patrol: list[tuple[str, int]], now_s: float) -> str:
    """Return the current sector for a soldier given their patrol schedule."""
    current = patrol[0][0]
    for sector, arrival_s in patrol:
        if now_s >= arrival_s:
            current = sector
        else:
            break
    return current


def _jitter_coords(coords: dict[str, float], max_delta: float = 0.00005) -> dict[str, float]:
    """Add tiny random drift to coordinates for realism."""
    return {
        "lat": round(coords["lat"] + random.uniform(-max_delta, max_delta), 6),
        "lng": round(coords["lng"] + random.uniform(-max_delta, max_delta), 6),
    }


class LocationMockFeed(ScriptedFeedMixin):
    def __init__(self) -> None:
        super().__init__()
        self._last_bravo3_sector: str = "Z1"
        self._last_singh_sector: str = "Z1"

    def _generative_event(self, callsign: str, patrol: list[tuple[str, int]]) -> dict:
        now = elapsed_s()
        sector = _sector_at_time(patrol, now)

        base_coords = SECTOR_COORDS.get(sector, {"lat": 37.7800, "lng": -122.3942})
        coords = _jitter_coords(base_coords)

        # Track sector changes for summary messaging
        if callsign == "Bravo-3":
            prev = self._last_bravo3_sector
            self._last_bravo3_sector = sector
        else:
            prev = self._last_singh_sector
            self._last_singh_sector = sector

        if prev != sector:
            summary = f"{callsign} entered {sector}. Conducting sector assessment."
        else:
            summary = f"{callsign} holding at {sector}. Position nominal."

        return build_event(
            event_type="position_update",
            summary=summary,
            confidence=0.99,
            urgency="low",
            source_name=f"gps:{callsign}",
            sector_id=sector,
            extracted_fields={
                "callsign": callsign,
                "coordinates_precise": coords,
                "sector_entered": sector != prev,
            },
        )

    async def run(self) -> None:
        logger.info("[location_mock] Starting. Cadence: %ds", CADENCE_S)
        await asyncio.sleep(1)

        soldiers = [
            ("Bravo-3", BRAVO3_PATROL),
            ("Singh", SINGH_PATROL),
        ]

        while True:
            # Scripted events first (carry the narrative-critical flags)
            await self.maybe_emit_scripted(FEED_NAME)

            # Generative position for each soldier
            for callsign, patrol in soldiers:
                event = self._generative_event(callsign, patrol)
                logger.debug(
                    "[location_mock] Generative: %s at sector=%s",
                    callsign,
                    event["location"]["sectorId"],
                )
                await post_event(event)
                await asyncio.sleep(1)

            # Poll for scripted events within the cadence window
            deadline = elapsed_s() + CADENCE_S
            while elapsed_s() < deadline:
                await asyncio.sleep(3)
                await self.maybe_emit_scripted(FEED_NAME)

    def get_bravo3_sector(self) -> str:
        return self._last_bravo3_sector

    def get_singh_sector(self) -> str:
        return self._last_singh_sector


async def main() -> None:
    feed = LocationMockFeed()
    await feed.run()


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
