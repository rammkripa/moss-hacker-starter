"""worker.py — Operation South Beach feed worker.

Launches all six feeds concurrently via asyncio.gather. Sets DEMO_T0 once
at startup so all feeds share the same timeline reference.

Usage:
    uv run python scripts/worker.py

Environment variables:
    MISSION_INGEST_URL     — default http://localhost:3000/api/mission/ingest
    MISSION_INGEST_SECRET  — default dev-secret
    FAA_NOTAM_CLIENT_ID    — optional, enables live FAA NOTAM feed
    FAA_NOTAM_CLIENT_SECRET — optional, enables live FAA NOTAM feed
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

# Make scripts/ importable as a package root so `from feeds._base import ...` works
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import feeds._base as _base
from feeds.biosensor_mock import BiosensorMockFeed
from feeds.faa_notams import FAANotamsFeed
from feeds.location_mock import LocationMockFeed
from feeds.nws_weather import NWSWeatherFeed
from feeds.opfor_intercept_mock import OpforInterceptMockFeed
from feeds.satellite_mock import SatelliteMockFeed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("worker")


async def _feed_task(name: str, coro) -> None:
    """Wrap a feed coroutine with error logging and auto-restart."""
    while True:
        try:
            logger.info("Starting feed: %s", name)
            await coro()
        except asyncio.CancelledError:
            logger.info("Feed %s cancelled", name)
            raise
        except Exception as exc:
            logger.exception("Feed %s crashed: %s — restarting in 5s", name, exc)
            await asyncio.sleep(5)


async def main() -> None:
    # Set DEMO_T0 once — all feeds read this via _base.elapsed_s()
    t0 = time.monotonic()
    _base.set_demo_t0(t0)
    logger.info(
        "Operation South Beach worker starting. DEMO_T0 set. "
        "Ingest URL: %s",
        _base.MISSION_INGEST_URL,
    )

    # Instantiate feeds
    satellite = SatelliteMockFeed()
    biosensor = BiosensorMockFeed()
    location = LocationMockFeed()
    opfor = OpforInterceptMockFeed()
    nws = NWSWeatherFeed()
    faa = FAANotamsFeed()

    # Run all six feeds concurrently. Each feed is wrapped in _feed_task which
    # provides crash-restart. The feeds are independent — failure in one does
    # not affect others.
    tasks = [
        asyncio.create_task(_feed_task("satellite_mock", satellite.run), name="satellite_mock"),
        asyncio.create_task(_feed_task("biosensor_mock", biosensor.run), name="biosensor_mock"),
        asyncio.create_task(_feed_task("location_mock", location.run), name="location_mock"),
        asyncio.create_task(_feed_task("opfor_intercept_mock", opfor.run), name="opfor_intercept_mock"),
        asyncio.create_task(_feed_task("nws_weather", nws.run), name="nws_weather"),
        asyncio.create_task(_feed_task("faa_notams", faa.run), name="faa_notams"),
    ]

    logger.info("All 6 feeds launched. Demo timeline active.")

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Shutting down worker (KeyboardInterrupt)")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        # Close the shared aiohttp session if it was created
        if _base._SESSION and not _base._SESSION.closed:
            await _base._SESSION.close()
        logger.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
