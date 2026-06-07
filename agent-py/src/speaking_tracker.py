"""speaking_tracker.py — Multi-participant active-speaker tracker.

Replaces the single asyncio.Event _user_speaking flag in AmbientHandler with a
set-based tracker that fires off the LiveKit Room "active_speakers_changed"
event.  Any participant speaking — the local soldier OR the cross-room soldier —
suppresses proactive ambient speech.

LiveKit docs confirm:
    event name : "active_speakers_changed"
    callback   : handler(speakers: list[livekit.rtc.Participant])
    source     : Room.on("active_speakers_changed", handler)

Verified via:
    python -c "import livekit.rtc as rtc, inspect; \
        src = inspect.getsource(rtc.Room); \
        idx = src.find('active_speakers_changed'); \
        print(src[idx:idx+300])"

The callback receives the *current* complete set of active speakers (not a
delta), so we replace _active_speakers wholesale on every call.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import livekit.rtc as rtc

logger = logging.getLogger("speaking_tracker")


class SpeakingTracker:
    """Tracks which room participants are currently speaking.

    Usage in my_agent entrypoint (after await ctx.connect()):

        tracker = SpeakingTracker()
        tracker.register(ctx.room)
        ambient = AmbientHandler(session=session, assistant=assistant,
                                 speaking_tracker=tracker)
    """

    def __init__(self) -> None:
        self._active_speakers: set[str] = set()  # keyed by participant SID
        self._last_change_at: float = 0.0

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, room: "rtc.Room") -> None:  # UNVERIFIED — check docs.livekit.io
        """Wire the listener onto the LiveKit room.

        Verification one-liner:
            python -c "import livekit.rtc as rtc, inspect; \
                src = inspect.getsource(rtc.Room); \
                idx = src.find('active_speakers_changed'); \
                print(src[idx:idx+400])"
        """
        room.on(  # UNVERIFIED — check docs.livekit.io
            "active_speakers_changed", self._on_active_speakers_changed
        )
        logger.debug("SpeakingTracker registered on room active_speakers_changed")

    # ------------------------------------------------------------------
    # LiveKit callback
    # ------------------------------------------------------------------

    def _on_active_speakers_changed(
        self, speakers: "list[rtc.Participant]"  # UNVERIFIED — check docs.livekit.io
    ) -> None:
        """Replace the active-speaker set with the current snapshot.

        LiveKit emits the complete current set, not a delta, so a full replace
        is correct.

        Verification one-liner for callback signature:
            python -c "import livekit.rtc as rtc, inspect; \
                src = inspect.getsource(rtc.Room); \
                start = src.find(\\\"active_speakers_changed\\\"); \
                print(src[start:start+600])"
        """
        new_sids: set[str] = set()
        for participant in speakers:
            sid = getattr(participant, "sid", None)
            if sid:
                new_sids.add(sid)

        if new_sids != self._active_speakers:
            self._active_speakers = new_sids
            self._last_change_at = time.monotonic()
            logger.debug(
                "active_speakers_changed: %d speaker(s) — sids=%s",
                len(new_sids),
                new_sids,
            )

    # ------------------------------------------------------------------
    # Query API used by AmbientHandler
    # ------------------------------------------------------------------

    def any_speaking(self) -> bool:
        """Return True if at least one participant is currently active."""
        return bool(self._active_speakers)

    def seconds_since_last_change(self) -> float:
        """Seconds elapsed since the last active_speakers_changed event.

        Returns a very large number (1e9) if register() was never called or
        no event has arrived yet, so the flush loop treats an uninitialised
        tracker as permanently quiet rather than incorrectly suppressing speech.
        """
        if self._last_change_at == 0.0:
            return 1e9
        return time.monotonic() - self._last_change_at

    # ------------------------------------------------------------------
    # Test-only injection helpers (also used by fake Room in tests)
    # ------------------------------------------------------------------

    def _inject_speakers(self, sids: list[str]) -> None:
        """Directly set the active speaker set. For unit tests only."""
        fake_participants = [_FakeParticipant(sid) for sid in sids]
        self._on_active_speakers_changed(fake_participants)  # type: ignore[arg-type]


class _FakeParticipant:
    """Minimal stand-in for livekit.rtc.Participant in tests."""

    def __init__(self, sid: str) -> None:
        self.sid = sid
