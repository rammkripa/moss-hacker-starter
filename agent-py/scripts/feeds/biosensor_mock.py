"""biosensor_mock.py — Per-soldier biosensor mock feed for Operation South Beach.

Emits every 30s for each soldier in the roster: [Bravo-3, Singh].
Baseline: HR 70-85, mobility_index 1.0, urgency="low".
Scripted spike: Bravo-3 HR climbs at T+8min per demo_script.py.

Generative events produce realistic jitter around baseline values. The
scripted events in demo_script.py override with specific values at the
exact demo offsets.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from feeds._base import (
    SECTOR_COORDS,
    ScriptedFeedMixin,
    build_event,
    elapsed_s,
    post_event,
)

logger = logging.getLogger("feeds.biosensor_mock")

FEED_NAME = "biosensor_mock"
CADENCE_S = 30

ROSTER: list[dict] = [
    {
        "callsign": "Bravo-3",
        "role": "recon",
        "default_sector": "A5",   # updated at runtime by location_mock via shared state
        "baseline_hr_lo": 72,
        "baseline_hr_hi": 82,
        "baseline_mobility": 1.0,
    },
    {
        "callsign": "Singh",
        "role": "medic",
        "default_sector": "Z1",
        "baseline_hr_lo": 65,
        "baseline_hr_hi": 75,
        "baseline_mobility": 0.95,
    },
]

# Bravo-3 spike profile: after T+480s, HR is elevated. The scripted event
# covers T+8:00 exactly; subsequent generative events should reflect the spike
# until T+9:30 when stabilization is scripted.
_BRAVO3_SPIKE_START_S = 480
_BRAVO3_SPIKE_END_S = 570


def _is_spike_period(callsign: str) -> bool:
    now = elapsed_s()
    return callsign == "Bravo-3" and _BRAVO3_SPIKE_START_S < now <= _BRAVO3_SPIKE_END_S


class BiosensorMockFeed(ScriptedFeedMixin):
    def __init__(self) -> None:
        super().__init__()
        # Track last-known sector per callsign (updated externally or from scripted events)
        self._soldier_sector: dict[str, str] = {
            "Bravo-3": "Z1",
            "Singh": "Z1",
        }

    def _generative_event(self, soldier: dict) -> dict:
        callsign = soldier["callsign"]
        role = soldier["role"]
        sector = self._soldier_sector.get(callsign, soldier["default_sector"])

        if _is_spike_period(callsign):
            hr = random.randint(105, 130)
            mobility = round(random.uniform(0.35, 0.55), 2)
            urgency = "high"
            summary = (
                f"{callsign} biosensor: HR {hr} bpm (elevated). "
                f"Mobility index {mobility}. Possible stress event in {sector}."
            )
        else:
            hr = random.randint(soldier["baseline_hr_lo"], soldier["baseline_hr_hi"])
            mobility = round(soldier["baseline_mobility"] * random.uniform(0.95, 1.05), 2)
            urgency = "low"
            summary = (
                f"{callsign} biosensor nominal: HR {hr} bpm, mobility index {mobility}. "
                f"Holding at {sector}."
            )

        return build_event(
            event_type="status_report",
            summary=summary,
            confidence=round(random.uniform(0.94, 0.99), 3),
            urgency=urgency,
            source_name=f"biosensor:{callsign}",
            sector_id=sector,
            extracted_fields={
                "callsign": callsign,
                "role": role,
                "heart_rate": hr,
                "mobility_index": mobility,
                "last_movement_at": f"T+{int(elapsed_s())}s",
                "spike_threshold_exceeded": _is_spike_period(callsign),
            },
        )

    def update_soldier_sector(self, callsign: str, sector_id: str) -> None:
        """Called by location_mock (via shared state) to keep sector current."""
        self._soldier_sector[callsign] = sector_id

    async def run(self) -> None:
        logger.info("[biosensor_mock] Starting. Cadence: %ds per soldier", CADENCE_S)
        await asyncio.sleep(1)
        tick = 0
        while True:
            # Check scripted events on every tick
            await self.maybe_emit_scripted(FEED_NAME)

            # Emit a generative event for each soldier (stagger by 2s to avoid burst)
            for i, soldier in enumerate(ROSTER):
                event = self._generative_event(soldier)
                logger.info(
                    "[biosensor_mock] Generative: %s HR=%s urgency=%s",
                    soldier["callsign"],
                    event["extractedFields"]["heart_rate"],
                    event["urgency"],
                )
                await post_event(event)
                if i < len(ROSTER) - 1:
                    await asyncio.sleep(2)

            tick += 1
            # Poll for scripted events mid-cadence to hit exact offsets
            deadline = elapsed_s() + CADENCE_S
            while elapsed_s() < deadline:
                await asyncio.sleep(5)
                await self.maybe_emit_scripted(FEED_NAME)


async def main() -> None:
    feed = BiosensorMockFeed()
    await feed.run()


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
