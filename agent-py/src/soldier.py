"""soldier.py — SoldierProfile dataclass and metadata parser.

The entrypoint (my_agent in agent.py) parses ctx.job.metadata into a
SoldierProfile and threads it through to the Assistant and AmbientHandler so
every layer knows who it is serving.

Wire format (JSON string packed into LiveKit AccessToken metadata):
    {
        "user_id":        "<uuid>",
        "callsign":       "Alpha",
        "role":           "recon",
        "unit":           "bravo",
        "current_sector": "M1"        # optional, may be null
    }

Console-mode default (no metadata): Alpha / recon / bravo / A5.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger("soldier")

# ---------------------------------------------------------------------------
# Unit defaults keyed by role
# ---------------------------------------------------------------------------

_UNIT_BY_ROLE: dict[str, str] = {
    "recon": "bravo",
    "medic": "alpha",
}

# Console-mode fallback identity used when ctx.job.metadata is absent.
_DEFAULT_PROFILE = {
    "callsign": "Alpha",
    "role": "recon",
    "unit": "bravo",
    "current_sector": "M1",
}


@dataclass
class SoldierProfile:
    """Immutable per-soldier identity parsed from LiveKit dispatch metadata."""

    callsign: str
    role: str  # "recon" | "medic" (extensible)
    unit: str  # "bravo" | "alpha" (extensible)
    current_sector: str | None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_metadata_json(cls, raw: str | None) -> "SoldierProfile":
        """Parse a SoldierProfile from the JSON string in ctx.job.metadata.

        Falls back to the console-mode default when *raw* is None, empty, or
        not valid JSON. Any missing field also falls back to its default so
        partial metadata (e.g. only user_id present) is safe.
        """
        if not raw:
            logger.debug(
                "No metadata; using default SoldierProfile (console mode)"
            )
            return cls(**_DEFAULT_PROFILE)

        try:
            meta = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "ctx.job.metadata is not valid JSON (%r); using default SoldierProfile",
                raw[:80],
            )
            return cls(**_DEFAULT_PROFILE)

        if not isinstance(meta, dict):
            logger.warning(
                "ctx.job.metadata decoded to %s, not dict; using default",
                type(meta).__name__,
            )
            return cls(**_DEFAULT_PROFILE)

        callsign: str = str(meta.get("callsign", _DEFAULT_PROFILE["callsign"]))
        role: str = str(meta.get("role", _DEFAULT_PROFILE["role"]))

        # unit: respect explicit value, then derive from role, then fall back
        unit: str = str(
            meta.get("unit") or _UNIT_BY_ROLE.get(role, _DEFAULT_PROFILE["unit"])
        )

        raw_sector = meta.get("current_sector")
        current_sector: str | None = (
            str(raw_sector) if raw_sector is not None else None
        )

        return cls(
            callsign=callsign,
            role=role,
            unit=unit,
            current_sector=current_sector,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise to a plain dict (useful for logging and metadata packing)."""
        return {
            "callsign": self.callsign,
            "role": self.role,
            "unit": self.unit,
            "current_sector": self.current_sector,
        }

    def __str__(self) -> str:
        sector = self.current_sector or "unknown"
        return f"{self.callsign} ({self.role}/{self.unit}) sector={sector}"
