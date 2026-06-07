import type { MissionContext, MissionEvent, TeamContext, TerrainMap } from './types';

export const MISSION_ID = 'operation-checkpoint-echo';

export const missionContext: MissionContext = {
  missionId: MISSION_ID,
  name: 'Operation Checkpoint Echo',
  summary:
    'Team Alpha must reach Checkpoint Echo by fourteen thirty while Mission Bay tracks route risk, team position, and verification needs.',
  objective: {
    primary: 'Team Alpha must reach Checkpoint Echo by 14:30.',
    secondary: ['Maintain comms with Bravo recon/support.', 'Keep Route C available as fallback.'],
    successCriteria: [
      'Alpha reaches E9 by 14:30.',
      'No unverified route assumption is treated as certain.',
    ],
    failureConditions: [
      'Alpha misses the extraction window.',
      'Team proceeds through a critical unverified risk.',
    ],
  },
  timeline: {
    missionStart: '2026-06-06T13:00:00Z',
    targetCompletion: '2026-06-06T14:30:00Z',
    keyMilestones: [
      { time: '13:00', description: 'Alpha departs C2 start area.' },
      { time: '13:45', description: 'Alpha expected near B6 approach sector.' },
      { time: '14:30', description: 'Alpha reaches Checkpoint Echo / extraction point E9.' },
    ],
  },
  constraints: [
    {
      id: 'constraint-safety-1',
      type: 'safety',
      description:
        'Mission Bay is decision support only and must surface uncertainty and verification steps.',
      priority: 'critical',
    },
    {
      id: 'constraint-comms-1',
      type: 'communications',
      description: 'Bravo reports may be delayed; do not treat unclear comms as confirmation.',
      priority: 'high',
    },
    {
      id: 'constraint-env-1',
      type: 'environmental',
      description: 'Sector B7 has limited visibility around the bridge checkpoint.',
      priority: 'high',
    },
  ],
  routes: [
    {
      id: 'route-a',
      name: 'Route A',
      sectors: ['C2', 'B6', 'B7', 'E9'],
      status: 'planned',
      notes:
        'Original route through Sector B7 and the bridge checkpoint; initially marked low risk.',
    },
    {
      id: 'route-c',
      name: 'Route C',
      sectors: ['C2', 'D4', 'E9'],
      status: 'fallback',
      notes: 'Slower fallback corridor that avoids the bridge checkpoint.',
    },
  ],
  importantContext: [
    'Planned Route A goes through Sector B7 and was originally low risk.',
    'Fallback Route C is slower but avoids the bridge.',
    'Sector B7 contains a bridge checkpoint and limited-visibility terrain.',
    'Unknowns must be stated explicitly; do not present tactical certainty beyond evidence.',
  ],
};

export const terrainMap: TerrainMap = {
  mapId: 'checkpoint-echo-grid',
  name: 'Checkpoint Echo Mission Grid',
  sectors: [
    {
      id: 'C2',
      name: 'Start Area',
      description: 'Mission start area and Alpha departure point.',
      coordinates: { x: 12, y: 70 },
      terrainType: 'open_field',
      riskLevel: 'low',
      annotations: ['Initial Alpha position', 'Reliable comms at start'],
    },
    {
      id: 'B6',
      name: 'Approach Sector',
      description: 'Approach corridor between the start area and bridge sector.',
      coordinates: { x: 34, y: 52 },
      terrainType: 'road',
      riskLevel: 'low',
      annotations: ['Part of Route A', 'Expected transit sector'],
    },
    {
      id: 'B7',
      name: 'Bridge Checkpoint',
      description: 'Bridge checkpoint with limited-visibility terrain.',
      coordinates: { x: 58, y: 42 },
      terrainType: 'bridge',
      riskLevel: 'medium',
      annotations: [
        'Originally low risk for Route A',
        'Visibility constraints',
        'Needs verification after live reports',
      ],
    },
    {
      id: 'D4',
      name: 'Fallback Corridor',
      description: 'Slower corridor that avoids the bridge checkpoint.',
      coordinates: { x: 42, y: 82 },
      terrainType: 'road',
      riskLevel: 'low',
      annotations: ['Route C fallback', 'Clear status unconfirmed'],
    },
    {
      id: 'E9',
      name: 'Checkpoint Echo',
      description: 'Extraction point and target completion location.',
      coordinates: { x: 84, y: 56 },
      terrainType: 'urban',
      riskLevel: 'low',
      annotations: ['Target arrival by 14:30', 'Extraction point'],
    },
  ],
  landmarks: [
    {
      id: 'lm-bridge',
      name: 'Bridge Checkpoint',
      sectorId: 'B7',
      type: 'bridge',
      description: 'Bridge checkpoint on Route A.',
    },
    {
      id: 'lm-echo',
      name: 'Checkpoint Echo',
      sectorId: 'E9',
      type: 'extraction_point',
      description: 'Mission extraction point.',
    },
  ],
};

export const teamContext: TeamContext = {
  teamId: 'mission-bay-team',
  name: 'Checkpoint Echo Team',
  members: [
    {
      id: 'chen',
      callSign: 'Chen',
      role: 'Comms specialist',
      skills: ['comms', 'radio relay'],
      assets: ['field radio'],
      notes: 'Primary teammate for communications questions.',
    },
    {
      id: 'singh',
      callSign: 'Singh',
      role: 'Medic',
      skills: ['trauma care', 'triage'],
      assets: ['med kit'],
    },
    {
      id: 'alvarez',
      callSign: 'Alvarez',
      role: 'Drone operator',
      skills: ['drone operations', 'imagery review'],
      assets: ['quad drone'],
    },
    {
      id: 'brooks',
      callSign: 'Brooks',
      role: 'Navigation lead',
      skills: ['route planning', 'terrain reading'],
      assets: ['offline map'],
    },
  ],
  units: [
    {
      id: 'alpha',
      name: 'Alpha',
      members: ['chen', 'singh', 'brooks'],
      assignment: 'Primary field unit moving to Checkpoint Echo.',
    },
    {
      id: 'bravo',
      name: 'Bravo',
      members: ['alvarez'],
      assignment: 'Recon/support with comms and drone observations.',
    },
  ],
};

export const scriptedMissionEvents: MissionEvent[] = [
  {
    id: 'event-001-alpha-to-b6',
    missionId: MISSION_ID,
    timestamp: '2026-06-06T13:10:00Z',
    source: { type: 'gps', name: 'Alpha GPS', reliability: 'high' },
    eventType: 'position_update',
    summary: 'Alpha leaves C2 and moves toward B6.',
    entities: [
      { id: 'alpha', type: 'team', label: 'Alpha' },
      { id: 'B6', type: 'sector', label: 'Sector B6' },
    ],
    location: { sectorId: 'B6', coordinates: { x: 34, y: 52 }, description: 'Approach sector B6.' },
    confidence: 0.95,
    urgency: 'low',
    rawInput: { modality: 'gps', transcript: 'Alpha GPS transition C2 to B6.' },
    extractedFields: { teamId: 'alpha', positionStatus: 'moving' },
    affectsWorldState: true,
  },
  {
    id: 'event-002-route-a-bridge-blocked',
    missionId: MISSION_ID,
    timestamp: '2026-06-06T13:22:00Z',
    source: { type: 'comms', name: 'Bravo radio', reliability: 'medium' },
    eventType: 'route_status_update',
    summary: 'Bravo reports Route A may be blocked near the bridge checkpoint.',
    entities: [
      { id: 'route-a', type: 'route', label: 'Route A' },
      { id: 'B7', type: 'sector', label: 'Sector B7' },
    ],
    location: { sectorId: 'B7', landmarkId: 'lm-bridge', description: 'Near bridge checkpoint.' },
    confidence: 0.68,
    urgency: 'high',
    rawInput: {
      modality: 'audio',
      transcript: 'Bravo to Mission Bay: Route A may be blocked near the bridge.',
    },
    extractedFields: {
      routeId: 'route-a',
      routeStatus: 'risky',
      reason: 'Possible blockage near bridge checkpoint.',
    },
    affectsWorldState: true,
  },
  {
    id: 'event-003-drone-vehicles-b7',
    missionId: MISSION_ID,
    timestamp: '2026-06-06T13:28:00Z',
    source: { type: 'drone_image', name: 'Bravo drone mock parser', reliability: 'medium' },
    eventType: 'visual_observation',
    summary: 'Drone imagery suggests three vehicles near the bridge checkpoint.',
    entities: [
      { id: 'vehicle-group-1', type: 'vehicle', label: 'Three vehicles' },
      { id: 'B7', type: 'sector', label: 'Sector B7' },
    ],
    location: {
      sectorId: 'B7',
      landmarkId: 'lm-bridge',
      coordinates: { x: 58, y: 42 },
      description: 'Bridge checkpoint vicinity.',
    },
    confidence: 0.72,
    urgency: 'high',
    rawInput: { modality: 'image', contentRef: 'mock://drone/b7-bridge-vehicles' },
    extractedFields: { riskId: 'risk-b7-vehicles', openQuestionId: 'verify-vehicles-b7' },
    affectsWorldState: true,
  },
  {
    id: 'event-004-command-extraction-priority',
    missionId: MISSION_ID,
    timestamp: '2026-06-06T13:34:00Z',
    source: { type: 'command_update', name: 'Command', reliability: 'high' },
    eventType: 'command_update',
    summary: 'Command changes priority from reconnaissance to extraction.',
    entities: [{ id: 'operation-checkpoint-echo', type: 'unknown', label: 'Mission objective' }],
    confidence: 0.98,
    urgency: 'critical',
    rawInput: {
      modality: 'text',
      transcript: 'Priority is now extraction. Get Alpha to Checkpoint Echo.',
    },
    extractedFields: {
      currentObjective:
        'Prioritize extraction: get Alpha to Checkpoint Echo by 14:30 while avoiding unverified route risk.',
    },
    affectsWorldState: true,
  },
  {
    id: 'event-005-alpha-close-b7',
    missionId: MISSION_ID,
    timestamp: '2026-06-06T13:40:00Z',
    source: { type: 'gps', name: 'Alpha GPS', reliability: 'high' },
    eventType: 'position_update',
    summary: 'Alpha is close to B7.',
    entities: [
      { id: 'alpha', type: 'team', label: 'Alpha' },
      { id: 'B7', type: 'sector', label: 'Sector B7' },
    ],
    location: {
      sectorId: 'B7',
      coordinates: { x: 53, y: 45 },
      description: 'Approaching Sector B7.',
    },
    confidence: 0.93,
    urgency: 'high',
    rawInput: { modality: 'gps', transcript: 'Alpha GPS near B7 approach.' },
    extractedFields: { teamId: 'alpha', positionStatus: 'moving' },
    affectsWorldState: true,
  },
  {
    id: 'event-006-route-c-unconfirmed',
    missionId: MISSION_ID,
    timestamp: '2026-06-06T13:47:00Z',
    source: { type: 'comms', name: 'Bravo radio', reliability: 'medium' },
    eventType: 'route_status_update',
    summary: 'Bravo cannot confirm whether Route C is clear.',
    entities: [
      { id: 'route-c', type: 'route', label: 'Route C' },
      { id: 'D4', type: 'sector', label: 'Sector D4' },
    ],
    location: { sectorId: 'D4', description: 'Fallback corridor status unknown.' },
    confidence: 0.6,
    urgency: 'medium',
    rawInput: { modality: 'audio', transcript: 'Bravo cannot confirm Route C is clear.' },
    extractedFields: {
      routeId: 'route-c',
      routeStatus: 'unknown',
      reason: 'Bravo cannot confirm fallback corridor is clear.',
    },
    affectsWorldState: true,
  },
];
