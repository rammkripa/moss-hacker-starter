import type { VisionParseResult } from './types';

export const MISSION_EVENT_TOOL = {
  name: 'emit_mission_event',
  description:
    'Emit a single structured Mission Bay observation parsed from the attached photo.',
  input_schema: {
    type: 'object',
    required: [
      'observationCategory',
      'summary',
      'confidence',
      'urgency',
      'riskAssessment',
      'vehicles',
      'peopleEstimate',
      'infrastructureState',
      'locationGuess',
      'notableEntities',
    ],
    properties: {
      observationCategory: {
        type: 'string',
        enum: [
          'visual_observation',
          'traffic',
          'crowd',
          'weather',
          'infrastructure',
          'protest',
          'incident',
        ],
      },
      summary: { type: 'string', maxLength: 280 },
      confidence: { type: 'number', minimum: 0, maximum: 1 },
      urgency: { type: 'string', enum: ['low', 'medium', 'high'] },
      riskAssessment: { type: 'string', maxLength: 500 },
      vehicles: {
        type: 'object',
        required: ['count', 'descriptions'],
        properties: {
          count: { type: 'integer', minimum: 0 },
          descriptions: { type: 'array', items: { type: 'string', maxLength: 120 } },
        },
      },
      peopleEstimate: {
        type: 'object',
        required: ['count', 'bucket'],
        properties: {
          count: { type: ['integer', 'null'], minimum: 0 },
          bucket: {
            type: 'string',
            enum: ['none', 'few', 'dozens', 'hundreds', 'thousands', 'unknown'],
          },
        },
      },
      infrastructureState: {
        type: 'string',
        enum: ['normal', 'damaged', 'blocked', 'under_construction', 'unknown'],
      },
      locationGuess: {
        type: 'object',
        required: ['description', 'landmarks', 'streets', 'isSanFrancisco', 'confidence'],
        properties: {
          description: { type: 'string', maxLength: 200 },
          landmarks: { type: 'array', items: { type: 'string' } },
          streets: { type: 'array', items: { type: 'string' } },
          isSanFrancisco: { type: 'boolean' },
          confidence: { type: 'number', minimum: 0, maximum: 1 },
        },
      },
      notableEntities: { type: 'array', items: { type: 'string' } },
      rejectionReason: { type: 'string' },
    },
  },
} as const;

export type ValidationOutcome =
  | { ok: true; value: VisionParseResult }
  | { ok: false; reason: string };

export function validateVisionParseResult(input: unknown): ValidationOutcome {
  if (!input || typeof input !== 'object') return { ok: false, reason: 'not_an_object' };
  const v = input as Record<string, unknown>;
  const categories = [
    'visual_observation', 'traffic', 'crowd', 'weather',
    'infrastructure', 'protest', 'incident',
  ];
  if (typeof v.observationCategory !== 'string' || !categories.includes(v.observationCategory)) {
    return { ok: false, reason: 'bad_observationCategory' };
  }
  if (typeof v.summary !== 'string' || v.summary.length === 0) {
    return { ok: false, reason: 'bad_summary' };
  }
  if (typeof v.confidence !== 'number' || v.confidence < 0 || v.confidence > 1) {
    return { ok: false, reason: 'bad_confidence' };
  }
  if (typeof v.urgency !== 'string' || !['low', 'medium', 'high'].includes(v.urgency)) {
    return { ok: false, reason: 'bad_urgency' };
  }
  if (typeof v.riskAssessment !== 'string') return { ok: false, reason: 'bad_riskAssessment' };
  if (!isVehicles(v.vehicles)) return { ok: false, reason: 'bad_vehicles' };
  if (!isPeopleEstimate(v.peopleEstimate)) return { ok: false, reason: 'bad_peopleEstimate' };
  const infraStates = ['normal', 'damaged', 'blocked', 'under_construction', 'unknown'];
  if (typeof v.infrastructureState !== 'string' || !infraStates.includes(v.infrastructureState)) {
    return { ok: false, reason: 'bad_infrastructureState' };
  }
  if (!isLocationGuess(v.locationGuess)) return { ok: false, reason: 'bad_locationGuess' };
  if (!Array.isArray(v.notableEntities) || v.notableEntities.some((x) => typeof x !== 'string')) {
    return { ok: false, reason: 'bad_notableEntities' };
  }
  return { ok: true, value: v as unknown as VisionParseResult };
}

function isVehicles(x: unknown): boolean {
  if (!x || typeof x !== 'object') return false;
  const o = x as Record<string, unknown>;
  if (typeof o.count !== 'number' || !Number.isInteger(o.count) || o.count < 0) return false;
  if (!Array.isArray(o.descriptions) || o.descriptions.some((d) => typeof d !== 'string')) return false;
  return true;
}

function isPeopleEstimate(x: unknown): boolean {
  if (!x || typeof x !== 'object') return false;
  const o = x as Record<string, unknown>;
  const buckets = ['none', 'few', 'dozens', 'hundreds', 'thousands', 'unknown'];
  if (typeof o.bucket !== 'string' || !buckets.includes(o.bucket)) return false;
  if (o.count !== null && (typeof o.count !== 'number' || !Number.isInteger(o.count) || o.count < 0)) return false;
  return true;
}

function isLocationGuess(x: unknown): boolean {
  if (!x || typeof x !== 'object') return false;
  const o = x as Record<string, unknown>;
  if (typeof o.description !== 'string') return false;
  if (!Array.isArray(o.landmarks) || o.landmarks.some((d) => typeof d !== 'string')) return false;
  if (!Array.isArray(o.streets) || o.streets.some((d) => typeof d !== 'string')) return false;
  if (typeof o.isSanFrancisco !== 'boolean') return false;
  if (typeof o.confidence !== 'number' || o.confidence < 0 || o.confidence > 1) return false;
  return true;
}
