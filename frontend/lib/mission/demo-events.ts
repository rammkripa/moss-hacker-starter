// Curated demo events for Operation Pier Glass.
// Mission Bay SF. Two soldiers: Alpha (UCSF side, mobile) + Bravo (Chase Center side, observer).
// Goal: extract both to Pier 50.

import type { MissionEvent } from './types';

export type DemoEvent = {
  label: string;
  hint: string;
  tone: 'slate' | 'green' | 'amber' | 'rose' | 'cyan';
  build: () => MissionEvent;
};

const MISSION_ID = 'operation-pier-glass';

function freshId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

// Real Mission Bay coordinates (lat/lng).
export const SECTOR_COORDS: Record<string, { lat: number; lng: number; label: string }> = {
  M1: { lat: 37.7680, lng: -122.3915, label: 'UCSF Mission Bay Hospital' },
  M2: { lat: 37.7685, lng: -122.3905, label: 'Mission Bay Blvd S / 5th St' },
  M3: { lat: 37.7700, lng: -122.3900, label: 'Nelson Rising Ln / 4th St' },
  M4: { lat: 37.7710, lng: -122.3885, label: '3rd & Mission Rock (RISKY)' },
  M5: { lat: 37.7680, lng: -122.3870, label: 'Chase Center / Bayfront Park' },
  M6: { lat: 37.7725, lng: -122.3895, label: 'Long Bridge / China Basin' },
  W1: { lat: 37.7705, lng: -122.3855, label: 'Bayfront waterfront path' },
  P1: { lat: 37.7720, lng: -122.3825, label: 'Pier 50 (EXTRACTION)' },
};

function sectorCoord(sector: string): { x: number; y: number } | undefined {
  const c = SECTOR_COORDS[sector];
  return c ? { x: c.lng, y: c.lat } : undefined;
}

function baseEvent(opts: {
  eventType: MissionEvent['eventType'];
  summary: string;
  confidence: number;
  urgency: MissionEvent['urgency'];
  sourceName: string;
  sourceType?: MissionEvent['source']['type'];
  reliability?: MissionEvent['source']['reliability'];
  sectorId?: string;
  description?: string;
  extractedFields?: Record<string, unknown>;
  idPrefix: string;
}): MissionEvent {
  return {
    id: freshId(opts.idPrefix),
    missionId: MISSION_ID,
    timestamp: nowIso(),
    source: {
      type: opts.sourceType ?? 'system',
      name: opts.sourceName,
      reliability: opts.reliability ?? 'high',
    },
    eventType: opts.eventType,
    summary: opts.summary,
    entities: [],
    confidence: opts.confidence,
    urgency: opts.urgency,
    location: opts.sectorId
      ? {
          sectorId: opts.sectorId,
          coordinates: sectorCoord(opts.sectorId),
          description: opts.description ?? SECTOR_COORDS[opts.sectorId]?.label,
        }
      : undefined,
    extractedFields: opts.extractedFields,
    affectsWorldState: true,
  };
}

export const DEMO_EVENTS: DemoEvent[] = [
  {
    label: '1. Alpha starts moving',
    hint: 'Alpha leaves UCSF M1 and heads east on Mission Bay Blvd S toward the central corridor.',
    tone: 'cyan',
    build: () =>
      baseEvent({
        idPrefix: 'alpha-depart',
        eventType: 'position_update',
        summary:
          'Alpha departing UCSF Mission Bay (M1). Moving east on Mission Bay Boulevard South toward the planned central corridor.',
        confidence: 0.99,
        urgency: 'medium',
        sourceName: 'gps:Alpha',
        sourceType: 'gps',
        sectorId: 'M2',
      }),
  },
  {
    label: '2. Bravo: smoke at 3rd & Mission Rock',
    hint: 'Bravo radios that the central corridor (M4) has smoke and intermittent movement.',
    tone: 'amber',
    build: () =>
      baseEvent({
        idPrefix: 'bravo-radio-smoke',
        eventType: 'comms',
        summary:
          'Bravo reports smoke and intermittent movement near 3rd Street and Mission Rock (M4). Cannot confirm central corridor is clear.',
        confidence: 0.78,
        urgency: 'medium',
        sourceName: 'comms:Bravo',
        sourceType: 'comms',
        sectorId: 'M4',
        extractedFields: {
          speaker_callsign: 'Bravo',
          observation_category: 'crowd',
        },
      }),
  },
  {
    label: '3. Alpha approaching M4 (RISKY)',
    hint: 'Alpha is now physically close to the same M4 area Bravo just flagged.',
    tone: 'rose',
    build: () =>
      baseEvent({
        idPrefix: 'alpha-near-m4',
        eventType: 'position_update',
        summary:
          'Alpha now approaching the 3rd Street / Mission Rock M4 corridor — the same sector Bravo just flagged for smoke and movement.',
        confidence: 0.99,
        urgency: 'high',
        sourceName: 'gps:Alpha',
        sourceType: 'gps',
        sectorId: 'M3',
        extractedFields: { approaching_risk_sector: 'M4' },
      }),
  },
  {
    label: '4. Drone: waterfront may be clearer',
    hint: 'Drone imagery suggests the Bayfront W1 path is less obstructed than M4.',
    tone: 'green',
    build: () =>
      baseEvent({
        idPrefix: 'drone-waterfront',
        eventType: 'visual_observation',
        summary:
          'Drone observation: the Bayfront waterfront path (W1) toward Pier 50 appears less obstructed than the central 3rd Street corridor. Visibility partial; not fully confirmed.',
        confidence: 0.68,
        urgency: 'medium',
        sourceName: 'drone',
        sectorId: 'W1',
        extractedFields: { observation_category: 'terrain', infrastructure_state: 'normal' },
      }),
  },
  {
    label: '5. Command: extraction priority',
    hint: 'Command updates the picture: extraction is now top priority. Stop reconning.',
    tone: 'rose',
    build: () =>
      baseEvent({
        idPrefix: 'command-priority',
        eventType: 'command_update',
        summary:
          'Command update from EXCON: extraction is now the priority. Stop spending time confirming secondary corridors. Find the fastest reasonably safe route to Pier 50 (P1).',
        confidence: 0.99,
        urgency: 'high',
        sourceName: 'command:EXCON',
        sourceType: 'command_update',
      }),
  },
  {
    label: '6. Bravo offers waterfront guidance',
    hint: 'Bravo: eyes on Bayfront side — can guide Alpha along W1 if Alpha avoids M4.',
    tone: 'cyan',
    build: () =>
      baseEvent({
        idPrefix: 'bravo-guidance',
        eventType: 'comms',
        summary:
          'Bravo has eyes on the Bayfront side. Can guide Alpha toward the waterfront W1 route to Pier 50 if Alpha avoids the 3rd Street M4 crossing.',
        confidence: 0.85,
        urgency: 'medium',
        sourceName: 'comms:Bravo',
        sourceType: 'comms',
        sectorId: 'M5',
        extractedFields: { speaker_callsign: 'Bravo' },
      }),
  },
];
