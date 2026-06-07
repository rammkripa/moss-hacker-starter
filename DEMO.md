# Mission Bay — Operation South Beach demo guide

## What this is

Mission Bay is a battlefield-awareness voice copilot for individual soldiers in a notional defensive security training exercise in South Beach SF (centered on 680 2nd Street). Two soldiers — **Bravo-3** (recon) and **Singh** (medic) — each connect from a phone and get per-soldier-tailored voice updates fused from drone photos, satellite imagery (mock), soldier comms, biosensors (mock), real NWS weather, and FAA NOTAMs.

The agent **stays quiet while anyone is talking** and chimes in only on **conflicts** between data sources or **info specifically relevant** to that soldier's role + sector.

This is decision support only — never directs lethal action, never identifies persons from imagery, never asserts intent.

## One-time setup

### 1. Install dependencies

```bash
pnpm setup
```

This runs `pnpm install` in `frontend/` and `uv sync` in `agent-py/`, and seeds `.env.local` from `.env.example`.

### 2. Fill in `.env.local` files

Both files need the same `MISSION_INGEST_SECRET` (any random string) and the same `LIVEKIT_ROOM_NAME`.

**`agent-py/.env.local`** — minimum required:

```dotenv
LIVEKIT_URL=wss://<your-project>.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
LIVEKIT_ROOM_NAME=mission_bay_demo_room

LIVEKIT_LLM_MODEL_ID=openai/gpt-4.1-mini
LIVEKIT_CLASSIFIER_MODEL_ID=openai/gpt-4.1-mini

MOSS_PROJECT_ID=...
MOSS_PROJECT_KEY=...
MOSS_INDEX_NAME=knowledge
MOSS_MEMORY_INDEX_NAME=memory
MOSS_EVENTS_INDEX_NAME=events
MOSS_MODEL_ID=moss-minilm

MISSION_INGEST_URL=http://localhost:3000/api/mission/ingest
MISSION_INGEST_SECRET=pick-any-string-here

# Optional — feeds fall back to mock-only mode if these are blank
API_511_KEY=
FAA_NOTAM_CLIENT_ID=
FAA_NOTAM_CLIENT_SECRET=
```

**`frontend/.env.local`** — minimum required:

```dotenv
LIVEKIT_URL=wss://<your-project>.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
LIVEKIT_ROOM_NAME=mission_bay_demo_room
AGENT_NAME=agent-py

OPENAI_API_KEY=...
REAL_OPENAI_KEY=... # optional, if OPENAI_API_KEY is reserved for another gateway
OPENAI_VISION_MODEL=gpt-4o-mini
VISION_MODEL=gpt-4o-mini

MOSS_PROJECT_ID=...
MOSS_PROJECT_KEY=...
MOSS_API_BASE_URL=https://api.moss.dev/v1
MOSS_EVENTS_INDEX_NAME=events

MISSION_INGEST_SECRET=pick-any-string-here
```

Both `MISSION_INGEST_SECRET` values must match.

### 3. Download voice models

```bash
pnpm agent:py:download-files
```

Fetches Silero VAD + the multilingual turn detector.

### 4. Seed Moss indexes

```bash
pnpm moss:index
```

Creates three Moss indexes: `knowledge` (seeded with the 13 South Beach AO entries), `memory` (per-user, seeded with a placeholder), and `events` (seeded with a placeholder; live writes happen at runtime).

## Run the stack

```bash
pnpm dev
```

This starts three processes via `concurrently`:
- **`agent-py`** — the Python LiveKit agent
- **`frontend`** — the Next.js app on `http://localhost:3000`
- **`feeds`** — the mock + real feed worker that POSTs `MissionEvent`s to `/api/mission/ingest`

Expected log lines once everything is up:

```
[agent-py]    registered worker { agent_name: "agent-py", ... }
[frontend]    ✓ Ready in ...
[feeds]       Mission Bay feed worker starting. Ingest URL: http://localhost:3000/api/mission/ingest
[feeds]       satellite_mock: 1 new events
[feeds]       biosensor_mock: 2 new events
```

If you don't have Moss/OpenAI credentials yet and just want to see the UI: `pnpm dev:agent-py` + `pnpm dev:frontend` runs just the agent + UI, no feeds.

## Test 1 — Two phones, two soldiers

1. Open `http://<your-laptop-ip>:3000/mobile` on Phone A (or Chrome tab).
2. Fill in the soldier form:
   - Callsign: **`Bravo-3`**
   - Role: **`recon`**
   - Tap **Connect to Mission Bay**.
3. Open the same URL on Phone B.
4. Fill in:
   - Callsign: **`Singh`**
   - Role: **`medic`**
   - Tap **Connect to Mission Bay**.
5. Wait ~20 seconds while both connect. You should each hear an initial greeting addressed by callsign.

Both phones are in the same LiveKit room, but each runs its own per-soldier filter, so each soldier hears different things.

## Test 2 — Photo upload (vision parser)

On Bravo-3's phone:

1. Tap **Take or choose photo**.
2. Pick any street photo (a real SF photo for the best result; any photo works for smoke testing).
3. Within ~3 seconds you should see the parsed summary appear under the button. e.g.:
   > Submitted: Several hundred demonstrators on Market Street near the Ferry Building.
4. If the photo is materially relevant to Bravo-3's current sector (A7 by default), the agent may proactively chime in.

The parsed event is also pushed to Singh's phone — but Singh's relevance filter generally drops visual events that don't affect her medical role, unless they imply casualties.

## Test 3 — Manual ingest (no photo)

From any shell:

```bash
SECRET=$(grep MISSION_INGEST_SECRET frontend/.env.local | cut -d= -f2)
curl -X POST http://localhost:3000/api/mission/ingest \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $SECRET" \
  -d @- <<JSON
{
  "event": {
    "id": "manual-bay-bridge-1",
    "missionId": "operation-south-beach",
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "source": { "type": "manual_note", "name": "operator", "reliability": "high" },
    "eventType": "incident",
    "summary": "Possible OP indicator at 2nd and Bryant — single unmarked vehicle parked, observation pattern.",
    "entities": [],
    "location": { "sectorId": "A4", "description": "2nd and Bryant" },
    "confidence": 0.75,
    "urgency": "high",
    "affectsWorldState": true
  }
}
JSON
```

Bravo-3 (recon, near A4) should hear about this proactively within ~2s. Singh probably won't unless it's flagged as medical.

## Test 4 — Demo timeline (let the worker drive the story)

Just run `pnpm dev` and connect both phones. The feed worker plays a deterministic 10-minute script:

- T+0:30 satellite reports A5 (South Park block) clear
- T+1:00 Bravo-3 starts moving north up 2nd Street
- T+2:00 OPFOR intercept hints at activity near Bay Bridge anchorage
- T+5:00 NWS fog advisory hits
- T+5:30 satellite NOW reports vehicle disposition in A5 → **CONFLICT** with the T+0:30 read → Bravo-3 hears the conflict alert
- T+6:00 Bravo-3 enters A5
- T+7:30 FAA NOTAM TFR over SFO bayside → rotary support degraded
- T+8:00 Bravo-3's biosensor spikes → **Singh hears a medic alert**, Bravo-3 doesn't
- T+9:00 second OPFOR intercept escalates

Demo time starts when the `feeds` process boots. The full timeline is in `agent-py/scripts/demo_script.py`.

## Test 5 — Voice questions

While connected, ask either phone:

- "Catch me up." → agent calls `search_dynamic_events` + `get_recent_changes`, briefs that soldier
- "What is sector A four like right now?" → agent calls `search_static_context` for baseline + `search_dynamic_events` for live changes
- "Who is at staging?" → uses static context (Singh, Z1)
- "Is there a conflict on the picture?" → agent should reference the conflict detector's findings if any

Verify the agent **opens with the callsign** ("Bravo Three, ..." / "Singh, ...").

## Test 6 — Quiet during comms

While Bravo-3 is mid-sentence on Phone A, trigger an event (Test 3 curl). The agent should NOT cut in. It should wait ~2.5s after Bravo-3 stops talking, then speak. If the same event already faded, it stays quiet.

## Architecture notes

- All events flow through one chokepoint: `POST /api/mission/ingest` (Zod-validated, dedup'd, written to Moss `events` index, broadcast on the LiveKit room data channel).
- Each soldier's agent runs the same hybrid gate (rule + LLM borderline) with two additional layers:
  - **Relevance** (`agent-py/src/relevance.py`) — DIRECT / ADJACENT / UNRELATED per soldier
  - **Conflict detection** (`agent-py/src/conflict.py`) — emits synthetic `conflict` events when sources disagree on the same sector
- The `SpeakingTracker` (`agent-py/src/speaking_tracker.py`) listens on `room.active_speakers_changed` and feeds the `AmbientHandler._flush_loop` (2.5s quiet gap before speech).

## Troubleshooting

- **Frontend can't start ("next: command not found")**: `pnpm --dir frontend install`
- **Agent crashes on first run with `model_q8.onnx` missing**: `pnpm agent:py:download-files`
- **Feed worker logs `Ingest rejected event: HTTP 401`**: `MISSION_INGEST_SECRET` differs between agent-py and frontend `.env.local`. Set them to the same string.
- **Feed worker logs `Ingest rejected event: HTTP 422`**: the `MissionEvent` shape changed; update the feed normalizer to match the new Zod schema in `frontend/app/api/mission/ingest/route.ts`.
- **Vision parser returns 502**: OpenAI vision credentials are missing or invalid
  in `frontend/.env.local`. Set `OPENAI_API_KEY` and a vision-capable model such
  as `OPENAI_VISION_MODEL=gpt-4o-mini`.
- **Agent never speaks proactively**: confirm `pnpm dev` shows all three processes running and that the feed worker logs "N new events" lines. The agent listens on the room data channel; if feeds aren't pushing, the agent has nothing to surface.
