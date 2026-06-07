"""opfor_intercept_mock.py — OPFOR comms intercept mock feed.

Emits 2-3 scripted SIGINT events on the demo timeline. Both scripted events
are defined in demo_script.py. This module handles only the scripted playback
plus a single generative "quiet" emit to confirm the feed is live.

Confidence range 0.5-0.7 (unverified intel) per spec. Low confidence is
critical for conflict scoring downstream — the agent should surface uncertainty.
"""

from __future__ import annotations

import asyncio
import logging

from feeds._base import (
    ScriptedFeedMixin,
    build_event,
    elapsed_s,
    post_event,
)

logger = logging.getLogger("feeds.opfor_intercept_mock")

FEED_NAME = "opfor_intercept_mock"

# Quiet poll cadence between scripted events — just check for pending scripted
# events. We don't generate noise intercepts outside the scripted moments.
POLL_INTERVAL_S = 10


class OpforInterceptMockFeed(ScriptedFeedMixin):
    def __init__(self) -> None:
        super().__init__()

    async def run(self) -> None:
        logger.info("[opfor_intercept_mock] Starting. Poll interval: %ds", POLL_INTERVAL_S)
        # Emit a startup heartbeat so the operator knows the feed is alive
        startup_event = build_event(
            event_type="status_report",
            summary="SIGINT feed online. Monitoring RF spectrum on 2nd St corridor. No intercepts at T+0.",
            confidence=0.99,
            urgency="low",
            source_name="sigint_mock",
            sector_id="A5",
            extracted_fields={"feed_status": "online", "monitoring_area": "2nd_st_corridor"},
        )
        await post_event(startup_event)

        while True:
            await self.maybe_emit_scripted(FEED_NAME)
            await asyncio.sleep(POLL_INTERVAL_S)


async def main() -> None:
    feed = OpforInterceptMockFeed()
    await feed.run()


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
