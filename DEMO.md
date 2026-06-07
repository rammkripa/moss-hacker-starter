# Mission Bay demo guide

Mission Bay is a realtime mission-awareness copilot for **Operation Checkpoint Echo**. The laptop dashboard injects deterministic fake live events and derives world state. Phones open the mobile web app and talk to the LiveKit voice agent, which uses Moss mission context plus the shared world-state JSON file.

## Setup

### Required environment variables

The starter already uses these variables:

Frontend `frontend/.env.local`:

```dotenv
LIVEKIT_URL=wss://<project-subdomain>.livekit.cloud
LIVEKIT_API_KEY=<your_livekit_api_key>
LIVEKIT_API_SECRET=<your_livekit_api_secret>
AGENT_NAME=agent-py
LIVEKIT_ROOM_NAME=mission_bay_demo_room
MISSION_STATE_PATH=/tmp/mission-bay-world-state.json
```

Agent `agent-py/.env.local`:

```dotenv
LIVEKIT_URL=wss://<project-subdomain>.livekit.cloud
LIVEKIT_API_KEY=<your_livekit_api_key>
LIVEKIT_API_SECRET=<your_livekit_api_secret>
MOSS_PROJECT_ID=<your_moss_project_id>
MOSS_PROJECT_KEY=<your_moss_project_key>
MOSS_INDEX_NAME=knowledge
MOSS_MEMORY_INDEX_NAME=memory
MOSS_MODEL_ID=moss-minilm
MISSION_STATE_PATH=/tmp/mission-bay-world-state.json
```

`MISSION_STATE_PATH` must match in both files so `/dashboard` and the Python agent see the same derived world state. `LIVEKIT_ROOM_NAME` defaults to `mission_bay_demo_room` so two phones can join the same session.

### Install dependencies

```bash
pnpm setup
```

### Fill LiveKit credentials

If you use the LiveKit CLI flow from the starter:

```bash
lk app env -w agent-py
lk app env -w frontend
```

Then add Moss credentials to `agent-py/.env.local`.

### Index Mission Bay knowledge into Moss

```bash
pnpm moss:index
```

This indexes `agent-py/knowledge.json`, which now contains Mission Bay mission plan, terrain, route, team, constraint, and expected catch-up knowledge.

### Start the demo

Run the frontend and Python LiveKit agent together:

```bash
pnpm dev
```

Or run them in separate terminals:

```bash
pnpm dev:frontend
pnpm dev:agent-py
```

## Dashboard test

1. Open `http://localhost:3000/dashboard`.
2. Confirm the **Mission Bay** header appears.
3. Confirm static mission context appears for **Operation Checkpoint Echo**.
4. Confirm the initial world state appears: Alpha starts at C2, Route A is clear from the original plan, and Route C is unverified.
5. Click **Inject Next Event**.
6. Confirm the event appears in the live event stream.
7. Confirm world state updates.
8. Continue injecting events.
9. Confirm Route A becomes risky after Bravo reports possible bridge blockage and the drone event adds vehicle evidence.
10. Confirm Alpha moves toward B6, then close to B7.
11. Confirm the drone observation creates a known risk and an open verification question.
12. Click **Reset Mission** and confirm the stream clears and the baseline world state returns.

## Mobile voice test

1. Start the app on the local network if needed:

   ```bash
   pnpm --dir frontend dev --hostname 0.0.0.0
   ```

2. Open `http://<your-laptop-ip>:3000/mobile` on two phones.
3. Tap **Connect to Mission Bay** on each phone. The token route uses `mission_bay_demo_room` by default so both phones join the same LiveKit room/session.
4. Ask:
   - “What is the mission objective?”
   - “Who can handle comms?”
   - “Catch me up.”
   - “Why is Route A risky?”
   - “What should we verify next?”

Expected:

- The agent responds by voice as **Mission Bay**.
- The agent uses static Mission Bay context from Moss and current event/world-state evidence from `/tmp/mission-bay-world-state.json`.
- The agent does not invent facts and says when route status is unknown or unverified.

## No-hallucination test

Before injecting the route blockage event, ask:

> Is Route A blocked?

Expected: Mission Bay says the original plan marks Route A as planned or low-risk and no live report has yet confirmed blockage.

After injecting the Bravo route blockage event, ask again:

> Is Route A blocked?

Expected: Mission Bay says Bravo reported Route A may be blocked or risky near the bridge, with medium confidence and uncertainty. After the drone event, it should also mention the three-vehicle observation as additional evidence.

## Known first-pass limitation

The shared state path is intentionally simple for hackathon stability: `/dashboard` writes a local JSON file through a Next.js API route, and the Python agent reads that same file. This works well for a local laptop demo. For deployment, replace it with a small persistent store or server-side API and keep the same `WorldState` shape.
