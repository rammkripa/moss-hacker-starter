"""satellite_mock.py — Satellite imagery mock feed for Operation South Beach.

Emits one "satellite pass" event every 60-90s during the demo. The cycle
rotates through four observation categories:
  1. sector_clear       → eventType=status_report
  2. vehicle_disposition → eventType=visual_observation
  3. terrain_change      → eventType=visual_observation
  4. weather_visibility  → eventType=visual_observation

Scripted events (from demo_script.py) take priority over the generative
cycle. The generative cycle fills gaps between scripted events so the demo
feels live even during quiet periods.
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

logger = logging.getLogger("feeds.satellite_mock")

FEED_NAME = "satellite_mock"
CADENCE_MIN_S = 60
CADENCE_MAX_S = 90

# Observation categories cycle in order. Index advances each non-scripted emit.
OBSERVATION_CYCLE = [
    "sector_clear",
    "vehicle_disposition",
    "terrain_change",
    "weather_visibility",
]

# Sectors visited by the generative cycle (in AO order)
SECTOR_CYCLE = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "Z1"]

# Canned summaries for generative (non-scripted) events per observation type
_TEMPLATES: dict[str, list[str]] = {
    "sector_clear": [
        "Satellite pass: {sector} reads sector_clear. No personnel or vehicle signatures detected.",
        "Satellite overpass: {sector} clear. Terrain nominal, no anomalies.",
    ],
    "vehicle_disposition": [
        "Satellite pass: {sector} — 1 vehicle signature detected, stationary. No threat indicators.",
        "Satellite overpass: {sector} vehicle disposition — parked civilian profile at grid edge.",
    ],
    "terrain_change": [
        "Satellite pass: {sector} — minor terrain change from prior image. Possible construction debris.",
        "Satellite overpass: {sector} terrain change detected. Rubble or equipment pile, ~3m span.",
    ],
    "weather_visibility": [
        "Satellite pass: {sector} — weather visibility good. No precipitation. Horizon clear.",
        "Satellite overpass: {sector} visibility report — partial cloud cover, imagery quality 80%.",
    ],
}

# Urgency per observation type (generative, non-scripted)
_URGENCY: dict[str, str] = {
    "sector_clear": "low",
    "vehicle_disposition": "medium",
    "terrain_change": "low",
    "weather_visibility": "low",
}

# Confidence range per observation type
_CONFIDENCE_RANGE: dict[str, tuple[float, float]] = {
    "sector_clear": (0.85, 0.95),
    "vehicle_disposition": (0.80, 0.92),
    "terrain_change": (0.78, 0.90),
    "weather_visibility": (0.85, 0.96),
}


class SatelliteMockFeed(ScriptedFeedMixin):
    def __init__(self) -> None:
        super().__init__()
        self._obs_idx = 0
        self._sector_idx = 0
        self._pass_counter = 0

    def _next_generative_event(self) -> dict:
        obs_type = OBSERVATION_CYCLE[self._obs_idx % len(OBSERVATION_CYCLE)]
        sector = SECTOR_CYCLE[self._sector_idx % len(SECTOR_CYCLE)]

        self._obs_idx = (self._obs_idx + 1) % len(OBSERVATION_CYCLE)
        self._sector_idx = (self._sector_idx + 1) % len(SECTOR_CYCLE)
        self._pass_counter += 1

        templates = _TEMPLATES[obs_type]
        summary = random.choice(templates).format(sector=sector)

        conf_lo, conf_hi = _CONFIDENCE_RANGE[obs_type]
        confidence = round(random.uniform(conf_lo, conf_hi), 3)

        event_type = "status_report" if obs_type == "sector_clear" else "visual_observation"
        urgency = _URGENCY[obs_type]

        return build_event(
            event_type=event_type,
            summary=summary,
            confidence=confidence,
            urgency=urgency,
            source_name="satellite",
            sector_id=sector,
            extracted_fields={
                "observation_type": obs_type,
                "pass_id": f"gen-{self._pass_counter}",
                "imagery_age_s": 0,
            },
        )

    async def run(self) -> None:
        logger.info("[satellite_mock] Starting. Cadence: %d-%ds", CADENCE_MIN_S, CADENCE_MAX_S)
        # First tick fast — check scripted immediately
        await asyncio.sleep(2)
        while True:
            # Always check scripted events first
            await self.maybe_emit_scripted(FEED_NAME)

            # Emit a generative event to keep the feed feeling live
            event = self._next_generative_event()
            logger.info(
                "[satellite_mock] Generative emit: %s sector=%s",
                event["extractedFields"]["observation_type"],
                event["location"]["sectorId"],
            )
            await post_event(event)

            # Wait randomized cadence before next generative emit
            cadence = random.uniform(CADENCE_MIN_S, CADENCE_MAX_S)
            # During the cadence window, keep polling for scripted events every 5s
            deadline = elapsed_s() + cadence
            while elapsed_s() < deadline:
                await asyncio.sleep(5)
                await self.maybe_emit_scripted(FEED_NAME)


async def main() -> None:
    feed = SatelliteMockFeed()
    await feed.run()


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
