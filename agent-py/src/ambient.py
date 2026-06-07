"""ambient.py — Mission Bay proactive-speech severity gate.

Architecture: Hybrid (Option C).

Full pipeline (per event):
  1. Relevance filter  — pure rule-based, per-soldier, no LLM cost
     DIRECT    -> normal severity gate
     ADJACENT  -> stricter SPEAK threshold (urgency==high AND confidence>=0.7)
     UNRELATED -> forced DROP

  2. Conflict detection — checks accepted event against rolling 10-event log;
     emits synthetic "conflict" MissionEvent that re-enters the pipeline.

  3. Fast rule gate — O(1), zero network cost:
       urgency==high AND confidence>=0.5 => SPEAK immediately  (DIRECT)
       urgency==high AND confidence>=0.7 => SPEAK immediately  (ADJACENT, stricter)
       urgency==low  OR  confidence<0.3  => DROP immediately
       everything else                   => LLM classifier call

  4. LLM classifier (borderline only) — standard LiveKit Inference model,
     ~300-token budget.
     Estimated <5% of events reach this stage under normal feed conditions.

  5. Anti-chatter controls:
       - Per-eventType cooldown (30 s default, 90 s non-critical).
       - Global minimum gap: 8 s between any two utterances.
       - Dedup SHA-256 hash on summary text: identical within 5 min => DROP.
       - Priority queue: buffer while speaking, drain highest-severity first.

  6. Quiet-during-comms gate (SpeakingTracker integration):
       - any_speaking() == True  -> enqueue always.
       - seconds_since_last_change() < QUIET_GAP_S -> enqueue.
       - Otherwise -> speak now.
     All spoken utterances are prefixed "{callsign}, " via generate_reply instructions.

eventType union — canonical values including new additions:
  visual_observation | traffic | crowd | protest | incident | status_report
  weather | notam | admin | mission_update | route_change | vip_movement
  road_closure | comms      (NEW — radio transmission from a soldier)
  conflict                  (NEW — synthetic contradiction notice)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from livekit.agents import inference

from conflict import ConflictDetector  # noqa: E402 — project-local module
from relevance import RelevanceVerdict, SoldierProfile, is_relevant_to  # noqa: E402

if TYPE_CHECKING:
    from livekit.agents import AgentSession
    from speaking_tracker import SpeakingTracker

# Seconds of silence (no active speaker) that must elapse before the flush
# loop will pop and deliver a queued SPEAK event.  Configurable via module-level
# constant so tests can override it without monkey-patching.
QUIET_GAP_S: float = 2.5

# Confidence threshold applied when the relevance verdict is ADJACENT.
# Stricter than the DIRECT threshold (0.5) to avoid over-alerting on
# events that are near but not directly in the soldier's sector.
ADJACENT_CONFIDENCE_THRESHOLD: float = 0.7

logger = logging.getLogger("ambient")

DEFAULT_CLASSIFIER_MODEL = "openai/gpt-4.1-mini"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class Action(str, Enum):
    SPEAK = "speak"
    STASH = "stash"
    DROP = "drop"


@dataclass
class MissionEvent:
    id: str
    timestamp: str
    eventType: str  # noqa: N815 — must match the wire format field name
    summary: str
    confidence: float  # [0, 1]
    urgency: str  # "low" | "medium" | "high"
    risk_assessment: str = ""
    location_guess: str = ""
    source: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> MissionEvent:
        return cls(
            id=str(d.get("id", "")),
            timestamp=str(d.get("timestamp", "")),
            eventType=str(d.get("eventType", "")),
            summary=str(d.get("summary", "")),
            confidence=float(d.get("confidence", 0.0)),
            urgency=str(d.get("urgency", "low")),
            risk_assessment=str(d.get("risk_assessment", "")),
            location_guess=str(d.get("location_guess", "")),
            source=str(d.get("source", "")),
        )


@dataclass
class GateDecision:
    action: Action
    severity_score: float  # 0.0-1.0
    reason: str
    suggested_utterance: str = ""  # only populated for SPEAK


# ---------------------------------------------------------------------------
# Cooldown and dedup tracker
# ---------------------------------------------------------------------------

# Per-eventType cooldown durations in seconds.
# "comms" and "conflict" are new types added alongside the original set.
COOLDOWN_BY_TYPE: dict[str, float] = {
    "road_closure": 30.0,
    "incident": 30.0,
    "weather": 90.0,
    "crowd": 60.0,
    "protest": 45.0,
    "vip_movement": 20.0,
    "route_change": 30.0,
    "comms": 20.0,      # radio comms — short cooldown, info is time-critical
    "conflict": 60.0,   # synthetic conflict notice — moderate to avoid spam
    "default": 30.0,
}

GLOBAL_MIN_GAP_S: float = 8.0
DEDUP_WINDOW_S: float = 300.0  # 5 minutes


@dataclass
class AntiChatter:
    """Tracks cooldowns, dedup hashes, and the speak queue."""

    _last_spoken_by_type: dict[str, float] = field(default_factory=dict)
    _last_spoken_global: float = field(default_factory=lambda: 0.0)
    _recent_hashes: dict[str, float] = field(default_factory=dict)  # hash -> timestamp
    _pending_queue: list[tuple[float, MissionEvent, GateDecision]] = field(
        default_factory=list
    )  # (severity_score, event, decision) — highest severity speaks next

    def _summary_hash(self, summary: str) -> str:
        return hashlib.sha256(summary.strip().lower().encode()).hexdigest()[:16]

    def _type_cooldown(self, event_type: str) -> float:
        return COOLDOWN_BY_TYPE.get(event_type, COOLDOWN_BY_TYPE["default"])

    def is_duplicate(self, event: MissionEvent) -> bool:
        """Return True if an identical summary was recently spoken."""
        h = self._summary_hash(event.summary)
        cutoff = time.monotonic() - DEDUP_WINDOW_S
        # Prune old hashes
        self._recent_hashes = {
            k: v for k, v in self._recent_hashes.items() if v > cutoff
        }
        return h in self._recent_hashes

    def on_cooldown(self, event: MissionEvent) -> bool:
        """Return True if this eventType is still within its cooldown window."""
        now = time.monotonic()
        last = self._last_spoken_by_type.get(event.eventType, 0.0)
        cooldown = self._type_cooldown(event.eventType)
        if (now - last) < cooldown:
            return True
        return now - self._last_spoken_global < GLOBAL_MIN_GAP_S

    def record_spoken(self, event: MissionEvent) -> None:
        now = time.monotonic()
        self._last_spoken_by_type[event.eventType] = now
        self._last_spoken_global = now
        h = self._summary_hash(event.summary)
        self._recent_hashes[h] = now

    def enqueue(self, event: MissionEvent, decision: GateDecision) -> None:
        """Buffer a SPEAK event that arrived while another was speaking."""
        self._pending_queue.append((decision.severity_score, event, decision))
        self._pending_queue.sort(key=lambda x: x[0], reverse=True)

    def has_queued(self) -> bool:
        """Return True if there is at least one event in the pending queue."""
        return bool(self._pending_queue)

    def pop_highest(self) -> tuple[MissionEvent, GateDecision] | None:
        if not self._pending_queue:
            return None
        _, event, decision = self._pending_queue.pop(0)
        return event, decision

    def clear_queue(self) -> None:
        self._pending_queue.clear()


# ---------------------------------------------------------------------------
# Rule-based fast gate
# ---------------------------------------------------------------------------


def rule_gate(
    event: MissionEvent,
    adjacent: bool = False,
) -> GateDecision | None:
    """
    Returns a GateDecision if the rules are conclusive, else None (send to LLM).

    Two relevance modes:
      adjacent=False (DIRECT)   — event is directly relevant to this soldier
                                  (own sector, own callsign, own role's
                                  affinity). Speak threshold is relaxed.
      adjacent=True  (ADJACENT) — event is in the broader AO but not directly
                                  the soldier's. Speak threshold is stricter
                                  so we don't chatter about other people's
                                  business.

    DIRECT rules:
      SPEAK    — urgency in (medium, high, critical) AND confidence >= 0.45
      STASH    — urgency=low  AND confidence >= 0.5  (kept in context, no speech)
      DROP     — urgency=low  AND confidence < 0.5    (noise floor)
      None     — anything else, defer to LLM

    ADJACENT rules:
      SPEAK    — urgency in (high, critical) AND confidence >= 0.7
      DROP     — urgency=low  OR  confidence < 0.3
      None     — anything else, defer to LLM
    """
    u = event.urgency.lower()
    c = event.confidence

    if adjacent:
        # Conservative path — only speak for clear, high-urgency events.
        if u in ("high", "critical") and c >= ADJACENT_CONFIDENCE_THRESHOLD:
            score = 0.7 + 0.3 * c
            return GateDecision(
                action=Action.SPEAK,
                severity_score=round(score, 3),
                reason=(
                    f"Rule: urgency={u} confidence={c:.2f}"
                    f" threshold={ADJACENT_CONFIDENCE_THRESHOLD}"
                    f" (adjacent-stricter) => speak"
                ),
            )
        if u == "low" or c < 0.3:
            return GateDecision(
                action=Action.DROP,
                severity_score=round(c * 0.3, 3),
                reason=(
                    f"Rule: urgency={u} confidence={c:.2f} adjacent"
                    f" => drop (noise floor)"
                ),
            )
        return None  # borderline, send to LLM

    # Hard noise floor — regardless of urgency, very low confidence drops.
    if c < 0.3:
        return GateDecision(
            action=Action.DROP,
            severity_score=round(c * 0.3, 3),
            reason=(
                f"Rule: confidence={c:.2f} below noise floor"
                f" => drop"
            ),
        )

    # DIRECT relevance: relaxed speak threshold so per-soldier updates surface
    if u in ("medium", "high", "critical") and c >= 0.45:
        # high/critical → strong speak; medium → still speak but lower score
        base = 0.7 if u in ("high", "critical") else 0.55
        score = base + 0.3 * c
        return GateDecision(
            action=Action.SPEAK,
            severity_score=round(min(score, 1.0), 3),
            reason=(
                f"Rule: urgency={u} confidence={c:.2f} direct => speak"
            ),
        )

    # Low urgency direct events: keep available silently if credible, else noise
    if u == "low":
        if c >= 0.5:
            return GateDecision(
                action=Action.STASH,
                severity_score=round(c * 0.5, 3),
                reason=(
                    f"Rule: urgency=low confidence={c:.2f} direct"
                    f" => stash (kept in context, not spoken)"
                ),
            )
        return GateDecision(
            action=Action.DROP,
            severity_score=round(c * 0.3, 3),
            reason=(
                f"Rule: urgency=low confidence={c:.2f} direct"
                f" => drop (noise floor)"
            ),
        )

    return None


# ---------------------------------------------------------------------------
# LLM-based classifier (haiku-class, borderline events only)
# ---------------------------------------------------------------------------

CLASSIFIER_SYSTEM_PROMPT = """\
You are the severity gate for Mission Bay, a realtime transit copilot moving \
a VIP delegation from SFO to Moscone Center. Your job is to classify \
incoming events and decide whether the voice agent should speak proactively \
right now, stash the event silently into context, or drop it entirely.

# Mission context
- Route A: US-101 N → I-80 W → 4th St → Howard St → Moscone. 90-minute window.
- Route C: US-101 N → I-280 N → surface streets. Slower fallback.
- High-value protection mission. Chatter is the #1 failure mode. Only speak \
when the delegation's safety, timing, or route is materially affected RIGHT NOW.

# Decision rules

SPEAK (action="speak") when ALL of the following:
  1. The event directly affects Route A, Route C, Howard St, 4th St, \
Moscone Center, SFO, Bay Bridge, or team positions.
  2. The change is material: road closed, crowd >100 people blocking a route, \
active incident requiring reroute, visibility danger, or VIP-proximity threat.
  3. confidence >= 0.45.
  4. The information has not already been communicated (check conversation \
context for duplicates).

STASH (action="stash") when:
  - The event is credible (confidence >= 0.35) and geographically relevant \
but NOT yet operationally urgent (e.g. developing situation, possible future \
impact, or confirmation pending).
  - OR: urgency==medium and route impact is indirect.

DROP (action="drop") when ANY of the following:
  - confidence < 0.35.
  - The event location is geographically irrelevant to the active routes.
  - The event is routine/administrative (Muni schedule, 311 noise complaint, \
distant weather with no route impact).
  - The event duplicates something already spoken in recent conversation.

# severity_score
Float 0.0-1.0 representing how operationally urgent this event is:
  - 0.9-1.0: Immediate safety/route threat.
  - 0.7-0.89: Significant but manageable (reroute advisable).
  - 0.5-0.69: Worth monitoring, stash for context.
  - 0.0-0.49: Noise, drop.

# suggested_utterance
Only include for action="speak". Write exactly what the agent should say \
aloud: 1-3 short conversational sentences in first-person present tense. \
Sound like a calm, professional copilot. Reference the specific route, \
location, or time impact. Do NOT use jargon, coordinates, or JSON.

# Output format
Respond with ONLY valid JSON. No markdown, no commentary outside the object.
{
  "action": "speak" | "stash" | "drop",
  "severity_score": <float 0.0-1.0>,
  "reason": "<one sentence explaining the decision>",
  "suggested_utterance": "<agent speech text, omit key if not speak>"
}"""

CLASSIFIER_USER_TEMPLATE = """\
## Incoming event
{event_json}

## Current world state summary
{world_state_summary}

## Last {n_turns} turns of conversation
{conversation_context}

Classify this event. Output strict JSON only."""


async def llm_classify(
    event: MissionEvent,
    world_state_summary: str,
    conversation_context: str,
    n_turns: int = 4,
) -> GateDecision:
    """Call the haiku-class LLM to classify a borderline event.

    Uses the standard LiveKit Inference classifier model. Returns a GateDecision.
    On any failure (timeout, parse error) defaults to STASH so we never drop
    a potentially important event silently.
    """
    event_json = json.dumps(
        {
            "id": event.id,
            "timestamp": event.timestamp,
            "eventType": event.eventType,
            "summary": event.summary,
            "confidence": event.confidence,
            "urgency": event.urgency,
            "risk_assessment": event.risk_assessment,
            "location_guess": event.location_guess,
            "source": event.source,
        },
        ensure_ascii=False,
    )

    user_prompt = CLASSIFIER_USER_TEMPLATE.format(
        event_json=event_json,
        world_state_summary=world_state_summary or "(world state unavailable)",
        conversation_context=conversation_context or "(no recent turns)",
        n_turns=n_turns,
    )

    try:
        llm_client = inference.LLM(
            model=os.getenv(
                "LIVEKIT_CLASSIFIER_MODEL_ID",
                os.getenv("LIVEKIT_LLM_MODEL_ID", DEFAULT_CLASSIFIER_MODEL),
            ),
        )
        async with llm_client:
            llm_client.chat_ctx_copy() if hasattr(llm_client, "chat_ctx_copy") else None
            # Build a minimal chat context for the classifier
            messages = [
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            # Use the LLM directly through LiveKit inference
            response_text = await _call_llm_for_classification(llm_client, messages)
    except Exception:
        logger.exception(
            "LLM classifier failed for event %s; defaulting to stash", event.id
        )
        return GateDecision(
            action=Action.STASH,
            severity_score=0.5,
            reason="LLM classifier error; conservatively stashed",
        )

    return _parse_classifier_response(response_text, event)


async def _call_llm_for_classification(llm_client, messages: list[dict]) -> str:
    """Low-level call to the LLM. Returns the raw response string.

    Uses the current livekit-agents API: `ChatContext.add_message(role=...,
    content=...)` with plain string roles ("system" | "user" | "assistant"),
    and `llm_client.chat(chat_ctx=ctx).to_str_iterable()` for a clean async
    string stream.
    """
    from livekit.agents.llm import ChatContext

    ctx = ChatContext.empty()
    for m in messages:
        role = m.get("role", "user")
        if role not in ("system", "user", "assistant"):
            role = "user"
        ctx.add_message(role=role, content=m["content"])

    chunks: list[str] = []
    async for chunk in llm_client.chat(chat_ctx=ctx).to_str_iterable():
        chunks.append(chunk)
    return "".join(chunks)


def _parse_classifier_response(raw: str, event: MissionEvent) -> GateDecision:
    """Parse the LLM JSON response. Falls back to STASH on any parse failure."""
    raw = raw.strip()
    # Strip markdown code fences if the LLM wrapped the JSON anyway
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(line for line in lines if not line.startswith("```")).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "Could not parse classifier JSON for event %s: %r", event.id, raw[:200]
        )
        return GateDecision(
            action=Action.STASH,
            severity_score=0.5,
            reason="Classifier returned unparseable JSON; conservatively stashed",
        )

    try:
        action = Action(parsed["action"])
    except (KeyError, ValueError):
        action = Action.STASH

    severity_score = float(parsed.get("severity_score", 0.5))
    severity_score = max(0.0, min(1.0, severity_score))
    reason = str(parsed.get("reason", ""))
    suggested_utterance = str(parsed.get("suggested_utterance", ""))

    return GateDecision(
        action=action,
        severity_score=severity_score,
        reason=reason,
        suggested_utterance=suggested_utterance,
    )


# ---------------------------------------------------------------------------
# Main gate entry point
# ---------------------------------------------------------------------------


async def run_gate(
    event: MissionEvent,
    world_state_summary: str = "",
    conversation_context: str = "",
    adjacent: bool = False,
) -> GateDecision:
    """Run the hybrid gate: rule gate first, then LLM for borderline cases.

    Args:
        event: The incoming MissionEvent.
        world_state_summary: Compact JSON string of current world state.
        conversation_context: Last N turns of conversation as plain text.
        adjacent: True when the relevance verdict was ADJACENT — applies
                  stricter confidence threshold in the rule gate.

    Returns:
        GateDecision with action, severity_score, reason, and (if SPEAK)
        suggested_utterance.
    """
    # Fast rule gate — no LLM cost
    decision = rule_gate(event, adjacent=adjacent)
    if decision is not None:
        logger.debug(
            "Rule gate => %s (score=%.2f) for event %s",
            decision.action,
            decision.severity_score,
            event.id,
        )
        return decision

    # Borderline: send to LLM classifier
    logger.debug(
        "Rule gate inconclusive for event %s; calling LLM classifier", event.id
    )
    decision = await llm_classify(event, world_state_summary, conversation_context)
    logger.debug(
        "LLM gate => %s (score=%.2f) for event %s",
        decision.action,
        decision.severity_score,
        event.id,
    )
    return decision


# ---------------------------------------------------------------------------
# generate_reply instruction builder
# ---------------------------------------------------------------------------


def build_reply_instructions(
    event: MissionEvent,
    decision: GateDecision,
    callsign: str = "",
) -> str:
    """Build the instructions= string for session.generate_reply().

    All proactive utterances MUST begin with "{callsign}, " so the soldier
    immediately recognises the message is addressed to them.

    The agent is told:
      1. That a new event just arrived (with its details).
      2. Exactly what to say (or to derive from the suggested_utterance).
      3. Style constraints: voice-only, calm, brief, in-character as Mission Bay.
    """
    callsign_prefix = f"{callsign}, " if callsign else ""

    if decision.suggested_utterance:
        utterance = decision.suggested_utterance
        # Ensure the LLM-suggested text starts with the soldier's callsign.
        if callsign and not utterance.startswith(callsign):
            utterance = callsign_prefix + utterance
        utterance_guidance = (
            f'Begin your spoken reply with the callsign prefix and say '
            f'something close to: "{utterance}" — '
            "but adapt naturally to the current conversation flow. "
        )
    else:
        utterance_guidance = (
            f'Begin your spoken reply with "{callsign_prefix}" then compose '
            f"a brief proactive update about this event in 1-3 sentences. "
        )

    return (
        "A new field event just arrived that requires a proactive voice update. "
        "Deliver this update NOW without waiting for the soldier to ask. "
        f"{utterance_guidance}"
        "Stay in character as Mission Bay: calm, professional, concise. "
        "Use plain spoken language — no markdown, no JSON, no lists. "
        "Reference the specific sector or location affected. "
        "End with a single short action option if appropriate "
        "(e.g. 'Do you want me to flag this for command?'). "
        f"Event details for reference — eventType={event.eventType}, "
        f"summary={event.summary!r}, "
        f"location={event.location_guess!r}, "
        f"urgency={event.urgency}, "
        f"confidence={event.confidence:.0%}."
    )


# ---------------------------------------------------------------------------
# Room data handler — wired up in agent.py
# ---------------------------------------------------------------------------


class AmbientHandler:
    """Stateful handler that wraps the gate, anti-chatter, and session coupling.

    Usage (in agent.py entrypoint):

        tracker = SpeakingTracker()
        tracker.register(ctx.room)
        ambient = AmbientHandler(session=session, assistant=assistant,
                                 speaking_tracker=tracker)
        await ambient.start()
        room.on("data_received", ambient.handle_data_received)
        # On shutdown: await ambient.stop()
    """

    def __init__(
        self,
        session: "AgentSession",
        assistant,  # the Assistant instance, for world-state access
        *,
        # Per-soldier profile — enables relevance filter and callsign-prefixed speech.
        # When None, all events are treated as DIRECT and no callsign prefix is added.
        soldier: SoldierProfile | None = None,
        # Legacy single-flag path kept for backward compatibility with old tests.
        # New code should pass speaking_tracker instead.
        user_speaking_flag: asyncio.Event | None = None,
        speaking_tracker: "SpeakingTracker | None" = None,
    ) -> None:
        self._session = session
        self._assistant = assistant
        self._soldier = soldier
        self._anti_chatter = AntiChatter()
        self._conflict_detector = ConflictDetector()
        # SpeakingTracker is authoritative when provided; fall back to the
        # single asyncio.Event so existing tests that pass user_speaking_flag
        # continue to work without modification.
        self._speaking_tracker = speaking_tracker
        self._user_speaking = user_speaking_flag or asyncio.Event()
        self._agent_speaking = False
        self._stash: list[MissionEvent] = []  # events silently added to context
        self._event_log: list[MissionEvent] = []  # append-only raw log (all events)
        self._lock = asyncio.Lock()
        self._stopped = False
        self._flush_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background flush loop. Call after constructing the handler."""
        self._stopped = False
        self._flush_task = asyncio.ensure_future(self._flush_loop())
        logger.debug("AmbientHandler flush loop started")

    async def stop(self) -> None:
        """Cancel the flush loop and clean up."""
        self._stopped = True
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        logger.debug("AmbientHandler flush loop stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_stash_summary(self) -> str:
        """Return a short plain-text summary of all stashed events.

        Injected into the next user-turn context so the LLM has them available.
        """
        if not self._stash:
            return ""
        lines = [
            f"[{e.timestamp}] {e.eventType}: {e.summary} "
            f"(confidence={e.confidence:.0%}, urgency={e.urgency})"
            for e in self._stash[-10:]  # last 10 only, avoid context explosion
        ]
        return "STASHED EVENTS (available for user queries):\n" + "\n".join(lines)

    async def handle_data_received(self, data: bytes, *args, **kwargs) -> None:
        """Called by room.on('data_received'). Parses and routes each event.

        Accepts two envelope shapes:
          1. {"type": "mission_event", "event": <MissionEvent dict>}
             — published by self-comms path (Assistant._publish_comms_event)
          2. {"type": "mission_event", "payload": <MissionEvent dict>}
             — legacy shape from the ingest pipeline
          3. Bare MissionEvent dict (no envelope wrapper)
        """
        try:
            raw = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.debug("Received non-JSON data on data channel; skipping")
            return

        # Unwrap envelope
        if isinstance(raw, dict) and raw.get("type") == "mission_event":
            # prefer "event" key (comms path), fall back to "payload" (ingest path)
            raw = raw.get("event") or raw.get("payload", raw)

        # Must have at least an id and summary to be a MissionEvent
        if not isinstance(raw, dict) or "summary" not in raw:
            return

        try:
            event = MissionEvent.from_dict(raw)
        except Exception:
            logger.exception("Failed to parse MissionEvent from data channel")
            return

        await self.on_event_received(event)

    async def on_event_received(self, event: MissionEvent) -> None:
        """Core handler: gate, anti-chatter, then speak or stash."""
        async with self._lock:
            await self._process_event(event)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_anyone_speaking(self) -> bool:
        """True if any room participant (user or cross-room soldier) is speaking.

        Prefers the multi-participant SpeakingTracker when available; falls
        back to the legacy single asyncio.Event for backward compatibility with
        existing tests.
        """
        if self._speaking_tracker is not None:
            return self._speaking_tracker.any_speaking()
        return self._user_speaking.is_set()

    async def _flush_loop(self) -> None:
        """Background task: pop queued SPEAK events once the room is quiet.

        Runs every 0.5 s. Delivers one event per tick — the highest-severity
        pending event — so we don't flood the room with back-to-back speech.
        Cancellable via stop().
        """
        while not self._stopped:
            await asyncio.sleep(0.5)
            if self._stopped:
                break

            # Only deliver when the room has been quiet for at least QUIET_GAP_S
            if self._is_anyone_speaking():
                continue

            if self._speaking_tracker is not None:
                elapsed = self._speaking_tracker.seconds_since_last_change()
                if elapsed < QUIET_GAP_S:
                    continue
            # If no tracker, fall through immediately (legacy mode)

            if not self._anti_chatter.has_queued():
                continue

            result = self._anti_chatter.pop_highest()
            if result is None:
                continue

            event, decision = result
            logger.debug(
                "Flush loop delivering queued event %s (score=%.2f)",
                event.id,
                decision.severity_score,
            )
            async with self._lock:
                await self._do_speak(event, decision)

    async def _process_event(self, event: MissionEvent) -> None:
        """
        Full pipeline:
          receive
            -> 1. relevance filter (UNRELATED -> DROP, else continue)
            -> 2. conflict detection (re-inject synthetic conflict events)
            -> 3. severity gate (rule + optional LLM, with ADJACENT stricter threshold)
            -> 4. anti-chatter (dedup, cooldown, queue)
            -> 5. quiet-during-comms (SpeakingTracker)
            -> speak / stash / drop
        """
        # Always append to event log for conflict detection and debugging.
        self._event_log.append(event)
        logger.info(
            "Event received: id=%s type=%s urgency=%s confidence=%.2f summary=%r",
            event.id,
            event.eventType,
            event.urgency,
            event.confidence,
            event.summary,
        )

        # ------------------------------------------------------------------
        # Step 1: Per-soldier relevance filter (pure rule-based, no LLM)
        # ------------------------------------------------------------------
        raw_dict = self._event_to_wire(event)
        if self._soldier is not None:
            verdict = is_relevant_to(raw_dict, self._soldier)
        else:
            verdict = RelevanceVerdict.DIRECT  # no profile = pass all events

        if verdict == RelevanceVerdict.UNRELATED:
            logger.debug(
                "DROP (unrelated) event %s for soldier %s",
                event.id,
                self._soldier.callsign if self._soldier else "unknown",
            )
            return

        adjacent_mode = verdict == RelevanceVerdict.ADJACENT

        # ------------------------------------------------------------------
        # Step 2: Conflict detection — check against rolling recent-event log
        # ------------------------------------------------------------------
        conflict_dicts = self._conflict_detector.check(raw_dict)
        self._conflict_detector.record(raw_dict)

        for cdict in conflict_dicts:
            logger.info(
                "Conflict emitted: %s vs %s in sector %s",
                cdict.get("extractedFields", {}).get("left_event_id", "?"),
                cdict.get("extractedFields", {}).get("right_event_id", "?"),
                (cdict.get("location") or {}).get("sectorId", "?"),
            )
            try:
                conflict_event = MissionEvent.from_dict(cdict)
                # Conflict events are always treated as DIRECT — they are
                # synthesised because the sector is already known to be relevant.
                await self._route_through_gate(conflict_event, adjacent=False)
            except Exception:
                logger.exception("Failed to route synthetic conflict event %s", cdict.get("id"))

        # ------------------------------------------------------------------
        # Steps 3-5: Gate + anti-chatter + quiet-during-comms for the original event
        # ------------------------------------------------------------------
        await self._route_through_gate(event, adjacent=adjacent_mode)

    async def _route_through_gate(self, event: MissionEvent, *, adjacent: bool) -> None:
        """Run gate -> anti-chatter -> quiet-during-comms for a single event."""
        world_state_summary = self._get_world_state_summary()
        conversation_context = self._get_conversation_context()

        decision = await run_gate(
            event, world_state_summary, conversation_context, adjacent=adjacent
        )

        # 3. Route on gate action
        if decision.action == Action.DROP:
            logger.debug("DROP event %s: %s", event.id, decision.reason)
            return

        if decision.action == Action.STASH:
            logger.info("STASH event %s: %s", event.id, decision.reason)
            self._stash.append(event)
            return

        # action == SPEAK — apply anti-chatter controls before committing
        assert decision.action == Action.SPEAK

        if self._anti_chatter.is_duplicate(event):
            logger.info(
                "SPEAK suppressed (duplicate): event %s summary already spoken",
                event.id,
            )
            self._stash.append(event)
            return

        if self._anti_chatter.on_cooldown(event):
            logger.info("SPEAK suppressed (cooldown): eventType=%s", event.eventType)
            # Buffer for later — flush loop delivers when room is quiet
            self._anti_chatter.enqueue(event, decision)
            return

        # ------------------------------------------------------------------
        # Step 5: Quiet-during-comms gate (SpeakingTracker)
        # ------------------------------------------------------------------
        if self._is_anyone_speaking():
            logger.info("SPEAK deferred (participant mid-turn): event %s queued", event.id)
            self._anti_chatter.enqueue(event, decision)
            return

        if self._speaking_tracker is not None:
            elapsed = self._speaking_tracker.seconds_since_last_change()
            if elapsed < QUIET_GAP_S:
                logger.info(
                    "SPEAK deferred (quiet gap %.1fs elapsed=%.1fs): event %s queued",
                    QUIET_GAP_S,
                    elapsed,
                    event.id,
                )
                self._anti_chatter.enqueue(event, decision)
                return

        # Clear to speak
        await self._do_speak(event, decision)

    def _event_to_wire(self, event: MissionEvent) -> dict:
        """Convert a MissionEvent dataclass instance to the wire-format dict expected
        by relevance.py and conflict.py, which operate on raw nested dicts."""
        return {
            "id": event.id,
            "missionId": "",
            "timestamp": event.timestamp,
            "eventType": event.eventType,
            "summary": event.summary,
            "confidence": event.confidence,
            "urgency": event.urgency,
            "source": {"name": event.source, "type": "", "reliability": ""},
            "location": {"sectorId": event.location_guess or None},
            "entities": [],
            "extractedFields": {},
        }

    async def _do_speak(self, event: MissionEvent, decision: GateDecision) -> None:
        """Trigger session.generate_reply and record the utterance."""
        callsign = self._soldier.callsign if self._soldier else ""
        instructions = build_reply_instructions(event, decision, callsign=callsign)
        logger.info(
            "SPEAK event %s (score=%.2f) callsign=%r: %s",
            event.id,
            decision.severity_score,
            callsign,
            decision.suggested_utterance or "(derived)",
        )

        self._agent_speaking = True
        self._anti_chatter.record_spoken(event)

        try:
            await self._session.generate_reply(instructions=instructions)
        except Exception:
            logger.exception("generate_reply failed for event %s", event.id)
        finally:
            self._agent_speaking = False

    def _get_world_state_summary(self) -> str:
        """Pull compact world state from the assistant's existing reader."""
        try:
            state = self._assistant._read_persisted_mission_state()
            ws = state.get("worldState", {}) if isinstance(state, dict) else {}
            # Trim to what the gate actually needs: route status + known risks
            compact = {
                "currentObjective": ws.get("currentObjective", ""),
                "routeStatus": ws.get("routeStatus", {}),
                "knownRisks": ws.get("knownRisks", []),
                "recentChanges": ws.get("recentChanges", []),
            }
            return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            logger.debug("Could not read world state for gate")
            return ""

    def _get_conversation_context(self, n: int = 4) -> str:
        """Extract the last n turns from the session chat context as plain text.

        LiveKit AgentSession exposes conversation history. We pull the last n
        assistant + user messages for injection into the classifier prompt.
        Falls back gracefully if the session doesn't expose history yet.
        """
        try:
            history = getattr(self._session, "chat_ctx", None)
            if history is None:
                return ""
            messages = list(history.messages)[-n * 2 :]  # n turns = 2*n messages
            lines = []
            for msg in messages:
                role = getattr(msg, "role", "unknown")
                content = getattr(msg, "content", "") or ""
                if isinstance(content, list):
                    content = " ".join(str(c) for c in content if isinstance(c, str))
                lines.append(f"{role}: {content.strip()}")
            return "\n".join(lines)
        except Exception:
            logger.debug("Could not extract conversation context")
            return ""
