import { NextResponse } from 'next/server';
import { DataPacket_Kind, RoomServiceClient } from 'livekit-server-sdk';
import { createHash } from 'node:crypto';
import { z } from 'zod';
import { mossAddDocs } from '@/lib/moss/moss-http';
import type { MissionEvent } from '@/lib/mission/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const revalidate = 0;

const SourceSchema = z.object({
  type: z.enum([
    'comms',
    'gps',
    'drone_image',
    'mobile_capture',
    'command_update',
    'manual_note',
    'system',
  ]),
  name: z.string(),
  reliability: z.enum(['low', 'medium', 'high']),
});

const EntitySchema = z.object({
  id: z.string(),
  type: z.enum(['team', 'person', 'route', 'sector', 'landmark', 'vehicle', 'unknown']),
  label: z.string(),
});

const LocationSchema = z
  .object({
    sectorId: z.string().optional(),
    landmarkId: z.string().optional(),
    coordinates: z.object({ x: z.number(), y: z.number() }).optional(),
    description: z.string().optional(),
  })
  .optional();

const RawInputSchema = z
  .object({
    modality: z.enum(['text', 'audio', 'image', 'video_frame', 'gps']),
    contentRef: z.string().optional(),
    transcript: z.string().optional(),
  })
  .optional();

const MissionEventSchema = z.object({
  id: z.string(),
  missionId: z.string(),
  timestamp: z.string(),
  source: SourceSchema,
  eventType: z.enum([
    'position_update',
    'route_status_update',
    'visual_observation',
    'traffic',
    'crowd',
    'weather',
    'infrastructure',
    'protest',
    'incident',
    'command_update',
    'status_report',
    'risk_detected',
    'objective_update',
    'equipment_update',
    'transit_delay',
    'comms',
    'conflict',
    'unknown',
  ]),
  summary: z.string().min(1).max(2000),
  entities: z.array(EntitySchema),
  location: LocationSchema,
  confidence: z.number().min(0).max(1),
  urgency: z.enum(['low', 'medium', 'high', 'critical']),
  rawInput: RawInputSchema,
  extractedFields: z.record(z.string(), z.unknown()).optional(),
  affectsWorldState: z.boolean(),
});

const IngestRequestSchema = z.object({ event: MissionEventSchema });

const DEDUP_WINDOW_MS = 5 * 60 * 1000;
const _dedupCache = new Map<string, number>();

function evictStaleDedup(): void {
  const cutoff = Date.now() - DEDUP_WINDOW_MS;
  for (const [k, ts] of _dedupCache) if (ts < cutoff) _dedupCache.delete(k);
}

function dedupKey(event: MissionEvent): string {
  const minuteBucket = event.timestamp.slice(0, 16);
  const raw = `${event.source.name}:${event.id}:${minuteBucket}:${event.summary.slice(0, 120)}`;
  return createHash('sha256').update(raw).digest('hex').slice(0, 16);
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
  const encoded = new TextEncoder().encode(
    JSON.stringify({ type: 'mission_event', event })
  );

  try {
    await svc.sendData(room, encoded, DataPacket_Kind.RELIABLE, {
      topic: 'mission_event',
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    // 404 just means the room hasn't been created yet — soldiers haven't
    // connected, so there's nobody to push to. The event is still in Moss
    // and soldiers will pick it up via search_dynamic_events when they
    // connect. Do NOT pre-create the room here: doing so creates it without
    // the agent dispatch metadata from the soldier's token, which prevents
    // the agent from joining when soldiers later connect.
    if (msg.toLowerCase().includes('not found') || msg.includes('404')) {
      return;
    }
    throw err;
  }
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
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }

  const parsed = IngestRequestSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: 'Validation failed', details: parsed.error.flatten() },
      { status: 422 }
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
    await mossAddDocs(process.env.MOSS_EVENTS_INDEX_NAME ?? 'events', [
      buildMossDoc(event),
    ]);
  } catch (err) {
    console.error('[ingest] Moss write failed:', err);
  }

  try {
    await pushToLiveKitRoom(event);
  } catch (err) {
    console.error('[ingest] LiveKit push failed:', err);
  }

  return NextResponse.json({ accepted: true, id: event.id, deduped: false });
}

export async function GET(): Promise<NextResponse> {
  return NextResponse.json({
    ok: true,
    info: 'POST a MissionEvent here. See docs/superpowers/plans/ for schema.',
    indexName: process.env.MOSS_EVENTS_INDEX_NAME ?? 'events',
  });
}
