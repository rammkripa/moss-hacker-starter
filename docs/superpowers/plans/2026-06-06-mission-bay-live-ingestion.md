# Mission Bay Live Ingestion + Ambient Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

---

# Addendum (2026-06-06): South Beach battlefield-awareness pivot — build status

## What this plan now targets

A per-soldier semantic filter over a fused multi-source event stream, framed as a **notional defensive security training exercise — Operation South Beach — centered on 680 2nd Street, San Francisco**. Two connected soldiers in the demo:

- **Bravo-3** (recon, Bravo unit) — patrols 2nd Street corridor, sectors A1–A7
- **Singh** (medic, Alpha unit) — at staging Z1 near South Beach Marina

Sector grid: `A1: 2nd/Howard`, `A2: 2nd/Folsom`, `A3: 2nd/Harrison`, `A4: 2nd/Bryant` (Bay Bridge anchorage proximity), `A5: 2nd/Brannan` (South Park block), `A6: 2nd/Townsend`, `A7: 2nd/King` (Oracle Park proximity), `Z1: South Beach Marina`.

Static data: maps + terrain + mission OPORD (in Moss `knowledge` index).
Dynamic data: locations, drone images (vision-parsed), satellite imagery (mock periodic), comms channel (each soldier's STT'd speech), biosensor mock, OPFOR intercept mock, real NWS weather, real (or mock-fallback) FAA NOTAMs.
Behavior: stay quiet while any participant in the room is speaking; chime in only on conflicts or info materially relevant to that soldier.

## Build status (after 4 parallel subagents on 2026-06-06)

**FOUNDATION — DELIVERED AND TESTED** (116 of 119 pytest cases pass):

| Piece | File(s) | Status |
|---|---|---|
| Soldier profile + dispatch metadata parsing | `agent-py/src/soldier.py`, `agent-py/src/agent.py` (entrypoint), `frontend/app/api/token/route.ts`, `frontend/app/mobile/page.tsx` | ✅ wired, tests pass |
| Self-comms publish (own STT transcript → mission_event data frame) | `agent-py/src/agent.py` (`_on_user_input_transcribed`, `_publish_comms_event`) | ✅ wired |
| Cross-participant speaking tracker (`active_speakers_changed`) | `agent-py/src/speaking_tracker.py` | ✅ wired, 8 tests pass |
| Ambient gate — relevance + conflict + quiet-during-comms | `agent-py/src/ambient.py`, `agent-py/src/relevance.py`, `agent-py/src/conflict.py` | ✅ wired, 8 + 29 tests pass |
| 6 feeds — satellite/biosensor/location/OPFOR mocks + real NWS + dual-mode FAA NOTAMs | `agent-py/scripts/feeds/*.py`, `agent-py/scripts/worker.py`, `agent-py/scripts/demo_script.py` | ✅ wired, 49 tests pass |
| South Beach knowledge corpus (13 entries, all SF-real geography) | `agent-py/knowledge.json` | ✅ written |
| South Beach agent instructions (per-soldier addressing + ROE + no-person-ID guardrails) | `agent-py/src/agent.py` | ✅ written |
| Pre-connect form on `/mobile` (callsign + role) | `frontend/app/mobile/page.tsx` | ✅ wired |
| `comms` and `conflict` added to `eventType` union | `frontend/lib/mission/types.ts` | ✅ wired |

**STILL TODO** (these tasks from Phase 2/3/4/6 of the main plan are NOT yet started):

| Piece | Why it matters | Plan task |
|---|---|---|
| `frontend/app/api/mission/ingest/route.ts` — the single Zod-validated chokepoint | Without it, feeds have no HTTP target to POST to | Task 7 |
| `frontend/lib/moss/moss-http.ts` — REST wrapper for writing to Moss `events` index | Without it, events aren't persisted to Moss for retrieval | Task 6 |
| Moss `events` index seed (`create_index.py` change + re-run `pnpm moss:index`) | Without it, agent's `search_dynamic_events` queries a non-existent index | Task 5 |
| Agent-side `events`-index retargeting of `search_dynamic_events` | Currently still reads from in-memory log only | Task 8 |
| Vision parser endpoint `POST /api/mission/ingest/photo` (Anthropic-backed) | Phone-uploaded "drone still" → MissionEvent | Tasks 9, 10 |
| `@anthropic-ai/sdk`, `zod`, Jest install on frontend | Prereq for vision parser + ingest tests | Task 2 |
| Photo upload UI on `/mobile` | Phone-side capture | Task 11 |
| FAA NOTAMs production credentials (or use the scripted-mock fallback for demo) | Real NOTAM feed | Open decision in Task 14 |

**KNOWN FAILING TESTS** (3):

1. `tests/test_ambient.py::test_gate_speak_decision_has_valid_suggested_utterance` — pre-existing, flagged by prompt-engineer agent in their "open decisions"; the fallback instruction text contains the literal string "Mission Bay" which an existing test asserts is absent. Either delete that assertion or rephrase the fallback.
2. `tests/test_comms_and_tracker.py::test_publish_comms_event_builds_correct_envelope` — fails on `from agent import Assistant` due to a pytest collection import issue with `livekit.agents.Agent`. The class exists (verified: `python -c "from livekit.agents import Agent"` works); pytest sees "unknown location". Likely a `sys.path` / namespace-package interaction with `livekit-agents 1.5.16` under pytest's collector. Workaround: add `conftest.py` to fix import order, or refactor the test to mock `Assistant` rather than import it.
3. `tests/test_comms_and_tracker.py::test_publish_comms_event_skips_when_no_room` — same root cause as #2.

## Architecture changes the agents introduced vs. the original plan

- **`MissionEvent.eventType`** now includes `"comms"` and `"conflict"` (the original plan added 6 vision-related categories; the subagents added 2 more). Update the Zod schema in Task 7 accordingly.
- **Ambient gate is now per-soldier**: `AmbientHandler(soldier=SoldierProfile)`. The `is_relevant_to(event, soldier)` filter (in `agent-py/src/relevance.py`) runs BEFORE the severity gate and returns `DIRECT | ADJACENT | UNRELATED`. ADJACENT raises the SPEAK confidence threshold from 0.5 to 0.7; UNRELATED forces DROP.
- **Conflict detection is per-handler (per-soldier)**, not global. Each soldier's `ConflictDetector` only sees events that arrived at that soldier's agent.
- **`AmbientHandler` now takes a `SpeakingTracker`** in addition to the legacy `user_speaking_flag`. The new `_flush_loop` ticks every 0.5s and pops the highest-severity queued event once `any_speaking() == False` AND `seconds_since_last_change() >= QUIET_GAP_S (2.5)`.
- **Frontend `/api/token` now requires `callsign` + `role`** in the POST body (400 if missing). The agent dispatch metadata becomes `{user_id, callsign, role, unit, current_sector}`.

## What this addendum supersedes

- **Task 4** (SF reskin to VIP transit) is REPLACED by the South Beach corpus and instructions delivered by Agent 4. The current `agent-py/knowledge.json` and `agent-py/src/agent.py` instructions block ARE the new content; do not re-apply the original Task 4 body.
- **Task 8** (agent refactor) is PARTIALLY DONE: data-channel handler, ambient wiring, in-memory event log are all in. Still needed: retarget tools to query the Moss `events` index once Tasks 5–7 are done.
- **Task 12** (ambient gate) is DONE and EXTENDED: now includes per-soldier relevance + conflict detection + quiet-during-comms, on top of the original hybrid severity gate.
- **Task 13** (wire ambient handler) is DONE.
- **Task 14** (external feeds) is DONE with a different feed mix: satellite/biosensor/location/OPFOR mocks + real NWS + FAA NOTAMs (dual mode), instead of SF 311/511/NWS. The `demo_script.py` and 10-minute scripted timeline are new.
- **Task 15** (feed worker + `pnpm dev:feeds`) needs the `pnpm dev:feeds` wire-up; the worker code exists at `agent-py/scripts/worker.py`.

## Next steps to reach a runnable end-to-end demo

1. Install frontend deps: `cd frontend && pnpm add zod @anthropic-ai/sdk nanoid && pnpm add -D jest @types/jest ts-jest @types/node`
2. Fix the 3 failing tests (1 assertion update, 2 import-order fixes).
3. Implement Tasks 5–7 from the main plan: `events` index seed, `moss-http.ts`, `/api/mission/ingest`.
4. Implement Tasks 9–11: vision parser + photo upload endpoint + `/mobile` photo UI.
5. Wire `pnpm dev:feeds` into `package.json`.
6. `pnpm moss:index` to seed the new corpus + `events` index.
7. End-to-end smoke test per the updated `DEMO.md`.

---

**Goal:** Turn Mission Bay from a scripted-events demo into a real-time SF VIP-transit copilot that (a) live-ingests events from public SF civic feeds and phone-uploaded "drone" photos, (b) writes them to Moss for semantic retrieval, (c) pushes them to the LiveKit room in real time, and (d) lets the voice agent proactively speak in ambient mode when material events arrive.

**Architecture:**

- Single ingest chokepoint: `POST /api/mission/ingest` accepts validated `MissionEvent` payloads from any source (photo parser, feed worker, dashboard), writes to a new Moss `events` index, updates derived `WorldState`, and broadcasts to the LiveKit room data channel.
- Photo path: `POST /api/mission/ingest/photo` (multipart) → Anthropic Claude Sonnet 4.6 with structured tool-use → normalized `MissionEvent` → forwarded to `/api/mission/ingest`.
- External feeds path: a Python side-process polls SF 311 (DataSF Socrata), 511 transit, and NWS weather every 30s–5min, normalizes to `MissionEvent`, dedups, and POSTs to `/api/mission/ingest`.
- Agent receives events via `ctx.room.on("data_received")`, runs them through an ambient hybrid gate (rule first, LLM only for borderline cases), and uses `session.generate_reply` to speak proactively when material — with cooldowns, dedup, and a user-speaking guard to prevent chatter.
- Mission scenario is rebranded to **"VIP transit, SFO → Moscone, 90-min window"** with real SF geography (US-101, I-280, Bay Bridge, Embarcadero, 4th/King, Howard St, Moscone Center).

**Tech Stack:**

- Frontend: Next.js 15 (Node runtime, App Router), `livekit-server-sdk`, `@anthropic-ai/sdk`, `zod`, Jest + ts-jest
- Agent: Python 3.12, `livekit-agents`, `moss`, `aiohttp`, `python-dotenv`, pytest
- Models: Anthropic Claude Sonnet 4.6 (vision parsing), OpenAI `gpt-5.2-chat-latest` via LiveKit Inference (voice LLM), `gpt-4o-mini`-class via LiveKit Inference (ambient classifier)
- Storage: Moss indexes (`knowledge` for static RAG, `memory` for per-user, **new** `events` for global mission events). No more `/tmp` file.
- Public APIs: DataSF SF 311 Socrata, 511.org SF Bay transit, api.weather.gov

---

## Conflicts Resolved Up Front

These calls were made before splitting into tasks. They override individual subagent designs where they disagreed.

| Decision | Choice | Why |
|---|---|---|
| Where do feeds write events? | Through `/api/mission/ingest` (HTTP), not directly to Moss/LiveKit | Single chokepoint = centralized dedup + auth + reducer |
| Events index location | NEW `events` index, separate from `memory` | `memory` is per-user (filter-guarded); events are global |
| `eventType` union | Widen to include `traffic`, `crowd`, `weather`, `infrastructure`, `protest`, `incident` | Vision parser + feeds emit these naturally |
| `source.type` union | Add `mobile_capture` | Photo uploads have a distinct provenance |
| `urgency` union | Keep existing `low\|medium\|high\|critical` | Reserve `critical` for highest-impact route blockers |
| `/tmp` file | Removed entirely; dashboard reducer in process memory | Agent uses Moss + in-memory world state |
| Ingest auth | Shared secret `MISSION_INGEST_SECRET` header | Quick, gates public ingress |
| Vision model | Anthropic Claude Sonnet 4.6, OpenAI fallback flag | Tool-use enforces strict JSON; one SDK |
| Ambient gate | Hybrid (rule first, LLM only for borderline) | Best chatter-vs-cost trade |
| Feed worker | Python side-process, `pnpm dev:feeds` via concurrently | Reuses Moss SDK + LiveKit creds |
| External feeds | SF 311 (2min), 511 transit (30s), NWS weather (5min) | Three real, no-key-or-free-key feeds covering route-risk surfaces |

---

## File Structure

### New files

```
docs/superpowers/plans/2026-06-06-mission-bay-live-ingestion.md   (this plan)

agent-py/
├── src/
│   └── ambient.py                                # ambient gate, anti-chatter, classifier
├── scripts/
│   ├── __init__.py
│   ├── worker.py                                 # main poll loop
│   ├── worker_config.py                          # cadences, bbox, constants
│   └── feeds/
│       ├── __init__.py
│       ├── sf311.py                              # SF 311 fetcher + normalizer
│       ├── sf511.py                              # 511 transit fetcher + normalizer
│       └── nws_weather.py                        # NWS weather fetcher + normalizer
└── tests/
    ├── test_ambient.py
    ├── test_agent_events.py                      # new event-related agent tests
    └── test_feed_worker.py

frontend/
├── lib/
│   ├── moss/
│   │   └── moss-http.ts                          # thin Moss REST wrapper
│   └── mission/
│       ├── vision-parser.ts                      # Anthropic wrapper + MissionEvent mapper
│       ├── vision-parser-schema.ts               # tool input_schema + runtime validator
│       └── vision-parser-prompt.ts               # system + user prompt builders
├── app/api/mission/
│   ├── ingest/
│   │   ├── route.ts                              # POST /api/mission/ingest
│   │   └── photo/
│   │       └── route.ts                          # POST /api/mission/ingest/photo
└── __tests__/
    ├── api/mission/ingest.test.ts
    ├── api/mission/ingest-photo.test.ts
    └── lib/mission/vision-parser.test.ts

frontend/jest.config.js
```

### Modified files

```
agent-py/
├── src/
│   ├── agent.py                                  # Remove /tmp path. Add data_received handler. Retarget tools to Moss events index + in-memory world state. Wire ambient handler.
│   └── create_index.py                           # Add `events` index seed
├── knowledge.json                                # Rewritten for SF VIP scenario
├── .env.example                                  # Add MOSS_EVENTS_INDEX_NAME, ANTHROPIC_API_KEY, API_511_KEY, MISSION_INGEST_SECRET, AGENT_INGEST_URL
└── pyproject.toml                                # Add aiohttp if not transitive

frontend/
├── lib/mission/
│   ├── types.ts                                  # Widen eventType + source.type unions; add VisionParseResult types
│   ├── drone-parser.ts                           # Rewrite as deprecated thin wrapper
│   ├── reducer.ts                                # No code change, but called from ingest route
│   └── fake-data.ts                              # Keep for dashboard manual injection in demo
├── app/
│   ├── api/mission/state/route.ts                # Keep for dashboard reads, but ingest is the new write path
│   └── mobile/page.tsx                           # Add photo upload UI + ambient indicator
├── .env.example                                  # Add MISSION_INGEST_SECRET, ANTHROPIC_API_KEY
└── package.json                                  # Add zod, @anthropic-ai/sdk, jest, ts-jest, @types/jest

package.json                                      # Add dev:feeds; update dev to include feeds as third concurrently target
DEMO.md                                           # Update with photo upload + ambient mode test scripts
```

---

# Phase 0: Foundation

## Task 1: Widen `MissionEvent` types

**Files:**
- Modify: `frontend/lib/mission/types.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/__tests__/lib/mission/types.test.ts`:

```ts
import type { MissionEvent } from '@/lib/mission/types';

test('MissionEvent accepts new vision-parser eventType values', () => {
  const e: MissionEvent = {
    id: 't1',
    missionId: 'operation-checkpoint-echo',
    timestamp: '2026-06-06T13:00:00Z',
    source: { type: 'mobile_capture', name: 'mobile:alvarez', reliability: 'medium' },
    eventType: 'protest',
    summary: 'Protest at Ferry Building',
    entities: [],
    confidence: 0.7,
    urgency: 'high',
    affectsWorldState: true,
  };
  expect(e.eventType).toBe('protest');
  expect(e.source.type).toBe('mobile_capture');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec jest __tests__/lib/mission/types.test.ts`
Expected: FAIL with TypeScript errors — `'protest'` not assignable to `eventType`, `'mobile_capture'` not assignable to `source.type`.

- [ ] **Step 3: Modify `frontend/lib/mission/types.ts`**

Replace the `MissionEvent` definition's `eventType` union (currently lines 94–103) with:

```ts
  eventType:
    | 'position_update'
    | 'route_status_update'
    | 'visual_observation'
    | 'traffic'
    | 'crowd'
    | 'weather'
    | 'infrastructure'
    | 'protest'
    | 'incident'
    | 'command_update'
    | 'status_report'
    | 'risk_detected'
    | 'objective_update'
    | 'equipment_update'
    | 'transit_delay'
    | 'unknown';
```

Replace the `source.type` union (currently line 90) with:

```ts
    type:
      | 'comms'
      | 'gps'
      | 'drone_image'
      | 'mobile_capture'
      | 'command_update'
      | 'manual_note'
      | 'system';
```

Append at the end of the file:

```ts
export type VisionObservationCategory =
  | 'visual_observation'
  | 'traffic'
  | 'crowd'
  | 'weather'
  | 'infrastructure'
  | 'protest'
  | 'incident';

export type VisionParseResult = {
  observationCategory: VisionObservationCategory;
  summary: string;
  confidence: number;
  urgency: 'low' | 'medium' | 'high';
  riskAssessment: string;
  vehicles: { count: number; descriptions: string[] };
  peopleEstimate: {
    count: number | null;
    bucket: 'none' | 'few' | 'dozens' | 'hundreds' | 'thousands' | 'unknown';
  };
  infrastructureState:
    | 'normal' | 'damaged' | 'blocked' | 'under_construction' | 'unknown';
  locationGuess: {
    description: string;
    landmarks: string[];
    streets: string[];
    isSanFrancisco: boolean;
    confidence: number;
  };
  notableEntities: string[];
  rejectionReason?: string;
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm exec jest __tests__/lib/mission/types.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/mission/types.ts frontend/__tests__/lib/mission/types.test.ts
git commit -m "feat(types): widen MissionEvent unions for vision parser + feeds"
```

---

## Task 2: Add frontend deps (`zod`, `@anthropic-ai/sdk`, Jest)

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/jest.config.js`

- [ ] **Step 1: Install deps**

Run:
```bash
cd frontend && pnpm add zod @anthropic-ai/sdk nanoid
cd frontend && pnpm add -D jest @types/jest ts-jest @types/node
```

- [ ] **Step 2: Create `frontend/jest.config.js`**

```js
/** @type {import('jest').Config} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  testMatch: ['**/__tests__/**/*.test.ts'],
  moduleNameMapper: { '^@/(.*)$': '<rootDir>/$1' },
};
```

- [ ] **Step 3: Add `test` script to `frontend/package.json`**

In the `scripts` block:
```json
"test": "jest"
```

- [ ] **Step 4: Verify Jest boots**

Run: `cd frontend && pnpm test -- --listTests`
Expected: lists at least `__tests__/lib/mission/types.test.ts` (created in Task 1) without errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/jest.config.js
git commit -m "build(frontend): add zod, anthropic sdk, jest"
```

---

## Task 3: Wire up env-var skeleton

**Files:**
- Modify: `agent-py/.env.example`
- Modify: `frontend/.env.example`

- [ ] **Step 1: Update `agent-py/.env.example`**

Append after the existing Moss block:
```dotenv
# New `events` index for live mission events (Task 4).
MOSS_EVENTS_INDEX_NAME=events

# Vision parser endpoint is in the frontend; agent doesn't need ANTHROPIC_API_KEY directly.

# External-feed worker (Phase 6).
SF311_APP_TOKEN=
API_511_KEY=
MISSION_INGEST_URL=http://localhost:3000/api/mission/ingest
MISSION_INGEST_SECRET=
LIVEKIT_ROOM_NAME=mission_bay_demo_room
```

- [ ] **Step 2: Update `frontend/.env.example`**

Append after the existing LiveKit block:
```dotenv
# Vision parser
ANTHROPIC_API_KEY=
VISION_MODEL=claude-sonnet-4-6
VISION_PROVIDER=anthropic

# Moss (the frontend now also writes events via REST)
MOSS_PROJECT_ID=
MOSS_PROJECT_KEY=
MOSS_API_BASE_URL=https://api.moss.dev/v1
MOSS_EVENTS_INDEX_NAME=events

# Ingest gate
MISSION_INGEST_SECRET=
```

- [ ] **Step 3: Commit**

```bash
git add agent-py/.env.example frontend/.env.example
git commit -m "chore(env): add vision, ingest, and feed env vars"
```

---

# Phase 1: SF Reskin

## Task 4: Rewrite `knowledge.json` for SFO → Moscone VIP transit

**Files:**
- Modify: `agent-py/knowledge.json`

- [ ] **Step 1: Replace contents of `agent-py/knowledge.json`**

```json
[
  {
    "id": "mission-plan-overview",
    "text": "Mission Bay is a real-time situational-awareness copilot for a 90-minute VIP transit operation in San Francisco. Operation Embarcadero One: at 13:00 local, a delegation departs SFO International and must arrive at Moscone Center (747 Howard St) by 14:30. Mission Bay surfaces uncertainty, evidence, confidence, and verification steps. It does not invent facts and explicitly flags when route status is unverified.",
    "metadata": { "category": "mission-plan", "topic": "objective" }
  },
  {
    "id": "route-a-primary",
    "text": "Route A is the primary route: SFO Departures Loop → US-101 N → I-80 W (Bay Bridge approach split-off avoided; stays on 101 to Cesar Chavez exit) → 4th Street north → 4th and Howard → Moscone Center. Estimated 28-35 minutes free-flowing. Originally marked LOW RISK before live updates. Crosses Muni line 14 (Mission), N-Judah, and T-Third at 4th & King. Sensitive to Bay Bridge backups that spill onto 101, and to protest/event traffic on 4th and Howard near Moscone.",
    "metadata": { "category": "routes", "topic": "route-a" }
  },
  {
    "id": "route-c-fallback",
    "text": "Route C is the fallback: SFO → US-101 N → I-280 N → 6th Street exit → surface streets via Brannan or Harrison → Moscone. Slower (38-48 minutes) but avoids the 4th/King Caltrain bottleneck and Howard Street activity zones. Should not be described as clear unless a recent observation confirms it; otherwise treat as fallback with unverified live status.",
    "metadata": { "category": "routes", "topic": "route-c" }
  },
  {
    "id": "neighborhood-soma",
    "text": "South of Market (SoMa) is the SF neighborhood containing Moscone Center, the destination. Bounded roughly by Market Street, 4th, Townsend, and 11th. Key risk zones: the 4th and King Caltrain plaza (heavy pedestrian and Muni activity), the Howard Street corridor (parades, protests, conventions), and the Yerba Buena/Moscone block itself when an event is in session.",
    "metadata": { "category": "terrain", "topic": "soma" }
  },
  {
    "id": "neighborhood-mission-bay",
    "text": "Mission Bay is the SF neighborhood east of SoMa, between SoMa and the bay. Hosts UCSF's Mission Bay campus and Chase Center. Adjacent to the inbound corridor along 4th Street north of Townsend. Not the destination — Moscone is in SoMa — but the operation is named for this neighborhood. Watch for Chase Center event days (concerts, Warriors home games) that produce major pedestrian flow near 3rd/4th and South.",
    "metadata": { "category": "terrain", "topic": "mission-bay" }
  },
  {
    "id": "landmark-bay-bridge",
    "text": "The San Francisco-Oakland Bay Bridge is a critical chokepoint east of downtown. Route A intentionally avoids the bridge by staying on 101 N to the Cesar Chavez exit, but a Bay Bridge eastbound closure or major backup creates spillback that affects 101 N approach lanes. A bridge closure is a HIGH urgency event and may require switching to Route C entirely.",
    "metadata": { "category": "terrain", "topic": "bay-bridge" }
  },
  {
    "id": "landmark-moscone",
    "text": "Moscone Center (747 Howard St) is the destination. Three buildings: Moscone North (Howard between 3rd and 4th), Moscone South (Howard between 3rd and 4th, south side), Moscone West (Howard at 4th). The standard VIP entrance is the Howard Street main entry. Convention activity at Moscone correlates with crowd density on Howard, 4th, and Mission streets.",
    "metadata": { "category": "terrain", "topic": "moscone" }
  },
  {
    "id": "transit-affected-lines",
    "text": "Muni lines that cross or affect the corridor: line 14 (Mission) crosses 4th/Mission and runs along the Mission Street corridor parallel to the route; lines 14R, 38 (Geary) feed Civic Center cross traffic; line 49 (Van Ness/Mission) runs directly past Moscone; N-Judah and T-Third terminate or pass through 4th and King Caltrain plaza. BART Powell, Montgomery, and Civic Center stations are on Market Street, two blocks north of Howard. Caltrain at 4th and King is the major rail terminus on the corridor.",
    "metadata": { "category": "transit", "topic": "muni-bart" }
  },
  {
    "id": "team-roster",
    "text": "Team roster for Operation Embarcadero One: Chen is the comms lead and runs the radio network. Singh is the medic on the principal vehicle. Alvarez is the recon drone operator and submits photo updates from the field. Brooks is the navigation lead and decides route changes. Park is the SFPD liaison. Lopez is the destination advance team lead, already on-site at Moscone.",
    "metadata": { "category": "team", "topic": "roster" }
  },
  {
    "id": "team-units",
    "text": "Units: Alpha is the principal vehicle convoy carrying the VIP delegation. Bravo is the chase vehicle and the field observation team — they take photos and call in observations along the corridor. Charlie is the destination advance team already at Moscone. Bravo's photo and voice observations are evidence but may still require verification when confidence is not high.",
    "metadata": { "category": "team", "topic": "units" }
  },
  {
    "id": "mission-constraints",
    "text": "Mission constraints: Mission Bay must not claim tactical certainty. Bravo comms and 311/feed reports may be delayed or incomplete. Howard Street has variable visibility around Moscone during event days. The 4th and King Caltrain plaza is a known pedestrian-density risk. The system should identify what needs verification: route blockage near 101/Cesar Chavez, protest/crowd density at Howard near Moscone, Bay Bridge spillback, and fallback Route C clearance.",
    "metadata": { "category": "constraints", "topic": "safety" }
  },
  {
    "id": "expected-catch-up",
    "text": "Expected catch-up pattern: The original plan said Route A was low risk. Live updates may change that if a Bravo photo or 311 report indicates blockage near 4th/Howard, an incident closes 101 N, a Bay Bridge closure causes spillback to 101, a Muni line 14 severe delay reflects upstream traffic, or NWS forecasts wind gusts or fog reducing Bay Bridge visibility. The highest-priority uncertainty after such events is whether Route C is clear, the magnitude of any Howard Street crowd or protest, and the live status of 101 northbound approaching SoMa.",
    "metadata": { "category": "agent-behavior", "topic": "catch-up" }
  }
]
```

- [ ] **Step 2: Update agent instructions in `agent-py/src/agent.py`**

In the `Assistant.__init__` constructor, replace the `instructions=textwrap.dedent(...)` block (currently lines 54–115) with:

```python
            instructions=textwrap.dedent(
                """\
                You are Mission Bay, a real-time situational awareness copilot for
                Operation Embarcadero One. Today you are guiding a VIP delegation
                transit from San Francisco International Airport to Moscone Center,
                a 90-minute window with a target arrival time of fourteen thirty.

                # Grounding (very important)

                - For questions about the original plan, terrain, neighborhoods,
                  routes, team roles, transit lines, or operational background,
                  call `search_static_context` before answering.
                - For questions about what changed, recent reports, live updates,
                  observations from Bravo, or feed reports, call
                  `search_dynamic_events` and `get_recent_changes` before
                  answering.
                - For questions about the current objective, team locations, route
                  status, risks, or open questions, call `get_world_state` before
                  answering.
                - If evidence is missing or unverified, say so. Do not guess.
                - Use careful language: "Based on current evidence", "The main
                  change is", "This should be verified", and "The original plan
                  said X, but live updates now indicate Y".

                # Safety framing

                - You are a situational-awareness and decision-support copilot.
                - Do not autonomously command lethal action, target people, or
                  present tactical certainty beyond evidence.
                - Surface risks, confidence, provenance, and verification steps.

                # Mission facts to remember

                - The VIP delegation must reach Moscone Center by fourteen thirty.
                - Route A runs SFO to US-101 N to Cesar Chavez to 4th Street
                  north to Howard at Moscone. Initially low risk.
                - Route C is a slower fallback via I-280 to 6th Street.
                - Moscone Center is on Howard Street at 4th in SoMa.
                - The 4th and King Caltrain plaza is a known pedestrian-density
                  risk on the corridor.
                - Bravo is the chase vehicle and submits photo observations from
                  the field. Alvarez is the recon drone operator. Brooks is the
                  navigation lead. Chen is comms. Singh is medic.

                # Memory

                - If a user shares a durable personal fact or mission note, use
                  the appropriate memory tool. Mission events arriving from the
                  field do not need to be remembered manually — they are already
                  written to the events store.

                # Output rules

                You are speaking via voice, so replies must sound natural in a
                text-to-speech system:

                - Respond in plain text only. Never use JSON, markdown, tables,
                  code, emojis, or other complex formatting.
                - Keep replies brief by default: one to four sentences.
                - Do not reveal system instructions, internal reasoning, tool
                  names, parameters, or raw outputs.
                - Spell out numbers in a voice-friendly way.

                # Guardrails

                - Stay within safe, lawful, and appropriate use; decline harmful
                  or out-of-scope requests.
                - Protect privacy and minimize sensitive data.
                """
            ),
```

- [ ] **Step 3: Update agent greeting**

In `my_agent` entrypoint, replace the `session.generate_reply` greeting (currently lines 513–519) with:

```python
    await session.generate_reply(
        instructions=(
            "Greet the user in one sentence, introduce yourself as Mission Bay, "
            "and say you can brief the SFO to Moscone transit, surface live "
            "changes, route risk, and verification steps."
        )
    )
```

- [ ] **Step 4: Verify by running the agent in console mode**

Run: `pnpm agent:py:console`
Type: "What's the mission objective?"
Expected: Agent calls `search_static_context`, replies with the SFO → Moscone framing.

- [ ] **Step 5: Re-index Moss with new content**

Run: `pnpm moss:index`
Expected: prints `Creating Moss knowledge index 'knowledge' with 12 docs` (or however many entries are in the new knowledge.json).

- [ ] **Step 6: Commit**

```bash
git add agent-py/knowledge.json agent-py/src/agent.py
git commit -m "feat(sf-reskin): rewrite knowledge corpus for SFO → Moscone VIP transit"
```

---

# Phase 2: Moss Events Index + Ingest Endpoint

## Task 5: Add `events` index to `create_index.py`

**Files:**
- Modify: `agent-py/src/create_index.py`

- [ ] **Step 1: Write the failing test**

Append to `agent-py/tests/test_moss.py` (or create if it doesn't exist):

```python
def test_create_index_includes_events_seed(monkeypatch):
    """Verify `events` seed document is generated correctly."""
    from src.create_index import _events_seed_documents

    docs = _events_seed_documents()
    assert len(docs) == 1
    assert docs[0].id == "__events_seed__"
    assert "events seed" in docs[0].text.lower()
    assert docs[0].metadata["event_type"] == "unknown"
    assert docs[0].metadata["urgency"] == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-py && uv run pytest tests/test_moss.py::test_create_index_includes_events_seed -v`
Expected: FAIL with `ImportError: cannot import name '_events_seed_documents'`.

- [ ] **Step 3: Add events index to `agent-py/src/create_index.py`**

After `DEFAULT_MEMORY_INDEX = "memory"`:
```python
DEFAULT_EVENTS_INDEX = "events"
```

After `_memory_seed_documents`:
```python
def _events_seed_documents() -> list[DocumentInfo]:
    """Placeholder so the events index exists and loads before the first ingest."""
    return [
        DocumentInfo(
            id="__events_seed__",
            text="(events seed) placeholder document. No real events yet.",
            metadata={
                "mission_id": "__seed__",
                "event_type": "unknown",
                "urgency": "low",
                "confidence": "0.0",
                "timestamp": "1970-01-01T00:00:00Z",
                "location_guess": "",
                "source": "__seed__",
                "external_id": "",
                "raw_ref": "",
            },
        )
    ]
```

In `build_indexes()`, after the memory-index creation block:
```python
    events_index = os.getenv("MOSS_EVENTS_INDEX_NAME", DEFAULT_EVENTS_INDEX)
    events_docs = _events_seed_documents()
    print(
        f"Creating Moss events index '{events_index}' with "
        f"{len(events_docs)} seed doc(s) using model '{model_id}'..."
    )
    events_result = await client.create_index(events_index, events_docs, model_id)
    print(
        f"  done (job: {events_result.job_id}, index: {events_result.index_name}, "
        f"docs: {events_result.doc_count})"
    )
```

Update the final print line:
```python
    print("All three Moss indexes created: knowledge, memory, events.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-py && uv run pytest tests/test_moss.py::test_create_index_includes_events_seed -v`
Expected: PASS.

- [ ] **Step 5: Re-create indexes against live Moss**

Run: `pnpm moss:index`
Expected: prints three "Creating Moss … index" lines and "All three Moss indexes created".

- [ ] **Step 6: Commit**

```bash
git add agent-py/src/create_index.py agent-py/tests/test_moss.py
git commit -m "feat(moss): add `events` index for live mission events"
```

---

## Task 6: Create Moss HTTP wrapper for Next.js

**Files:**
- Create: `frontend/lib/moss/moss-http.ts`
- Create: `frontend/__tests__/lib/moss/moss-http.test.ts`

> **Verification note:** The Moss REST endpoint path and auth header names below are UNVERIFIED. Confirm against https://docs.moss.dev/docs/rest-api before running. If the REST API isn't a stable path, fallback is a Python FastAPI sidecar in the agent process — see Task 6 alt below.

- [ ] **Step 1: Write the failing test**

Create `frontend/__tests__/lib/moss/moss-http.test.ts`:

```ts
import { mossAddDocs } from '@/lib/moss/moss-http';

const fetchMock = jest.fn();
global.fetch = fetchMock as any;

beforeEach(() => {
  fetchMock.mockReset();
  process.env.MOSS_PROJECT_ID = 'test-project';
  process.env.MOSS_PROJECT_KEY = 'test-key';
  process.env.MOSS_API_BASE_URL = 'https://test.moss.dev/v1';
});

test('mossAddDocs POSTs to /indexes/{name}/add_docs with auth headers', async () => {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ job_id: 'j1', index_name: 'events', doc_count: 1 }),
  });

  const res = await mossAddDocs('events', [
    { id: 'evt-1', text: 'hello', metadata: { mission_id: 'x' } },
  ]);

  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('https://test.moss.dev/v1/indexes/events/add_docs');
  expect(init.method).toBe('POST');
  expect(init.headers['X-Project-Id']).toBe('test-project');
  expect(init.headers['X-Project-Key']).toBe('test-key');
  expect(JSON.parse(init.body).documents[0].id).toBe('evt-1');
  expect(res.doc_count).toBe(1);
});

test('mossAddDocs throws if env vars are missing', async () => {
  delete process.env.MOSS_PROJECT_ID;
  await expect(mossAddDocs('events', [])).rejects.toThrow(/MOSS_PROJECT_ID/);
});

test('mossAddDocs throws on non-2xx response', async () => {
  fetchMock.mockResolvedValueOnce({
    ok: false,
    status: 500,
    text: async () => 'internal error',
  });
  await expect(
    mossAddDocs('events', [{ id: 'e', text: 't' }]),
  ).rejects.toThrow(/HTTP 500/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test moss-http`
Expected: FAIL with `Cannot find module '@/lib/moss/moss-http'`.

- [ ] **Step 3: Create `frontend/lib/moss/moss-http.ts`**

```ts
// UNVERIFIED — check https://docs.moss.dev/docs for the exact REST endpoint
// path, authentication header name, and add_docs request/response shape.
// Fallback: replace this file with a call to a FastAPI /ingest endpoint on
// the agent process (see Task 6-alt).

export type MossDocumentInput = {
  id: string;
  text: string;
  metadata?: Record<string, string>;
};

type MossAddDocsResponse = {
  job_id: string;
  index_name: string;
  doc_count: number;
};

export async function mossAddDocs(
  indexName: string,
  docs: MossDocumentInput[],
): Promise<MossAddDocsResponse> {
  const projectId = process.env.MOSS_PROJECT_ID;
  const projectKey = process.env.MOSS_PROJECT_KEY;
  if (!projectId || !projectKey) {
    throw new Error('MOSS_PROJECT_ID and MOSS_PROJECT_KEY must be set');
  }
  const base = process.env.MOSS_API_BASE_URL ?? 'https://api.moss.dev/v1';

  const res = await fetch(`${base}/indexes/${encodeURIComponent(indexName)}/add_docs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Project-Id': projectId,
      'X-Project-Key': projectKey,
    },
    body: JSON.stringify({ documents: docs }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '(no body)');
    throw new Error(`Moss add_docs failed: HTTP ${res.status} — ${text}`);
  }
  return res.json() as Promise<MossAddDocsResponse>;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test moss-http`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/moss/moss-http.ts frontend/__tests__/lib/moss/moss-http.test.ts
git commit -m "feat(moss): add Moss REST wrapper for Next.js writes"
```

**Task 6-alt** (use only if Moss REST API doesn't exist/isn't stable): Replace `mossAddDocs` body with a `fetch` to `process.env.AGENT_INGEST_URL` (e.g. `http://localhost:8765/moss/add_docs`) and add a FastAPI sidecar in the agent process exposing the Moss Python SDK. Keep the same TypeScript signature.

---

## Task 7: Create `POST /api/mission/ingest` route

**Files:**
- Create: `frontend/app/api/mission/ingest/route.ts`
- Create: `frontend/__tests__/api/mission/ingest.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/__tests__/api/mission/ingest.test.ts`:

```ts
import { POST } from '@/app/api/mission/ingest/route';
import type { MissionEvent } from '@/lib/mission/types';

jest.mock('@/lib/moss/moss-http', () => ({
  mossAddDocs: jest.fn().mockResolvedValue({ job_id: 'j1', index_name: 'events', doc_count: 1 }),
}));

jest.mock('livekit-server-sdk', () => ({
  DataPacket_Kind: { RELIABLE: 0, LOSSY: 1 },
  RoomServiceClient: jest.fn().mockImplementation(() => ({
    sendData: jest.fn().mockResolvedValue(undefined),
  })),
}));

import { mossAddDocs } from '@/lib/moss/moss-http';
import { RoomServiceClient } from 'livekit-server-sdk';

const VALID_EVENT: MissionEvent = {
  id: 'test-event-001',
  missionId: 'operation-checkpoint-echo',
  timestamp: '2026-06-06T13:10:00Z',
  source: { type: 'gps', name: 'Alpha GPS', reliability: 'high' },
  eventType: 'position_update',
  summary: 'Alpha moves toward 4th and King.',
  entities: [{ id: 'alpha', type: 'team', label: 'Alpha' }],
  confidence: 0.95,
  urgency: 'low',
  affectsWorldState: true,
};

function makeRequest(body: unknown, headers: Record<string, string> = {}) {
  return new Request('http://localhost/api/mission/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  process.env.LIVEKIT_URL = 'wss://test.livekit.cloud';
  process.env.LIVEKIT_API_KEY = 'k';
  process.env.LIVEKIT_API_SECRET = 's';
  process.env.LIVEKIT_ROOM_NAME = 'mission_bay_demo_room';
  delete process.env.MISSION_INGEST_SECRET;
});

test('accepts a valid event, writes to Moss, pushes to LiveKit', async () => {
  const res = await POST(makeRequest({ event: VALID_EVENT }));
  expect(res.status).toBe(200);
  const body = await res.json();
  expect(body).toEqual({ accepted: true, id: 'test-event-001', deduped: false });

  expect(mossAddDocs).toHaveBeenCalledTimes(1);
  const [indexName, docs] = (mossAddDocs as jest.Mock).mock.calls[0];
  expect(indexName).toBe('events');
  expect(docs[0].text).toContain('Alpha moves toward 4th and King.');
  expect(docs[0].metadata.event_type).toBe('position_update');

  const instance = (RoomServiceClient as jest.Mock).mock.instances[0];
  expect(instance.sendData).toHaveBeenCalledTimes(1);
});

test('rejects invalid event payload', async () => {
  const res = await POST(makeRequest({ event: { id: 'x' } }));
  expect(res.status).toBe(422);
  expect(mossAddDocs).not.toHaveBeenCalled();
});

test('deduplicates identical event within window', async () => {
  const res1 = await POST(makeRequest({ event: VALID_EVENT }));
  expect((await res1.json()).deduped).toBe(false);
  const res2 = await POST(makeRequest({ event: VALID_EVENT }));
  expect((await res2.json()).deduped).toBe(true);
  expect(mossAddDocs).toHaveBeenCalledTimes(1);
});

test('returns 401 when MISSION_INGEST_SECRET is set and token is wrong', async () => {
  process.env.MISSION_INGEST_SECRET = 'tok';
  const res = await POST(
    makeRequest({ event: { ...VALID_EVENT, id: 'tev-other' } }, { Authorization: 'Bearer wrong' }),
  );
  expect(res.status).toBe(401);
  expect(mossAddDocs).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test ingest.test`
Expected: FAIL with `Cannot find module '@/app/api/mission/ingest/route'`.

- [ ] **Step 3: Create `frontend/app/api/mission/ingest/route.ts`**

```ts
import { NextResponse } from 'next/server';
import { DataPacket_Kind, RoomServiceClient } from 'livekit-server-sdk';
import { createHash } from 'node:crypto';
import { z } from 'zod';
import { mossAddDocs } from '@/lib/moss/moss-http';
import { applyEventToWorldState, createInitialWorldState } from '@/lib/mission/reducer';
import type { MissionEvent, WorldState } from '@/lib/mission/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const revalidate = 0;

const SourceSchema = z.object({
  type: z.enum([
    'comms', 'gps', 'drone_image', 'mobile_capture',
    'command_update', 'manual_note', 'system',
  ]),
  name: z.string(),
  reliability: z.enum(['low', 'medium', 'high']),
});

const EntitySchema = z.object({
  id: z.string(),
  type: z.enum(['team', 'person', 'route', 'sector', 'landmark', 'vehicle', 'unknown']),
  label: z.string(),
});

const LocationSchema = z.object({
  sectorId: z.string().optional(),
  landmarkId: z.string().optional(),
  coordinates: z.object({ x: z.number(), y: z.number() }).optional(),
  description: z.string().optional(),
}).optional();

const RawInputSchema = z.object({
  modality: z.enum(['text', 'audio', 'image', 'video_frame', 'gps']),
  contentRef: z.string().optional(),
  transcript: z.string().optional(),
}).optional();

const MissionEventSchema = z.object({
  id: z.string(),
  missionId: z.string(),
  timestamp: z.string(),
  source: SourceSchema,
  eventType: z.enum([
    'position_update', 'route_status_update', 'visual_observation',
    'traffic', 'crowd', 'weather', 'infrastructure', 'protest', 'incident',
    'command_update', 'status_report', 'risk_detected',
    'objective_update', 'equipment_update', 'transit_delay', 'unknown',
  ]),
  summary: z.string().min(1).max(2000),
  entities: z.array(EntitySchema),
  location: LocationSchema,
  confidence: z.number().min(0).max(1),
  urgency: z.enum(['low', 'medium', 'high', 'critical']),
  rawInput: RawInputSchema,
  extractedFields: z.record(z.unknown()).optional(),
  affectsWorldState: z.boolean(),
});

const IngestRequestSchema = z.object({ event: MissionEventSchema });

const DEDUP_WINDOW_MS = 5 * 60 * 1000;
const _dedupCache = new Map<string, number>();
let _worldState: WorldState | null = null;

function dedupKey(event: MissionEvent): string {
  const minuteBucket = event.timestamp.slice(0, 16);
  const raw = `${event.source.name}:${event.id}:${minuteBucket}:${event.summary.slice(0, 120)}`;
  return createHash('sha256').update(raw).digest('hex').slice(0, 16);
}

function evictStaleDedup(): void {
  const cutoff = Date.now() - DEDUP_WINDOW_MS;
  for (const [k, ts] of _dedupCache) if (ts < cutoff) _dedupCache.delete(k);
}

function buildMossDoc(event: MissionEvent) {
  const text = `[${event.eventType} | ${event.source.name} | urgency:${event.urgency}] ${event.summary}`;
  return {
    id: `evt-${event.id}`,
    text,
    metadata: {
      mission_id: event.missionId,
      event_type: event.eventType,
      urgency: event.urgency,
      confidence: String(event.confidence),
      timestamp: event.timestamp,
      location_guess: event.location?.sectorId ?? event.location?.description ?? '',
      source: event.source.name,
      external_id: event.id,
      raw_ref: event.rawInput?.contentRef ?? '',
    },
  };
}

async function pushToLiveKitRoom(event: MissionEvent): Promise<void> {
  const url = process.env.LIVEKIT_URL;
  const key = process.env.LIVEKIT_API_KEY;
  const secret = process.env.LIVEKIT_API_SECRET;
  if (!url || !key || !secret) return;
  const room = process.env.LIVEKIT_ROOM_NAME ?? 'mission_bay_demo_room';
  const svc = new RoomServiceClient(url, key, secret);
  const encoded = new TextEncoder().encode(JSON.stringify({ type: 'mission_event', event }));
  await svc.sendData(room, encoded, DataPacket_Kind.RELIABLE, { topic: 'mission_event' });
}

export async function POST(req: Request): Promise<NextResponse> {
  const secret = process.env.MISSION_INGEST_SECRET;
  if (secret) {
    const auth = req.headers.get('authorization') ?? '';
    const provided = auth.startsWith('Bearer ') ? auth.slice(7) : auth;
    if (provided !== secret) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
  }

  let body: unknown;
  try { body = await req.json(); }
  catch { return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 }); }

  const parsed = IngestRequestSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: 'Validation failed', details: parsed.error.flatten() },
      { status: 422 },
    );
  }
  const { event } = parsed.data as { event: MissionEvent };

  evictStaleDedup();
  const key = dedupKey(event);
  if (_dedupCache.has(key)) {
    return NextResponse.json({ accepted: true, id: event.id, deduped: true });
  }
  _dedupCache.set(key, Date.now());

  try {
    await mossAddDocs(process.env.MOSS_EVENTS_INDEX_NAME ?? 'events', [buildMossDoc(event)]);
  } catch (err) {
    console.error('[ingest] Moss write failed:', err);
  }

  if (!_worldState) _worldState = createInitialWorldState('operation-checkpoint-echo');
  _worldState = applyEventToWorldState(_worldState, event);

  try { await pushToLiveKitRoom(event); }
  catch (err) { console.error('[ingest] LiveKit push failed:', err); }

  return NextResponse.json({ accepted: true, id: event.id, deduped: false });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test ingest.test`
Expected: PASS (all four tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/app/api/mission/ingest/route.ts frontend/__tests__/api/mission/ingest.test.ts
git commit -m "feat(api): POST /api/mission/ingest — Moss + LiveKit single chokepoint"
```

---

# Phase 3: Agent Refactor (Replace `/tmp` File)

## Task 8: Refactor agent to listen on data channel

**Files:**
- Modify: `agent-py/src/agent.py`
- Create: `agent-py/tests/test_agent_events.py`

- [ ] **Step 1: Write the failing test**

Create `agent-py/tests/test_agent_events.py`:

```python
"""Tests for the agent's data-channel event handling."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import Assistant


@pytest.fixture
def assistant():
    a = Assistant(room=None, user_id="user_1")
    a._moss = MagicMock()
    a._moss.query = AsyncMock(return_value=MagicMock(docs=[], time_taken_ms=0))
    return a


def test_event_handler_parses_envelope_and_appends_to_log(assistant):
    """A 'mission_event' data payload appends to the in-memory event log."""
    payload = {
        "type": "mission_event",
        "event": {
            "id": "evt-1",
            "missionId": "operation-checkpoint-echo",
            "timestamp": "2026-06-06T13:10:00Z",
            "source": {"type": "system", "name": "sf_311", "reliability": "medium"},
            "eventType": "incident",
            "summary": "Crash at 4th and King",
            "entities": [],
            "confidence": 0.7,
            "urgency": "high",
            "affectsWorldState": True,
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    assistant._handle_event_payload(raw)
    assert len(assistant._event_log) == 1
    assert assistant._event_log[0]["id"] == "evt-1"


def test_event_handler_ignores_unrelated_data(assistant):
    """A non-mission_event payload does not append to the log."""
    raw = json.dumps({"type": "moss_context", "data": {}}).encode("utf-8")
    assistant._handle_event_payload(raw)
    assert assistant._event_log == []


def test_event_handler_handles_invalid_json(assistant):
    """A malformed payload doesn't crash and doesn't append."""
    assistant._handle_event_payload(b"not json")
    assert assistant._event_log == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-py && uv run pytest tests/test_agent_events.py -v`
Expected: FAIL with `AttributeError: 'Assistant' object has no attribute '_event_log'`.

- [ ] **Step 3: Modify `agent-py/src/agent.py`**

Add `EVENTS_INDEX` next to `MEMORY_INDEX`:
```python
EVENTS_INDEX = os.getenv("MOSS_EVENTS_INDEX_NAME", "events")
```

In `Assistant.__init__`, initialize the event log and world state right after `self._indexes_loaded = False`:
```python
        self._event_log: list[dict] = []
        self._world_state: dict | None = None
```

Add the data handler method on `Assistant` (e.g., after `_publish_moss_context`):
```python
    def _handle_event_payload(self, raw: bytes) -> None:
        """Parse a data-channel payload and append `mission_event` payloads to the log.

        Called from the room's `data_received` handler. Tolerant of malformed
        input — never raises.
        """
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        if payload.get("type") != "mission_event":
            return
        event = payload.get("event")
        if not isinstance(event, dict) or "id" not in event:
            return
        self._event_log.append(event)
        if len(self._event_log) > 200:
            self._event_log = self._event_log[-200:]
```

Delete `_read_persisted_mission_state` and all references to `MISSION_STATE_PATH` (currently lines 185–242).

Replace `search_dynamic_events` with:
```python
    @function_tool()
    async def search_dynamic_events(self, context: RunContext, query: str) -> str:
        """Search live mission events from the events index and recent in-memory log.

        Args:
            query: The live event, update, or change to search for.
        """
        summaries: list[str] = []
        for ev in self._event_log[-25:]:
            summaries.append(
                f"{ev.get('timestamp', '')}: {ev.get('summary', '')} "
                f"[confidence={ev.get('confidence', '?')} urgency={ev.get('urgency', '?')}]"
            )
        try:
            result = await self._moss.query(EVENTS_INDEX, query, QueryOptions(top_k=5))
            await self._publish_moss_context(query, result)
            for d in getattr(result, "docs", None) or []:
                t = (getattr(d, "text", "") or "").strip()
                if t:
                    summaries.append(t)
        except Exception:
            logger.exception("Moss `events` index search failed")
        summaries = [s for s in summaries if s]
        if not summaries:
            return "No live mission events have arrived yet."
        return "\n".join(summaries)
```

Replace `get_world_state` and `get_recent_changes` with versions that read from `self._world_state` (initialized lazily by replaying `_event_log`). Add a helper:
```python
    def _world_state_or_init(self) -> dict:
        if self._world_state is None:
            self._world_state = {
                "missionId": "operation-checkpoint-echo",
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "currentObjective": "VIP delegation must reach Moscone Center by 14:30.",
                "teamPositions": {},
                "routeStatus": {
                    "route-a": {"status": "clear", "confidence": 0.55, "reason": "Planned route, no live contradiction yet.", "supportingEventIds": [], "lastUpdated": datetime.now(timezone.utc).isoformat()},
                    "route-c": {"status": "unknown", "confidence": 0.4, "reason": "Fallback, not recently verified.", "supportingEventIds": [], "lastUpdated": datetime.now(timezone.utc).isoformat()},
                },
                "knownRisks": [],
                "recentChanges": [],
                "openQuestions": [],
            }
        return self._world_state

    @function_tool()
    async def get_world_state(self, context: RunContext) -> str:
        """Return the current derived mission world state."""
        return self._compact_json(self._world_state_or_init())

    @function_tool()
    async def get_recent_changes(self, context: RunContext) -> str:
        """Return recent world-state changes and the in-memory event log tail."""
        ws = self._world_state_or_init()
        return self._compact_json({
            "recentChanges": ws.get("recentChanges", []),
            "eventLogTail": self._event_log[-10:],
        })
```

In `my_agent` entrypoint, after `await ctx.connect()` and BEFORE the `generate_reply` greeting:
```python
    # Wire data-channel listener: external feeds and the /api/mission/ingest
    # endpoint publish `{"type": "mission_event", "event": MissionEvent}` data
    # frames on the room. The Assistant appends to its in-memory log and the
    # ambient handler (Phase 5) decides what to do.
    assistant_ref = session._agent if hasattr(session, "_agent") else None

    def _on_data(packet) -> None:
        # packet: rtc.DataPacket with .data (bytes) and .participant
        agent = assistant_ref
        if isinstance(agent, Assistant):
            agent._handle_event_payload(packet.data)

    ctx.room.on("data_received", _on_data)
```

> **Verification note:** Verify the exact callback signature of `rtc.Room.on("data_received", ...)` on `livekit-agents==1.5.16`. If the callback receives `(data, participant, kind, topic)` instead of a `DataPacket`, adjust accordingly. Run `python -c "import livekit.rtc as rtc; help(rtc.Room)"` inside `agent-py/.venv` to confirm.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-py && uv run pytest tests/test_agent_events.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Run full agent test suite to verify no regressions**

Run: `cd agent-py && uv run pytest -v`
Expected: previous tests still pass except any that explicitly test `_read_persisted_mission_state` — delete those tests.

- [ ] **Step 6: Commit**

```bash
git add agent-py/src/agent.py agent-py/tests/test_agent_events.py
git commit -m "refactor(agent): replace /tmp file with data-channel + events index"
```

---

# Phase 4: Vision Parser (Photo Upload)

## Task 9: Create vision-parser schema, prompt, and wrapper

**Files:**
- Create: `frontend/lib/mission/vision-parser-schema.ts`
- Create: `frontend/lib/mission/vision-parser-prompt.ts`
- Create: `frontend/lib/mission/vision-parser.ts`
- Create: `frontend/__tests__/lib/mission/vision-parser.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/__tests__/lib/mission/vision-parser.test.ts`:

```ts
import { __setAnthropicClient, parsePhotoToMissionEvent } from '@/lib/mission/vision-parser';

function fakeAnthropic(toolInput: unknown) {
  return {
    messages: {
      create: jest.fn().mockResolvedValue({
        content: [{ type: 'tool_use', name: 'emit_mission_event', input: toolInput, id: 't1' }],
        stop_reason: 'tool_use',
      }),
    },
  } as any;
}

const TINY_JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xd9]);
afterEach(() => __setAnthropicClient(null));

test('returns well-shaped MissionEvent for valid vision response', async () => {
  __setAnthropicClient(
    fakeAnthropic({
      observationCategory: 'protest',
      summary: 'Several hundred demonstrators on Market Street outside Ferry Building.',
      confidence: 0.82,
      urgency: 'high',
      riskAssessment: 'Market east of 1st impassable to vehicles.',
      vehicles: { count: 2, descriptions: ['SFPD SUV', 'SFPD sedan'] },
      peopleEstimate: { count: null, bucket: 'hundreds' },
      infrastructureState: 'blocked',
      locationGuess: {
        description: 'Market St in front of Ferry Building',
        landmarks: ['Ferry Building clock tower'],
        streets: ['Market Street'],
        isSanFrancisco: true,
        confidence: 0.9,
      },
      notableEntities: ['Cardboard signs', 'SFPD presence'],
    }),
  );

  const outcome = await parsePhotoToMissionEvent({
    imageBytes: TINY_JPEG,
    mimeType: 'image/jpeg',
    submitterId: 'alvarez',
    locationHint: 'Embarcadero',
  });

  expect(outcome.ok).toBe(true);
  if (!outcome.ok) throw new Error();
  expect(outcome.event.eventType).toBe('protest');
  expect(outcome.event.source.type).toBe('mobile_capture');
  expect(outcome.event.source.name).toBe('mobile:alvarez');
  expect(outcome.event.confidence).toBeCloseTo(0.82);
  expect(outcome.event.urgency).toBe('high');
  expect(outcome.event.affectsWorldState).toBe(true);
});

test('off-route photo downgraded to low urgency with [off-route] prefix', async () => {
  __setAnthropicClient(
    fakeAnthropic({
      observationCategory: 'crowd',
      summary: 'Stadium crowd in Seattle.',
      confidence: 0.7,
      urgency: 'high',
      riskAssessment: 'N/A',
      vehicles: { count: 0, descriptions: [] },
      peopleEstimate: { count: null, bucket: 'thousands' },
      infrastructureState: 'normal',
      locationGuess: {
        description: 'Seattle',
        landmarks: ['Space Needle'],
        streets: [],
        isSanFrancisco: false,
        confidence: 0.1,
      },
      notableEntities: ['stadium'],
    }),
  );

  const outcome = await parsePhotoToMissionEvent({
    imageBytes: TINY_JPEG,
    mimeType: 'image/jpeg',
  });
  if (!outcome.ok) throw new Error();
  expect(outcome.event.summary.startsWith('[off-route]')).toBe(true);
  expect(outcome.event.urgency).toBe('low');
  expect(outcome.event.affectsWorldState).toBe(false);
});

test('malformed model output returns 422 with low-confidence fallback', async () => {
  __setAnthropicClient(fakeAnthropic({ observationCategory: 'NOPE', summary: 42 }));
  const outcome = await parsePhotoToMissionEvent({
    imageBytes: TINY_JPEG,
    mimeType: 'image/jpeg',
  });
  expect(outcome.ok).toBe(false);
  if (outcome.ok) throw new Error();
  expect(outcome.status).toBe(422);
  expect(outcome.lowConfidenceEvent.confidence).toBeLessThanOrEqual(0.2);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test vision-parser`
Expected: FAIL with module-not-found.

- [ ] **Step 3: Create three files**

`frontend/lib/mission/vision-parser-schema.ts` — copy verbatim from the AI engineer's design in `Task 1` of the vision parser section above (`MISSION_EVENT_TOOL` constant + `validateVisionParseResult` function + helpers).

`frontend/lib/mission/vision-parser-prompt.ts` — copy verbatim the `VISION_SYSTEM_PROMPT` constant + `buildUserPrompt` function from the design above.

`frontend/lib/mission/vision-parser.ts` — copy verbatim the wrapper from the design above (`parsePhotoToMissionEvent`, `__setAnthropicClient`, `mapToMissionEvent`, `placeholderEvent`, `withTimeout`, `isTimeout`).

The full code for all three files is in the agent's design output earlier in this conversation. Paste them as-is.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test vision-parser`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/mission/vision-parser*.ts frontend/__tests__/lib/mission/vision-parser.test.ts
git commit -m "feat(vision): Anthropic-backed photo → MissionEvent parser"
```

---

## Task 10: Create `POST /api/mission/ingest/photo` endpoint

**Files:**
- Create: `frontend/app/api/mission/ingest/photo/route.ts`
- Create: `frontend/__tests__/api/mission/ingest-photo.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/__tests__/api/mission/ingest-photo.test.ts`:

```ts
import { POST } from '@/app/api/mission/ingest/photo/route';
import { __setAnthropicClient } from '@/lib/mission/vision-parser';

const fetchMock = jest.fn();
global.fetch = fetchMock as any;

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ accepted: true, id: 'x', deduped: false }) });
});

afterEach(() => __setAnthropicClient(null));

function fakeAnthropic(input: any) {
  return {
    messages: {
      create: jest.fn().mockResolvedValue({
        content: [{ type: 'tool_use', name: 'emit_mission_event', id: 't', input }],
        stop_reason: 'tool_use',
      }),
    },
  } as any;
}

function makeReq(form: FormData) {
  return new Request('http://localhost/api/mission/ingest/photo', {
    method: 'POST',
    body: form,
  }) as any;
}

test('returns 200 with parsed MissionEvent and forwards to /api/mission/ingest', async () => {
  process.env.MISSION_INGEST_URL = 'http://localhost/api/mission/ingest';
  __setAnthropicClient(
    fakeAnthropic({
      observationCategory: 'traffic',
      summary: 'Heavy 101 congestion at Cesar Chavez.',
      confidence: 0.75,
      urgency: 'medium',
      riskAssessment: 'Adds 12min northbound.',
      vehicles: { count: 30, descriptions: [] },
      peopleEstimate: { count: 0, bucket: 'none' },
      infrastructureState: 'normal',
      locationGuess: {
        description: '101 N near Cesar Chavez',
        landmarks: [], streets: ['US-101'],
        isSanFrancisco: true, confidence: 0.8,
      },
      notableEntities: ['brake lights'],
    }),
  );

  const form = new FormData();
  form.append('image', new File([new Uint8Array([0xff, 0xd8])], 'c.jpg', { type: 'image/jpeg' }));
  form.append('submitter_id', 'alvarez');

  const res = await POST(makeReq(form));
  expect(res.status).toBe(200);
  const body = await res.json();
  expect(body.event.eventType).toBe('traffic');

  // forwarded to ingest endpoint
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('http://localhost/api/mission/ingest');
  expect(JSON.parse(init.body).event.eventType).toBe('traffic');
});

test('returns 400 for missing image', async () => {
  const res = await POST(makeReq(new FormData()));
  expect(res.status).toBe(400);
});

test('returns 400 for unsupported mime', async () => {
  const form = new FormData();
  form.append('image', new File(['x'], 'a.txt', { type: 'text/plain' }));
  const res = await POST(makeReq(form));
  expect(res.status).toBe(400);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test ingest-photo`
Expected: FAIL with module-not-found.

- [ ] **Step 3: Create `frontend/app/api/mission/ingest/photo/route.ts`**

```ts
import { NextResponse } from 'next/server';
import { parsePhotoToMissionEvent } from '@/lib/mission/vision-parser';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MAX_BYTES = 8 * 1024 * 1024;
const ALLOWED = new Set(['image/jpeg', 'image/png', 'image/webp']);

async function forwardToIngest(event: unknown): Promise<void> {
  const url = process.env.MISSION_INGEST_URL ?? 'http://localhost:3000/api/mission/ingest';
  const secret = process.env.MISSION_INGEST_SECRET;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (secret) headers.Authorization = `Bearer ${secret}`;
  await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({ event }),
  });
}

export async function POST(req: Request): Promise<NextResponse> {
  let form: FormData;
  try { form = await req.formData(); }
  catch { return NextResponse.json({ error: 'invalid_multipart' }, { status: 400 }); }

  const file = form.get('image');
  if (!(file instanceof File)) {
    return NextResponse.json({ error: 'missing_image' }, { status: 400 });
  }
  if (!ALLOWED.has(file.type)) {
    return NextResponse.json({ error: 'unsupported_mime', detail: file.type }, { status: 400 });
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json({ error: 'image_too_large' }, { status: 400 });
  }

  const buf = new Uint8Array(await file.arrayBuffer());
  const outcome = await parsePhotoToMissionEvent({
    imageBytes: buf,
    mimeType: file.type as 'image/jpeg' | 'image/png' | 'image/webp',
    locationHint: (form.get('location_hint') as string | null) ?? undefined,
    submitterId: (form.get('submitter_id') as string | null) ?? undefined,
  });

  if (outcome.ok) {
    try { await forwardToIngest(outcome.event); }
    catch (err) { console.error('[ingest/photo] forward failed', err); }
    return NextResponse.json({ event: outcome.event }, { status: 200 });
  }
  return NextResponse.json(
    { error: outcome.error, lowConfidenceEvent: outcome.lowConfidenceEvent },
    { status: outcome.status },
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test ingest-photo`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/api/mission/ingest/photo/route.ts frontend/__tests__/api/mission/ingest-photo.test.ts
git commit -m "feat(api): POST /api/mission/ingest/photo — vision → MissionEvent"
```

---

## Task 11: Add photo upload UI to `/mobile`

**Files:**
- Modify: `frontend/app/mobile/page.tsx`

- [ ] **Step 1: Add a photo-upload control to the mobile page**

Inside the connected-room view, add a button below the Connect button:

```tsx
<input
  type="file"
  accept="image/jpeg,image/png,image/webp"
  capture="environment"
  className="hidden"
  id="photo-input"
  onChange={async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append('image', file);
    form.append('submitter_id', 'mobile-user');
    setUploadStatus('uploading...');
    try {
      const res = await fetch('/api/mission/ingest/photo', { method: 'POST', body: form });
      if (res.ok) {
        const body = await res.json();
        setUploadStatus(`Submitted: ${body.event.summary}`);
      } else {
        setUploadStatus('Submit failed.');
      }
    } catch {
      setUploadStatus('Submit failed.');
    }
    e.target.value = '';
  }}
/>
<label
  htmlFor="photo-input"
  className="block w-full rounded-lg border border-white/20 bg-black/30 py-3 text-center text-sm font-medium text-white"
>
  Submit field photo
</label>
{uploadStatus && <p className="mt-2 text-xs opacity-80">{uploadStatus}</p>}
```

Add `const [uploadStatus, setUploadStatus] = useState<string | null>(null);` near other state.

- [ ] **Step 2: Smoke test manually**

Run `pnpm dev`. Open `http://localhost:3000/mobile` on a phone. Connect. Submit any photo. Confirm:
- Status text changes to "Submitted: …"
- Browser network tab shows POST to `/api/mission/ingest/photo` returning 200
- Console shows the agent's `_event_log` grew (add a temporary `logger.info("event log: %s", self._event_log[-1])` in `_handle_event_payload` if you need confirmation, then remove)

- [ ] **Step 3: Commit**

```bash
git add frontend/app/mobile/page.tsx
git commit -m "feat(mobile): add field-photo capture UI"
```

---

# Phase 5: Ambient Mode

## Task 12: Create `agent-py/src/ambient.py` module

**Files:**
- Create: `agent-py/src/ambient.py`
- Create: `agent-py/tests/test_ambient.py`

- [ ] **Step 1: Write the failing tests**

Create `agent-py/tests/test_ambient.py`:

```python
"""Tests for the ambient mode gate."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.ambient import Action, AmbientHandler, AntiChatter, run_gate


def make_event(**overrides):
    base = {
        "id": "evt-test",
        "missionId": "operation-checkpoint-echo",
        "timestamp": "2026-06-06T13:00:00Z",
        "source": {"type": "system", "name": "sf_311", "reliability": "medium"},
        "eventType": "incident",
        "summary": "test event",
        "entities": [],
        "confidence": 0.7,
        "urgency": "medium",
        "affectsWorldState": True,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_gate_drops_low_urgency_noise():
    """Rule gate drops urgency=low with no LLM call."""
    event = make_event(eventType="weather", summary="Light breeze", confidence=0.2, urgency="low")
    decision = await run_gate(event, world_state_summary="", conversation_context="")
    assert decision.action == Action.DROP


@pytest.mark.asyncio
async def test_gate_speaks_for_high_urgency_on_route():
    """Rule gate fires SPEAK on high urgency + confidence>=0.5."""
    event = make_event(
        eventType="road_closure",
        summary="Bay Bridge eastbound closed after crash at toll plaza",
        confidence=0.9,
        urgency="high",
    )
    decision = await run_gate(event, world_state_summary="", conversation_context="")
    assert decision.action == Action.SPEAK
    assert decision.severity_score >= 0.85


@pytest.mark.asyncio
async def test_cooldown_suppresses_second_speak():
    """Two same-type SPEAK events within 30s — second is suppressed."""
    session = MagicMock()
    session.generate_reply = AsyncMock()
    handler = AmbientHandler(session=session, assistant=MagicMock())

    e1 = make_event(id="evt-1", eventType="protest", summary="Crowd at Howard", confidence=0.8, urgency="high")
    e2 = make_event(id="evt-2", eventType="protest", summary="Crowd at Mission", confidence=0.85, urgency="high")
    await handler.on_event_received(e1)
    await handler.on_event_received(e2)
    assert session.generate_reply.call_count == 1


def test_anti_chatter_dedup_blocks_repeat_summary():
    ac = AntiChatter()
    e = make_event(summary="Bay Bridge eastbound closed after crash at toll plaza")
    ac.mark_spoken(e)
    e2 = make_event(id="other", summary="Bay Bridge eastbound closed after crash at toll plaza")
    assert ac.is_duplicate(e2) is True
```

Note: requires `pytest-asyncio`. Add to `agent-py/pyproject.toml` dev deps:
```toml
[dependency-groups]
dev = [..., "pytest-asyncio>=0.23"]
```
Add `asyncio_mode = "auto"` to `[tool.pytest.ini_options]` in pyproject.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-py && uv run pytest tests/test_ambient.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ambient'`.

- [ ] **Step 3: Create `agent-py/src/ambient.py`**

Paste the full ambient module from the prompt-engineer's design output. Key components:
- `class Action(Enum)`: SPEAK, STASH, DROP
- `@dataclass GateDecision`: action, severity_score, reason, suggested_utterance
- `class AntiChatter`: per-type cooldown map, global min gap, SHA-256 dedup, priority queue
- `async def run_gate(event, world_state_summary, conversation_context) -> GateDecision`: rule gate first, calls `_call_llm_for_classification` only for borderline cases
- `CLASSIFIER_SYSTEM_PROMPT` constant (from design above)
- `CLASSIFIER_USER_TEMPLATE` constant
- `class AmbientHandler`: wires `handle_data_received` to `on_event_received` to `_do_speak`

The exact file content is in the prompt-engineer's design earlier in this conversation. Paste verbatim.

Key constants at the top:
```python
GLOBAL_MIN_GAP_S = 8.0
COOLDOWNS_S = {
    "road_closure": 30.0, "incident": 30.0, "route_change": 30.0,
    "protest": 45.0, "crowd": 60.0, "weather": 90.0, "vip_movement": 20.0,
}
SPEAK_RULE_URGENCY = {"high", "critical"}
SPEAK_RULE_MIN_CONFIDENCE = 0.5
DROP_RULE_MAX_CONFIDENCE = 0.3
DROP_RULE_URGENCY = {"low"}
LLM_CLASSIFIER_MODEL = "openai/gpt-4o-mini"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-py && uv run pytest tests/test_ambient.py -v`
Expected: PASS (all four tests).

- [ ] **Step 5: Commit**

```bash
git add agent-py/src/ambient.py agent-py/tests/test_ambient.py agent-py/pyproject.toml
git commit -m "feat(agent): ambient mode gate (hybrid rule + LLM, anti-chatter)"
```

---

## Task 13: Wire ambient handler into agent entrypoint

**Files:**
- Modify: `agent-py/src/agent.py`

- [ ] **Step 1: Replace the `_on_data` handler from Task 8 with the ambient-aware version**

In `my_agent`, replace the data handler wired in Task 8 with:

```python
    from .ambient import AmbientHandler

    assistant_instance = Assistant(room=ctx.room, user_id=user_id)
    ambient = AmbientHandler(session=session, assistant=assistant_instance)

    await session.start(
        agent=assistant_instance,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )

    await ctx.connect()

    # Subscribe to mission_event data frames (from /api/mission/ingest)
    ctx.room.on("data_received", ambient.handle_data_received)
```

(Note: this replaces the existing `assistant_ref` indirection — pass the instance directly.)

- [ ] **Step 2: Smoke test the end-to-end loop**

Run `pnpm dev`. In another shell:
```bash
curl -X POST http://localhost:3000/api/mission/ingest \
  -H 'Content-Type: application/json' \
  -d '{"event":{"id":"smoke-1","missionId":"operation-checkpoint-echo","timestamp":"2026-06-06T13:00:00Z","source":{"type":"system","name":"smoke","reliability":"high"},"eventType":"road_closure","summary":"Bay Bridge eastbound closed after multi-vehicle crash at toll plaza","entities":[],"confidence":0.9,"urgency":"high","affectsWorldState":true}}'
```

Connect to `/mobile` first. Expected: agent speaks proactively about the Bay Bridge closure within ~2s of the curl POST.

- [ ] **Step 3: Commit**

```bash
git add agent-py/src/agent.py
git commit -m "feat(agent): wire ambient handler to room data channel"
```

---

# Phase 6: External SF Feeds

## Task 14: Create feed normalizers

**Files:**
- Create: `agent-py/scripts/__init__.py` (empty)
- Create: `agent-py/scripts/feeds/__init__.py` (empty)
- Create: `agent-py/scripts/feeds/sf311.py`
- Create: `agent-py/scripts/feeds/sf511.py`
- Create: `agent-py/scripts/feeds/nws_weather.py`
- Create: `agent-py/scripts/worker_config.py`
- Create: `agent-py/tests/test_feed_worker.py`

- [ ] **Step 1: Write failing tests**

Create `agent-py/tests/test_feed_worker.py`. Copy the 7 test cases verbatim from the data-engineer's design output above. Adjust path: `sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))`.

- [ ] **Step 2: Run test to verify they fail**

Run: `cd agent-py && uv run pytest tests/test_feed_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'feeds'`.

- [ ] **Step 3: Create empty `__init__.py` files**

Run:
```bash
touch agent-py/scripts/__init__.py agent-py/scripts/feeds/__init__.py
```

- [ ] **Step 4: Create `agent-py/scripts/worker_config.py`**

```python
"""Constants for the feed worker."""
from __future__ import annotations

# SFO terminal coords: 37.6213, -122.3790
# Moscone Center: 37.7835, -122.3999
CORRIDOR_LAT_MIN = 37.615
CORRIDOR_LAT_MAX = 37.790
CORRIDOR_LON_MIN = -122.500
CORRIDOR_LON_MAX = -122.385

MISSION_ID = "operation-checkpoint-echo"

CADENCES_S = {
    "sf311": 120,        # 2 min
    "sf511": 30,         # 30 sec
    "nws_weather": 300,  # 5 min
}

MAX_LIVEKIT_PUBLISHES_PER_CYCLE = 10
USER_AGENT = "MissionBayWorker/1.0 (aryan.aladar@gmail.com)"
```

- [ ] **Step 5: Create the three normalizer modules**

Copy the full `normalize_sf311`, `normalize_511_alert`, and `normalize_nws_period` functions from the data-engineer's design output above into the respective files. Also add `async def fetch_sf311(session)`, `async def fetch_511_alerts(session)`, `async def fetch_nws_forecast(session)` skeletons:

`agent-py/scripts/feeds/sf311.py` — copy full module from design. Add fetcher:
```python
import os
from datetime import datetime, timedelta, timezone

async def fetch_sf311(session) -> list[dict]:
    """Fetch recent SF 311 cases within the corridor bbox."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(timespec="seconds")
    where = (
        f"opened >= '{since}' AND "
        f"latitude BETWEEN {CORRIDOR_LAT_MIN} AND {CORRIDOR_LAT_MAX} AND "
        f"longitude BETWEEN {CORRIDOR_LON_MIN} AND {CORRIDOR_LON_MAX}"
    )
    url = "https://data.sfgov.org/resource/vw6y-z8j6.json"
    params = {"$where": where, "$order": "opened DESC", "$limit": 50}
    headers = {}
    token = os.getenv("SF311_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token
    async with session.get(url, params=params, headers=headers) as resp:
        resp.raise_for_status()
        return await resp.json()
```

`agent-py/scripts/feeds/sf511.py` — copy from design. Add fetcher:
```python
import os

async def fetch_511_alerts(session) -> list[dict]:
    """Fetch active SF Bay transit service alerts (SIRI JSON)."""
    key = os.getenv("API_511_KEY")
    if not key:
        return []  # silently skip if not configured
    url = "https://api.511.org/transit/servicealerts"
    params = {"agency": "SF", "api_key": key, "Format": "JSON"}
    async with session.get(url, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    # Unwrap SIRI envelope
    try:
        deliveries = data["Siri"]["ServiceDelivery"]["SituationExchangeDelivery"]
        if isinstance(deliveries, dict):
            deliveries = [deliveries]
        situations = []
        for d in deliveries:
            sits = d.get("Situations", {}).get("PtSituationElement", [])
            if isinstance(sits, dict):
                sits = [sits]
            situations.extend(sits)
        return situations
    except (KeyError, TypeError):
        return []
```

`agent-py/scripts/feeds/nws_weather.py` — copy from design. Add fetcher:
```python
NWS_FORECAST_URL = "https://api.weather.gov/gridpoints/MTR/84,127/forecast/hourly"

async def fetch_nws_forecast(session) -> list[dict]:
    async with session.get(NWS_FORECAST_URL) as resp:
        resp.raise_for_status()
        data = await resp.json()
    return data.get("properties", {}).get("periods", [])
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd agent-py && uv run pytest tests/test_feed_worker.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 7: Commit**

```bash
git add agent-py/scripts agent-py/tests/test_feed_worker.py
git commit -m "feat(feeds): SF 311, 511 transit, NWS weather normalizers"
```

---

## Task 15: Create worker main loop

**Files:**
- Create: `agent-py/scripts/worker.py`
- Modify: `package.json`

- [ ] **Step 1: Create `agent-py/scripts/worker.py`**

```python
"""Mission Bay feed worker.

Polls SF 311, SF 511 transit, and NWS weather. Normalizes to MissionEvent.
Dedups in-memory. Posts each new event to /api/mission/ingest as the
single ingress chokepoint.

Run from repo root via `pnpm dev:feeds` (concurrently target).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

from feeds.sf311 import fetch_sf311, normalize_sf311
from feeds.sf511 import fetch_511_alerts, normalize_511_alert
from feeds.nws_weather import fetch_nws_forecast, normalize_nws_period
from worker_config import CADENCES_S, USER_AGENT

ENV_PATH = Path(__file__).resolve().parent.parent / ".env.local"
load_dotenv(ENV_PATH)

logger = logging.getLogger("feed_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

INGEST_URL = os.getenv("MISSION_INGEST_URL", "http://localhost:3000/api/mission/ingest")
INGEST_SECRET = os.getenv("MISSION_INGEST_SECRET")

seen: set[str] = set()


async def post_event_to_ingest(session: aiohttp.ClientSession, event: dict) -> None:
    """POST a normalized event to the single ingest chokepoint."""
    headers = {"Content-Type": "application/json"}
    if INGEST_SECRET:
        headers["Authorization"] = f"Bearer {INGEST_SECRET}"
    try:
        async with session.post(INGEST_URL, json={"event": event}, headers=headers, timeout=5) as resp:
            if resp.status >= 400:
                body = await resp.text()
                logger.warning("Ingest rejected event %s: HTTP %s — %s", event.get("id"), resp.status, body[:200])
    except asyncio.TimeoutError:
        logger.warning("Ingest timed out for event %s", event.get("id"))
    except Exception:
        logger.exception("Ingest POST failed for event %s", event.get("id"))


async def run_poll(name: str, fetch_fn, normalize_fn, session: aiohttp.ClientSession) -> None:
    try:
        raw_items = await fetch_fn(session)
    except Exception:
        logger.exception("Fetch failed for %s", name)
        return

    new_events: list[dict] = []
    for raw in raw_items:
        event = normalize_fn(raw)
        if event is None:
            continue
        if event["id"] in seen:
            continue
        seen.add(event["id"])
        new_events.append(event)

    if not new_events:
        return

    logger.info("%s: %d new events", name, len(new_events))
    for ev in new_events:
        await post_event_to_ingest(session, ev)


async def feed_loop(name: str, fetch_fn, normalize_fn, cadence: int) -> None:
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        while True:
            await run_poll(name, fetch_fn, normalize_fn, session)
            await asyncio.sleep(cadence)


async def main() -> None:
    logger.info("Mission Bay feed worker starting. Ingest URL: %s", INGEST_URL)
    await asyncio.gather(
        feed_loop("sf311", fetch_sf311, normalize_sf311, CADENCES_S["sf311"]),
        feed_loop("sf511", fetch_511_alerts, normalize_511_alert, CADENCES_S["sf511"]),
        feed_loop("nws_weather", fetch_nws_forecast, normalize_nws_period, CADENCES_S["nws_weather"]),
    )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Update root `package.json`**

In `scripts`, add:
```json
"dev:feeds": "uv --directory agent-py run scripts/worker.py",
```

Update `dev`:
```json
"dev": "concurrently -n agent-py,frontend,feeds -c cyan,magenta,yellow \"pnpm dev:agent-py\" \"pnpm dev:frontend\" \"pnpm dev:feeds\"",
```

- [ ] **Step 3: Smoke test the worker**

Run `pnpm dev`. In another shell:
```bash
curl -sS http://localhost:3000/api/mission/state
```
Watch the `[feeds]` log lines. After ~30 seconds you should see lines like:
```
[feeds] feed_worker INFO sf511: 2 new events
```
And confirm `/api/mission/state` (or the agent's event log via console) reflects new entries.

- [ ] **Step 4: Commit**

```bash
git add agent-py/scripts/worker.py package.json
git commit -m "feat(feeds): worker main loop, wire to pnpm dev"
```

---

# Phase 7: Verification

## Task 16: End-to-end smoke test playbook

**Files:**
- Modify: `DEMO.md`

- [ ] **Step 1: Update `DEMO.md`**

Replace the body with the new flow:

```markdown
# Mission Bay live ingestion demo

## What this is

Mission Bay is a real-time SF transit copilot. Today's scenario: a VIP delegation moves from SFO to Moscone Center in 90 minutes. The agent ambiently surfaces traffic, transit, weather, protest, and incident events as they happen.

## Setup

1. `pnpm setup`
2. Fill `agent-py/.env.local` and `frontend/.env.local` per `.env.example`. Required:
   - LiveKit (URL, key, secret)
   - Moss (project ID, project key)
   - Anthropic API key (vision parser)
   - 511.org API key (free, https://511.org/open-data/token) — optional; worker skips 511 if absent
   - `MISSION_INGEST_SECRET` — pick any random string, set in both .env.local files
3. `pnpm agent:py:download-files` — pulls VAD + turn detector models
4. `pnpm moss:index` — creates `knowledge`, `memory`, `events` Moss indexes
5. `pnpm dev` — runs agent + frontend + feed worker

## Test 1: Photo upload

1. Open `http://<your-laptop-ip>:3000/mobile` on a phone.
2. Tap **Connect to Mission Bay**.
3. Tap **Submit field photo** and pick any SF street photo (or any photo).
4. Within ~3 seconds:
   - The mobile UI shows the parsed summary
   - The voice agent speaks proactively about the photo if it's material (e.g. protest, blocked road)
   - If non-material, the event is stashed and you can ask "what's new?"

## Test 2: Manual ingest (no photo)

Confirm the loop without the vision model:

```bash
curl -X POST http://localhost:3000/api/mission/ingest \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MISSION_INGEST_SECRET" \
  -d @- <<'JSON'
{
  "event": {
    "id": "manual-1",
    "missionId": "operation-checkpoint-echo",
    "timestamp": "2026-06-06T13:30:00Z",
    "source": {"type": "manual_note", "name": "operator", "reliability": "high"},
    "eventType": "road_closure",
    "summary": "Bay Bridge eastbound fully closed after multi-vehicle crash at toll plaza",
    "entities": [],
    "confidence": 0.92,
    "urgency": "high",
    "affectsWorldState": true
  }
}
JSON
```

Connect on `/mobile` first. Expected: agent speaks "Heads up, Bay Bridge eastbound is closed…" within 2s.

## Test 3: External feeds

After `pnpm dev`, watch the `[feeds]` lines. Within 30s you should see at least:
- `sf511: N new events` (if API_511_KEY is set; otherwise skipped)
- `sf311: N new events` (after 2 min if any qualifying cases)
- `nws_weather: N new events` (if conditions are significant; often 0 on calm days)

Ask the agent: "What just came in?" — it should call `search_dynamic_events` and summarize.

## Test 4: No-hallucination guard

Before any events arrive, ask: "Is Route A blocked?"
Expected: Mission Bay says the original plan marks Route A as low risk, no live report has contradicted that yet.

After the curl from Test 2: "Is Route A blocked?"
Expected: Mission Bay cites the Bay Bridge closure and proposes Route C.
```

- [ ] **Step 2: Commit**

```bash
git add DEMO.md
git commit -m "docs(demo): live ingestion + ambient mode playbook"
```

---

## Task 17: Final cleanup — remove `/tmp` state path code

**Files:**
- Modify: `frontend/app/api/mission/state/route.ts` (keep as read-only dashboard view, no writes)
- Modify: `frontend/lib/mission/drone-parser.ts` (already deprecated in Task 9; verify deletion is safe)

- [ ] **Step 1: Audit remaining `/tmp` and `MISSION_STATE_PATH` references**

Run:
```bash
grep -rn "MISSION_STATE_PATH\|mission-bay-world-state" agent-py/ frontend/ docs/ 2>/dev/null
```
Expected: only mentions in DEMO.md history and the dashboard read path (which is fine — dashboard can still read the file for display, but nothing writes it on the agent path anymore).

- [ ] **Step 2: Delete the obsolete frontend reducer wiring through the dashboard if it dual-writes**

Check `frontend/app/api/mission/state/route.ts`. If it still has POST handlers that write the file, comment them out and add a note: this file is a read-only view. Real events flow through `/api/mission/ingest`.

- [ ] **Step 3: Run full test suite**

```bash
cd frontend && pnpm test
cd agent-py && uv run pytest
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove /tmp file write path; ingest is the single chokepoint"
```

---

# Self-Review

**Spec coverage:**
- ✅ SF reskin → Task 4
- ✅ Photo upload → vision parser → MissionEvent → Tasks 9, 10, 11
- ✅ Events in Moss (replace /tmp) → Tasks 5, 6, 7, 8, 17
- ✅ LiveKit data-channel push → Task 7 (push), Task 8 (receive)
- ✅ Ambient proactive speech with severity gating → Tasks 12, 13
- ✅ External feeds (SF 311, 511, NWS) → Tasks 14, 15

**Open verification items requiring live confirmation before demo:**

1. **Moss REST API contract** (Task 6) — the `mossAddDocs` wrapper assumes `POST /v1/indexes/{name}/add_docs` with `X-Project-Id`/`X-Project-Key` headers. Confirm at https://docs.moss.dev/docs/rest-api. If wrong, switch to the FastAPI sidecar fallback noted in Task 6-alt.
2. **LiveKit `data_received` callback signature** (Task 8) — confirm `(packet,)` vs `(data, participant, kind, topic)` on `livekit-agents==1.5.16`. Adjust `_on_data` accordingly.
3. **SF 311 Socrata column names** (Task 14) — hit `https://data.sfgov.org/resource/vw6y-z8j6.json?$select=*&$limit=1` to see live columns. The normalizer assumes `latitude`/`longitude` for filtering; if columns are `lat`/`long`, swap.
4. **511 SIRI JSON shape** (Task 14) — fetch one live alert and print before wiring. The `SituationExchangeDelivery` nesting varies.
5. **Anthropic SDK on Next 15 Edge vs Node runtime** — vision route uses `runtime = 'nodejs'`. Confirm `@anthropic-ai/sdk` works there (it does at time of writing).
6. **NWS gridpoint stability** — `MTR/84,127` is downtown SF. Verify once: `curl https://api.weather.gov/points/37.7749,-122.4194 | jq .properties.forecastHourly`.

**Placeholder scan:** all code blocks contain runnable code. No `# TODO` or `// TBD` placeholders.

**Type consistency:**
- `MissionEvent.eventType` union widened in Task 1 — Zod schema in Task 7 matches.
- `source.type` union includes `mobile_capture` — vision parser uses it; Zod schema accepts it.
- Function names: `mossAddDocs`, `parsePhotoToMissionEvent`, `_handle_event_payload`, `AmbientHandler.on_event_received`, `run_gate`, `normalize_sf311`, `normalize_511_alert`, `normalize_nws_period` are referenced consistently across all tasks.

**Known divergences from individual subagent designs:**
- Feed worker writes to `/api/mission/ingest` instead of directly to Moss + LiveKit (single chokepoint).
- Events index is `events`, not `memory` with metadata filter (clean isolation).
- Ingest endpoint adds Zod validation + dedup + reducer step + auth header all in one route — the central design pattern.

---

# Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-06-mission-bay-live-ingestion.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Best for this plan because Phase 0 → Phase 1 → Phase 2 are sequential and each later phase depends on the previous one being green.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
