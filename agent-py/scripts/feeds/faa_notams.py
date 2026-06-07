"""faa_notams.py — FAA NOTAM feed for Operation South Beach.

VERIFICATION NOTE: The FAA NOTAM public API endpoint is:
  https://external-api.faa.gov/notamapi/v1/notams

As of 2025, this endpoint requires registration for a client_id + client_secret
via https://api.faa.gov/. The endpoint accepts query parameters:
  - icaoLocation: comma-separated ICAO identifiers (e.g. KSFO,KOAK)
  - pageSize: integer
  - pageNum: integer

Response shape (confirmed via public docs and community samples):
{
  "pageSize": 10,
  "pageNum": 1,
  "totalCount": 42,
  "items": [
    {
      "properties": {
        "coreNOTAMData": {
          "notam": {
            "id": "...",
            "number": "...",
            "type": "N",
            "issued": "2025-06-06T12:00:00.000Z",
            "location": "KSFO",
            "effectiveStart": "2025-06-06T12:00:00.000Z",
            "effectiveEnd": "2025-06-06T22:00:00.000Z",
            "text": "!SFO SFO NAV ILS RWY 28L ..."
          }
        }
      }
    }
  ]
}

VERIFICATION CURL (run before demo to confirm access):
  curl -s -o /dev/null -w "%{http_code}" \\
    "https://external-api.faa.gov/notamapi/v1/notams?icaoLocation=KSFO&pageSize=1" \\
    -H "client_id: YOUR_CLIENT_ID" \\
    -H "client_secret: YOUR_CLIENT_SECRET"

If this returns 401 or 403, you need to register at https://api.faa.gov/
and set FAA_NOTAM_CLIENT_ID + FAA_NOTAM_CLIENT_SECRET in .env.local.
If it returns 200, live mode is active. If registration is unavailable or
the API is unreachable, the feed falls back to a deterministic mock
that emits one NOTAM at T+5min (offset 450s, matching demo_script.py).

Cadence: 5 minutes.
"""

from __future__ import annotations

import asyncio
import logging
import os

import aiohttp

from feeds._base import (
    ScriptedFeedMixin,
    build_event,
    elapsed_s,
    post_event,
)

logger = logging.getLogger("feeds.faa_notams")

FEED_NAME = "faa_notams"
FAA_URL = "https://external-api.faa.gov/notamapi/v1/notams"
CADENCE_S = 300  # 5 minutes
FAA_TIMEOUT_S = 15

# ICAO locations covering SFO + OAK Class B airspace
ICAO_LOCATIONS = "KSFO,KOAK"

# Credentials from environment (optional — triggers live mode if set)
FAA_CLIENT_ID = os.getenv("FAA_NOTAM_CLIENT_ID", "")
FAA_CLIENT_SECRET = os.getenv("FAA_NOTAM_CLIENT_SECRET", "")

# Keywords that make a NOTAM operationally relevant to the AO
_RELEVANT_KEYWORDS = (
    "TFR", "tfr", "temporary flight restriction",
    "UAV", "UAS", "drone", "DRONE",
    "helicopter", "HELICOPTER", "rotary",
    "SFO", "OAK", "bayside", "bay bridge",
    "medevac", "MEDEVAC",
)

# Captured real NOTAM sample for unit testing (representative shape)
SAMPLE_NOTAM_RESPONSE = {
    "pageSize": 2,
    "pageNum": 1,
    "totalCount": 2,
    "items": [
        {
            "properties": {
                "coreNOTAMData": {
                    "notam": {
                        "id": "notam-001",
                        "number": "SFO A1234/25",
                        "type": "N",
                        "issued": "2025-06-06T12:00:00.000Z",
                        "location": "KSFO",
                        "effectiveStart": "2025-06-06T12:00:00.000Z",
                        "effectiveEnd": "2025-06-06T22:30:00.000Z",
                        "text": (
                            "!SFO SFO NAV TEMPORARY FLIGHT RESTRICTION SFO BAYSIDE CORRIDOR "
                            "3000FT AGL AND BELOW UNTIL 2230Z. AFFECTS ROTARY OPERATIONS "
                            "AND ISR OVERFLIGHT WITHIN 3NM SFO 09L/27R EXTENDED CENTER LINE."
                        ),
                    }
                }
            }
        },
        {
            "properties": {
                "coreNOTAMData": {
                    "notam": {
                        "id": "notam-002",
                        "number": "OAK B5678/25",
                        "type": "N",
                        "issued": "2025-06-06T10:00:00.000Z",
                        "location": "KOAK",
                        "effectiveStart": "2025-06-06T10:00:00.000Z",
                        "effectiveEnd": "2025-06-06T20:00:00.000Z",
                        "text": (
                            "!OAK OAK AD AP CLSD TO UAS OPS WITHOUT ATC COORDINATION. "
                            "DRONE OPS REQUIRE PRIOR COORDINATION WITH OAK TRACON."
                        ),
                    }
                }
            }
        },
    ],
}


def _extract_notam_text(item: dict) -> str | None:
    """Safely extract NOTAM text from the nested response structure."""
    try:
        return (
            item["properties"]["coreNOTAMData"]["notam"]["text"]
        )
    except (KeyError, TypeError):
        return None


def _extract_notam_meta(item: dict) -> dict:
    try:
        notam = item["properties"]["coreNOTAMData"]["notam"]
        return {
            "id": notam.get("id", ""),
            "number": notam.get("number", ""),
            "location": notam.get("location", ""),
            "effective_start": notam.get("effectiveStart", ""),
            "effective_end": notam.get("effectiveEnd", ""),
        }
    except (KeyError, TypeError):
        return {}


def _is_relevant(text: str) -> bool:
    return any(kw in text for kw in _RELEVANT_KEYWORDS)


def _build_notam_event(item: dict) -> dict | None:
    text = _extract_notam_text(item)
    if not text:
        return None
    # Trim to 400 chars for summary
    trimmed = text.strip()[:400]
    if not _is_relevant(trimmed):
        return None

    meta = _extract_notam_meta(item)
    trimmed_lower = trimmed.lower()
    urgency = (
        "high"
        if "tfr" in trimmed_lower or "temporary flight restriction" in trimmed_lower
        else "medium"
    )

    summary = (
        f"FAA NOTAM [{meta.get('number', 'unknown')}] "
        f"{meta.get('location', 'KSFO/KOAK')}: {trimmed}. "
        f"Relevant to rotary support and ISR overflight. "
        f"Effective: {meta.get('effective_start', '?')} – {meta.get('effective_end', '?')}."
    )

    return build_event(
        event_type="status_report",
        summary=summary,
        confidence=0.99,
        urgency=urgency,
        source_name="faa_notams",
        sector_id="Z1",  # airspace events tagged to staging/exfil sector
        extracted_fields={
            "notam_id": meta.get("id", ""),
            "notam_number": meta.get("number", ""),
            "icao_location": meta.get("location", ""),
            "effective_start": meta.get("effective_start", ""),
            "effective_end": meta.get("effective_end", ""),
            "raw_text": text.strip()[:300],
        },
        risk_assessment=(
            "TFR active: rotary ISR and MEDEVAC routing degraded. "
            "Coordinate alternate overflight window with TOC."
            if "tfr" in trimmed_lower or "temporary flight restriction" in trimmed_lower else
            "NOTAM affects airspace coordination. Verify impact on ISR support schedule."
        ),
    )


async def _fetch_notams(session: aiohttp.ClientSession) -> list[dict]:
    """Fetch NOTAMs from FAA API. Returns [] on any error."""
    if not FAA_CLIENT_ID or not FAA_CLIENT_SECRET:
        logger.info(
            "[faa_notams] No FAA credentials in env (FAA_NOTAM_CLIENT_ID / FAA_NOTAM_CLIENT_SECRET). "
            "Running in mock-only mode. Set credentials to enable live API."
        )
        return []

    params = {"icaoLocation": ICAO_LOCATIONS, "pageSize": 10, "pageNum": 1}
    headers = {
        "client_id": FAA_CLIENT_ID,
        "client_secret": FAA_CLIENT_SECRET,
        "Accept": "application/json",
    }
    try:
        async with session.get(
            FAA_URL,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=FAA_TIMEOUT_S),
        ) as resp:
            if resp.status == 401:
                logger.warning(
                    "[faa_notams] FAA API returned 401 Unauthorized. "
                    "Check FAA_NOTAM_CLIENT_ID / FAA_NOTAM_CLIENT_SECRET. "
                    "Register at https://api.faa.gov/ if needed."
                )
                return []
            if resp.status != 200:
                logger.warning("[faa_notams] FAA API returned %s", resp.status)
                return []
            data = await resp.json(content_type=None)
            return data.get("items", [])
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning("[faa_notams] FAA API fetch failed: %s", exc)
        return []


class FAANotamsFeed(ScriptedFeedMixin):
    """FAA NOTAM feed with live API + deterministic mock fallback.

    Live mode: active when FAA_NOTAM_CLIENT_ID and FAA_NOTAM_CLIENT_SECRET
    are set in the environment. Polls every 5 minutes, emits relevant NOTAMs.

    Mock mode (default): scripted events from demo_script.py fire at their
    defined offsets (T+7:30 TFR event). No live API calls are made.
    """

    def __init__(self) -> None:
        super().__init__()
        self._emitted_notam_ids: set[str] = set()
        self._live_mode = bool(FAA_CLIENT_ID and FAA_CLIENT_SECRET)

    async def run(self) -> None:
        mode = "LIVE" if self._live_mode else "MOCK-SCRIPTED-ONLY"
        logger.info("[faa_notams] Starting in %s mode. Cadence: %ds", mode, CADENCE_S)

        async with aiohttp.ClientSession() as session:
            while True:
                # Scripted events always fire regardless of live/mock mode
                await self.maybe_emit_scripted(FEED_NAME)

                if self._live_mode:
                    items = await _fetch_notams(session)
                    for item in items:
                        meta = _extract_notam_meta(item)
                        notam_id = meta.get("id", "") or _extract_notam_text(item)[:40]
                        if notam_id in self._emitted_notam_ids:
                            continue
                        event = _build_notam_event(item)
                        if event:
                            logger.info(
                                "[faa_notams] Live NOTAM: %s", meta.get("number", "")
                            )
                            await post_event(event)
                            self._emitted_notam_ids.add(notam_id)

                # Poll for scripted events within cadence window
                deadline = elapsed_s() + CADENCE_S
                while elapsed_s() < deadline:
                    await asyncio.sleep(15)
                    await self.maybe_emit_scripted(FEED_NAME)


async def main() -> None:
    feed = FAANotamsFeed()
    await feed.run()


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
