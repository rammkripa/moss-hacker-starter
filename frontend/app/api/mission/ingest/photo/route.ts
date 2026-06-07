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
  try {
    form = await req.formData();
  } catch {
    return NextResponse.json({ error: 'invalid_multipart' }, { status: 400 });
  }

  const file = form.get('image');
  if (!(file instanceof File)) {
    return NextResponse.json({ error: 'missing_image' }, { status: 400 });
  }
  if (!ALLOWED.has(file.type)) {
    return NextResponse.json(
      { error: 'unsupported_mime', detail: file.type },
      { status: 400 }
    );
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
    try {
      await forwardToIngest(outcome.event);
    } catch (err) {
      console.error('[ingest/photo] forward failed', err);
    }
    return NextResponse.json({ event: outcome.event }, { status: 200 });
  }

  return NextResponse.json(
    { error: outcome.error, lowConfidenceEvent: outcome.lowConfidenceEvent },
    { status: outcome.status }
  );
}
