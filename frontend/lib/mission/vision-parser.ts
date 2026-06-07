import Anthropic from '@anthropic-ai/sdk';
import { nanoid } from 'nanoid';
import type { MissionEvent, VisionParseResult } from './types';
import { MISSION_EVENT_TOOL, validateVisionParseResult } from './vision-parser-schema';
import { VISION_SYSTEM_PROMPT, buildUserPrompt } from './vision-parser-prompt';

const VISION_MODEL = process.env.VISION_MODEL ?? 'claude-sonnet-4-6';
// Larger images (phone uploads can be 5-10MB) need more headroom for the
// upload-to-Anthropic + model inference round trip. Total worst-case ~45s.
const FIRST_ATTEMPT_TIMEOUT_MS = 25000;
const RETRY_TIMEOUT_MS = 20000;
const MISSION_ID = 'operation-pier-glass';

export type ParsePhotoInput = {
  imageBytes: Uint8Array;
  mimeType: 'image/jpeg' | 'image/png' | 'image/webp';
  locationHint?: string;
  submitterId?: string;
};

export type ParsePhotoOutcome =
  | { ok: true; event: MissionEvent; raw: VisionParseResult }
  | {
      ok: false;
      status: 422 | 502 | 504;
      error: string;
      lowConfidenceEvent: MissionEvent;
    };

let _client: Anthropic | null = null;

function client(): Anthropic {
  if (!_client) {
    _client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY ?? '' });
  }
  return _client;
}

/** Test seam — let unit tests inject a fake. */
export function __setAnthropicClient(c: Anthropic | null) {
  _client = c;
}

export async function parsePhotoToMissionEvent(
  input: ParsePhotoInput
): Promise<ParsePhotoOutcome> {
  const capturedAt = new Date().toISOString();
  const userPrompt = buildUserPrompt({
    submitterId: input.submitterId,
    locationHint: input.locationHint,
    capturedAt,
  });
  const base64 = Buffer.from(input.imageBytes).toString('base64');

  const attempt = async (timeoutMs: number) =>
    withTimeout(
      client().messages.create({
        model: VISION_MODEL,
        max_tokens: 1024,
        system: VISION_SYSTEM_PROMPT,
        tools: [MISSION_EVENT_TOOL as never],
        tool_choice: { type: 'tool', name: MISSION_EVENT_TOOL.name },
        messages: [
          {
            role: 'user',
            content: [
              {
                type: 'image',
                source: { type: 'base64', media_type: input.mimeType, data: base64 },
              },
              { type: 'text', text: userPrompt },
            ],
          },
        ],
      }),
      timeoutMs
    );

  let response: Awaited<ReturnType<Anthropic['messages']['create']>>;
  try {
    response = await attempt(FIRST_ATTEMPT_TIMEOUT_MS);
  } catch (e1) {
    try {
      response = await attempt(RETRY_TIMEOUT_MS);
    } catch (e2) {
      const status = isTimeout(e2) ? 504 : 502;
      return {
        ok: false,
        status,
        error: 'vision_provider_unreachable',
        lowConfidenceEvent: placeholderEvent({
          capturedAt,
          submitterId: input.submitterId,
          locationHint: input.locationHint,
          reason: 'Vision provider did not respond. Parse pending.',
        }),
      };
    }
  }

  const toolBlock = response.content.find((b) => b.type === 'tool_use');
  if (!toolBlock || toolBlock.type !== 'tool_use') {
    return {
      ok: false,
      status: 422,
      error: 'model_did_not_call_tool',
      lowConfidenceEvent: placeholderEvent({
        capturedAt,
        submitterId: input.submitterId,
        locationHint: input.locationHint,
        reason: 'Model returned no structured tool call.',
      }),
    };
  }

  const validated = validateVisionParseResult(toolBlock.input);
  if (!validated.ok) {
    return {
      ok: false,
      status: 422,
      error: `invalid_model_output:${validated.reason}`,
      lowConfidenceEvent: placeholderEvent({
        capturedAt,
        submitterId: input.submitterId,
        locationHint: input.locationHint,
        reason: `Model output failed schema validation (${validated.reason}).`,
      }),
    };
  }

  return {
    ok: true,
    event: mapToMissionEvent(validated.value, {
      capturedAt,
      submitterId: input.submitterId,
      locationHint: input.locationHint,
    }),
    raw: validated.value,
  };
}

export function mapToMissionEvent(
  parse: VisionParseResult,
  meta: { capturedAt: string; submitterId?: string; locationHint?: string }
): MissionEvent {
  const id = `event-vision-${nanoid(8)}`;
  const offRoute = parse.locationGuess.isSanFrancisco === false;
  const summary = offRoute ? `[off-route] ${parse.summary}` : parse.summary;
  const urgency = offRoute
    ? 'low'
    : parse.urgency === 'high'
      ? 'high'
      : parse.urgency === 'medium'
        ? 'medium'
        : 'low';
  return {
    id,
    missionId: MISSION_ID,
    timestamp: meta.capturedAt,
    source: {
      type: 'mobile_capture',
      name: meta.submitterId ? `mobile:${meta.submitterId}` : 'mobile:anonymous',
      reliability:
        parse.confidence >= 0.7 ? 'high' : parse.confidence >= 0.4 ? 'medium' : 'low',
    },
    eventType: parse.observationCategory,
    summary,
    entities: parse.notableEntities.map((label: string, i: number) => ({
      id: `${id}-entity-${i}`,
      type: 'unknown' as const,
      label,
    })),
    location: {
      description:
        parse.locationGuess.description ||
        meta.locationHint ||
        (offRoute ? 'Not San Francisco' : undefined),
    },
    confidence: parse.confidence,
    urgency,
    rawInput: {
      modality: 'image',
      contentRef: `mem://capture/${id}`,
    },
    extractedFields: {
      riskAssessment: parse.riskAssessment,
      vehicles: parse.vehicles,
      peopleEstimate: parse.peopleEstimate,
      infrastructureState: parse.infrastructureState,
      locationGuess: parse.locationGuess,
      rejectionReason: parse.rejectionReason ?? null,
    },
    affectsWorldState: !offRoute && parse.confidence >= 0.3,
  };
}

function placeholderEvent(meta: {
  capturedAt: string;
  submitterId?: string;
  locationHint?: string;
  reason: string;
}): MissionEvent {
  const id = `event-vision-stub-${nanoid(8)}`;
  return {
    id,
    missionId: MISSION_ID,
    timestamp: meta.capturedAt,
    source: {
      type: 'mobile_capture',
      name: meta.submitterId ? `mobile:${meta.submitterId}` : 'mobile:anonymous',
      reliability: 'low',
    },
    eventType: 'visual_observation',
    summary: `Photo received but not yet parsed. ${meta.reason}`,
    entities: [],
    location: meta.locationHint ? { description: meta.locationHint } : undefined,
    confidence: 0.1,
    urgency: 'low',
    rawInput: { modality: 'image', contentRef: `mem://capture/${id}` },
    extractedFields: { placeholder: true, reason: meta.reason },
    affectsWorldState: false,
  };
}

async function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return await Promise.race([
    p,
    new Promise<T>((_, reject) =>
      setTimeout(() => reject(new Error('vision_timeout')), ms)
    ),
  ]);
}

function isTimeout(e: unknown): boolean {
  return e instanceof Error && e.message === 'vision_timeout';
}
