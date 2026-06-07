import { nanoid } from 'nanoid';
import type { MissionEvent, VisionParseResult } from './types';
import { VISION_SYSTEM_PROMPT, buildUserPrompt } from './vision-parser-prompt';
import { MISSION_EVENT_TOOL, validateVisionParseResult } from './vision-parser-schema';

const VISION_MODEL = process.env.OPENAI_VISION_MODEL ?? process.env.VISION_MODEL ?? 'gpt-4o-mini';
const OPENAI_CHAT_COMPLETIONS_URL =
  process.env.OPENAI_CHAT_COMPLETIONS_URL ?? 'https://api.openai.com/v1/chat/completions';
// Larger images (phone uploads can be 5-10MB) need more headroom for the
// upload-to-provider + model inference round trip. Total worst-case ~45s.
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

export async function parsePhotoToMissionEvent(input: ParsePhotoInput): Promise<ParsePhotoOutcome> {
  const capturedAt = new Date().toISOString();
  const userPrompt = buildUserPrompt({
    submitterId: input.submitterId,
    locationHint: input.locationHint,
    capturedAt,
  });
  const base64 = Buffer.from(input.imageBytes).toString('base64');

  const attempt = async (timeoutMs: number) =>
    withTimeout(callOpenAIVision({ base64, mimeType: input.mimeType, userPrompt }), timeoutMs);

  let parsedJson: unknown;
  try {
    parsedJson = await attempt(FIRST_ATTEMPT_TIMEOUT_MS);
  } catch (e1) {
    try {
      parsedJson = await attempt(RETRY_TIMEOUT_MS);
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

  const validated = validateVisionParseResult(parsedJson);
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

type ChatCompletionResponse = {
  choices?: Array<{
    message?: {
      content?: unknown;
      tool_calls?: Array<{
        function?: {
          name?: string;
          arguments?: string;
        };
      }>;
    };
  }>;
};

async function callOpenAIVision(input: {
  base64: string;
  mimeType: ParsePhotoInput['mimeType'];
  userPrompt: string;
}): Promise<unknown> {
  const apiKey = process.env.REAL_OPENAI_KEY ?? process.env.OPENAI_API_KEY;
  if (!apiKey) {
    throw new Error('missing_openai_api_key');
  }

  const res = await fetch(OPENAI_CHAT_COMPLETIONS_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: VISION_MODEL,
      temperature: 0.1,
      max_tokens: 1024,
      response_format: { type: 'json_object' },
      messages: [
        {
          role: 'system',
          content: `${VISION_SYSTEM_PROMPT}

Return exactly one JSON object matching this JSON Schema. Do not wrap it in markdown and do not include prose:
${JSON.stringify(MISSION_EVENT_TOOL.input_schema)}`,
        },
        {
          role: 'user',
          content: [
            { type: 'text', text: input.userPrompt },
            {
              type: 'image_url',
              image_url: {
                url: `data:${input.mimeType};base64,${input.base64}`,
              },
            },
          ],
        },
      ],
    }),
  });

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`openai_vision_http_${res.status}:${body.slice(0, 300)}`);
  }

  const json = (await res.json()) as ChatCompletionResponse;
  return extractStructuredOutput(json);
}

function extractStructuredOutput(response: ChatCompletionResponse): unknown {
  const message = response.choices?.[0]?.message;
  const toolCall = message?.tool_calls?.find(
    (call) => call.function?.name === MISSION_EVENT_TOOL.name
  );
  if (toolCall?.function?.arguments) {
    return parseJsonish(toolCall.function.arguments);
  }

  if (typeof message?.content === 'string') {
    return parseJsonish(message.content);
  }

  if (Array.isArray(message?.content)) {
    const text = message.content
      .map((part) => {
        if (!part || typeof part !== 'object') return '';
        const p = part as Record<string, unknown>;
        return typeof p.text === 'string' ? p.text : '';
      })
      .join('\n')
      .trim();
    if (text) return parseJsonish(text);
  }

  throw new Error('openai_vision_no_structured_output');
}

function parseJsonish(raw: string): unknown {
  const trimmed = raw.trim();
  const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  return JSON.parse(fenced ? fenced[1] : trimmed);
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
      reliability: parse.confidence >= 0.7 ? 'high' : parse.confidence >= 0.4 ? 'medium' : 'low',
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
    new Promise<T>((_, reject) => setTimeout(() => reject(new Error('vision_timeout')), ms)),
  ]);
}

function isTimeout(e: unknown): boolean {
  return e instanceof Error && e.message === 'vision_timeout';
}
