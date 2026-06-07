# Mission Bay

Mission Bay is a realtime mission-awareness copilot. It converts static mission context plus live events into a shared derived world state that users can query by voice.

This repo is adapted from the LiveKit + Moss hacker starter and keeps the existing architecture:

- **Python LiveKit voice agent** in `agent-py/`
- **Next.js frontend** in `frontend/`
- **Moss semantic retrieval and memory** for grounded context/evidence
- **LiveKit Inference** for STT, LLM, and TTS

## Demo surfaces

- `http://localhost:3000/dashboard` — laptop mission dashboard for Operation Checkpoint Echo.
- `http://localhost:3000/mobile` — phone-friendly voice interface for Mission Bay.
- `http://localhost:3000/` — original LiveKit voice shell, rebranded for Mission Bay.

## What the first pass includes

- Mission Bay branding and voice-agent persona.
- Static mission context, terrain, routes, team roster, and constraints.
- Deterministic fake live event injection from the dashboard.
- A TypeScript `WorldState` reducer that updates positions, route status, risks, recent changes, and open questions.
- A mocked drone-image parser placeholder for future Unsiloed/Qwen integration.
- Mission-focused Moss knowledge in `agent-py/knowledge.json`.
- A simple shared-state path: the dashboard writes `/tmp/mission-bay-world-state.json`, and the Python agent reads it for current-world-state tools.

## Quick start

```bash
pnpm setup
pnpm moss:index
pnpm dev
```

You need LiveKit credentials in both `frontend/.env.local` and `agent-py/.env.local`, plus Moss credentials in `agent-py/.env.local`. See `DEMO.md` for exact environment variables and local test scripts.

## Local testing guide

See [`DEMO.md`](./DEMO.md) for:

- Setup and environment variables
- Moss mission knowledge indexing
- Dashboard test script
- Mobile two-phone voice test script
- No-hallucination route-status test
- Known first-pass limitations
