"""nws_weather.py — Real NWS weather feed for Operation South Beach.

Public API, no key required.
Endpoint: https://api.weather.gov/gridpoints/MTR/84,127/forecast/hourly

Polls every 5 minutes. Emits only when significant conditions are met:
  - Wind speed >= 20 mph
  - Precipitation probability >= 40%
  - Shortcut/description contains fog, smoke, or mist keywords

Each significant period → MissionEvent with eventType="status_report".
Falls through gracefully (logs warning, does not crash) if the NWS API
is unreachable. Scripted events from demo_script.py will fire regardless.
"""

from __future__ import annotations

import asyncio
import logging
import re

import aiohttp

from feeds._base import (
    ScriptedFeedMixin,
    build_event,
    elapsed_s,
    post_event,
)

logger = logging.getLogger("feeds.nws_weather")

FEED_NAME = "nws_weather"
NWS_URL = "https://api.weather.gov/gridpoints/MTR/84,127/forecast/hourly"
CADENCE_S = 300  # 5 minutes
NWS_TIMEOUT_S = 15

# Significant condition thresholds
WIND_THRESHOLD_MPH = 20
PRECIP_THRESHOLD_PCT = 40
FOG_KEYWORDS = re.compile(r"\b(fog|mist|smoke|haze|drizzle|freezing)\b", re.IGNORECASE)


def _mph(value: int | float | str | None, unit: str | None) -> float:
    """Convert wind speed to mph. NWS returns either:
      - a string like "14 mph" or "10 to 20 mph"  (hourly forecast endpoint)
      - a number in km/h with a separate windSpeedUnit (gridpoints endpoint)
    """
    if value is None:
        return 0.0
    if isinstance(value, str):
        # Take the LARGEST integer in the string ("10 to 20 mph" -> 20)
        nums = re.findall(r"\d+", value)
        if not nums:
            return 0.0
        return float(max(int(n) for n in nums))
    v = float(value)
    if unit and "km" in unit.lower():
        return v * 0.621371
    return v


def _is_significant(period: dict) -> bool:
    """Return True if this forecast period warrants a MissionEvent."""
    wind_mph = _mph(
        period.get("windSpeed"),
        period.get("windSpeedUnit"),
    )
    precip_pct = period.get("probabilityOfPrecipitation", {}).get("value") or 0
    short_desc = period.get("shortForecast", "")
    detailed = period.get("detailedForecast", "")

    if wind_mph >= WIND_THRESHOLD_MPH:
        return True
    if precip_pct >= PRECIP_THRESHOLD_PCT:
        return True
    if FOG_KEYWORDS.search(short_desc) or FOG_KEYWORDS.search(detailed):
        return True
    return False


def _build_nws_event(period: dict) -> dict:
    """Normalize a significant NWS forecast period into a MissionEvent."""
    short_desc = period.get("shortForecast", "")
    detailed = period.get("detailedForecast", "")
    temp = period.get("temperature", "?")
    temp_unit = period.get("temperatureUnit", "F")
    wind = period.get("windSpeed", "?")
    wind_dir = period.get("windDirection", "")
    precip_pct = period.get("probabilityOfPrecipitation", {}).get("value") or 0
    start_time = period.get("startTime", "")

    fog_detected = bool(FOG_KEYWORDS.search(short_desc) or FOG_KEYWORDS.search(detailed))

    summary = (
        f"NWS MTR weather update [{start_time[:16]}]: {short_desc}. "
        f"Wind {wind_dir} {wind}. Temp {temp}{temp_unit}. "
        f"Precip {precip_pct}%. "
        f"{'FOG ADVISORY — visibility degraded. ' if fog_detected else ''}"
        f"Affects ISR visibility and outdoor operations in AO."
    )

    # Estimate wind_mph for extractedFields
    if isinstance(wind, str):
        m = re.search(r"(\d+)", wind)
        wind_mph_val = float(m.group(1)) if m else 0.0
    else:
        wind_mph_val = _mph(wind, None)

    urgency = "medium" if (wind_mph_val >= WIND_THRESHOLD_MPH or fog_detected) else "low"
    confidence = 0.91  # NWS official — high confidence

    return build_event(
        event_type="status_report",
        summary=summary,
        confidence=confidence,
        urgency=urgency,
        source_name="nws_weather",
        sector_id="A5",  # AO center for weather events
        extracted_fields={
            "wind_mph": round(wind_mph_val, 1),
            "precip_pct": precip_pct,
            "fog": fog_detected,
            "short_forecast": short_desc,
            "forecast_start": start_time,
            "wx_condition": "fog" if fog_detected else short_desc.lower()[:20],
        },
        risk_assessment=(
            "Fog reduces visual reconnaissance range. Satellite imagery effectiveness degraded. "
            "Recommend increased check-in frequency for Bravo-3."
            if fog_detected else ""
        ),
    )


async def _fetch_nws_periods(session: aiohttp.ClientSession) -> list[dict]:
    """Fetch and return forecast periods from NWS hourly endpoint."""
    headers = {
        "User-Agent": "(operation-south-beach, aryan.aladar@gmail.com)",
        "Accept": "application/geo+json",
    }
    try:
        async with session.get(
            NWS_URL,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=NWS_TIMEOUT_S),
        ) as resp:
            if resp.status != 200:
                logger.warning("[nws_weather] NWS returned %s", resp.status)
                return []
            data = await resp.json(content_type=None)
            return data.get("properties", {}).get("periods", [])
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning("[nws_weather] Fetch failed: %s", exc)
        return []


class NWSWeatherFeed(ScriptedFeedMixin):
    def __init__(self) -> None:
        super().__init__()
        self._emitted_period_ids: set[str] = set()

    async def run(self) -> None:
        logger.info("[nws_weather] Starting. Cadence: %ds. URL: %s", CADENCE_S, NWS_URL)
        async with aiohttp.ClientSession() as session:
            while True:
                # Always check scripted events first (includes the T+5:00 fog advisory)
                await self.maybe_emit_scripted(FEED_NAME)

                # Fetch live NWS data
                periods = await _fetch_nws_periods(session)
                if periods:
                    # Take the next 3 hours of forecast periods
                    for period in periods[:3]:
                        period_id = str(period.get("number", "")) + period.get("startTime", "")
                        if period_id in self._emitted_period_ids:
                            continue
                        if _is_significant(period):
                            event = _build_nws_event(period)
                            logger.info(
                                "[nws_weather] Significant condition: %s",
                                period.get("shortForecast", ""),
                            )
                            await post_event(event)
                            self._emitted_period_ids.add(period_id)
                else:
                    logger.debug("[nws_weather] No significant periods in current fetch")

                # Poll for scripted events within cadence
                deadline = elapsed_s() + CADENCE_S
                while elapsed_s() < deadline:
                    await asyncio.sleep(15)
                    await self.maybe_emit_scripted(FEED_NAME)


async def main() -> None:
    feed = NWSWeatherFeed()
    await feed.run()


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
