import { NextResponse } from 'next/server';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { scriptedMissionEvents } from '@/lib/mission/fake-data';
import { createInitialWorldState } from '@/lib/mission/reducer';
import type { MissionEvent, WorldState } from '@/lib/mission/types';

const STATE_PATH = process.env.MISSION_STATE_PATH ?? '/tmp/mission-bay-world-state.json';
const INITIAL_STATE = createInitialWorldState('operation-checkpoint-echo');

type PersistedMissionState = {
  worldState: WorldState;
  injectedEvents: MissionEvent[];
};

async function readState(): Promise<PersistedMissionState> {
  try {
    const raw = await readFile(STATE_PATH, 'utf-8');
    return JSON.parse(raw) as PersistedMissionState;
  } catch {
    return { worldState: INITIAL_STATE, injectedEvents: [] };
  }
}

async function writeState(state: PersistedMissionState) {
  await mkdir(dirname(STATE_PATH), { recursive: true });
  await writeFile(STATE_PATH, JSON.stringify(state, null, 2), 'utf-8');
}

export async function GET() {
  const state = await readState();
  return NextResponse.json({ ...state, statePath: STATE_PATH });
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const action = body?.action;

  if (action === 'reset') {
    const state = { worldState: INITIAL_STATE, injectedEvents: [] };
    await writeState(state);
    return NextResponse.json({ ...state, statePath: STATE_PATH });
  }

  if (action === 'set') {
    const state = {
      worldState: body.worldState as WorldState,
      injectedEvents: (body.injectedEvents ?? []) as MissionEvent[],
    };
    await writeState(state);
    return NextResponse.json({ ...state, statePath: STATE_PATH });
  }

  if (action === 'seed-all') {
    const state = {
      worldState: body.worldState as WorldState,
      injectedEvents: scriptedMissionEvents,
    };
    await writeState(state);
    return NextResponse.json({ ...state, statePath: STATE_PATH });
  }

  return NextResponse.json({ error: 'Unknown mission state action.' }, { status: 400 });
}
