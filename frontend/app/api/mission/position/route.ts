import { NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// In-memory store of the latest position per soldier (callsign-keyed).
// Fine for hackathon demo: single Next.js process, single mission room.
type Position = {
  callsign: string;
  role: string;
  lat: number;
  lng: number;
  accuracy?: number;
  heading?: number | null;
  speed?: number | null;
  ts: string;
};

const _positions: Map<string, Position> = (() => {
  const g = globalThis as unknown as { __positionsStore?: Map<string, Position> };
  if (!g.__positionsStore) g.__positionsStore = new Map();
  return g.__positionsStore;
})();

async function forwardAsMissionEvent(p: Position): Promise<void> {
  // Push as a position_update MissionEvent through the standard ingest pipe
  // so the agent's ambient gate sees it like any other event.
  const url =
    process.env.MISSION_INGEST_URL ?? 'http://localhost:3000/api/mission/ingest';
  const secret = process.env.MISSION_INGEST_SECRET;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (secret) headers.Authorization = `Bearer ${secret}`;
  const event = {
    id: `gps-${p.callsign}-${Date.now()}`,
    missionId: 'operation-pier-glass',
    timestamp: p.ts,
    source: { type: 'gps', name: `gps:${p.callsign}`, reliability: 'high' },
    eventType: 'position_update',
    summary: `${p.callsign} GPS update: ${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}${
      p.accuracy ? ` (±${Math.round(p.accuracy)}m)` : ''
    }.`,
    entities: [],
    confidence: 0.9,
    urgency: 'low',
    location: {
      coordinates: { x: p.lng, y: p.lat },
      description: 'GPS-reported',
    },
    extractedFields: {
      callsign: p.callsign,
      role: p.role,
      accuracy_m: p.accuracy ?? null,
      heading_deg: p.heading ?? null,
      speed_mps: p.speed ?? null,
    },
    affectsWorldState: true,
  };
  try {
    await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({ event }),
      // GPS pings are frequent; don't block the mobile if Moss is slow.
      signal: AbortSignal.timeout(2000),
    });
  } catch {
    // Best-effort. Positions are still cached in-memory for dashboard polling.
  }
}

export async function POST(req: Request): Promise<NextResponse> {
  let body: Partial<Position>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'invalid_json' }, { status: 400 });
  }
  if (
    !body ||
    typeof body.callsign !== 'string' ||
    typeof body.lat !== 'number' ||
    typeof body.lng !== 'number'
  ) {
    return NextResponse.json({ error: 'invalid_payload' }, { status: 400 });
  }
  const p: Position = {
    callsign: body.callsign.trim(),
    role: typeof body.role === 'string' ? body.role : 'unknown',
    lat: body.lat,
    lng: body.lng,
    accuracy: typeof body.accuracy === 'number' ? body.accuracy : undefined,
    heading: typeof body.heading === 'number' ? body.heading : null,
    speed: typeof body.speed === 'number' ? body.speed : null,
    ts: typeof body.ts === 'string' ? body.ts : new Date().toISOString(),
  };
  _positions.set(p.callsign, p);
  // Forward to the ingest pipe without awaiting — mobile gets fast 200.
  void forwardAsMissionEvent(p);
  return NextResponse.json({ ok: true });
}

export async function GET(): Promise<NextResponse> {
  return NextResponse.json({
    positions: Array.from(_positions.values()),
  });
}
