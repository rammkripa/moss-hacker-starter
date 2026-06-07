export type MissionContext = {
  missionId: string;
  name: string;
  summary: string;
  objective: {
    primary: string;
    secondary: string[];
    successCriteria: string[];
    failureConditions: string[];
  };
  timeline: {
    missionStart: string;
    targetCompletion: string;
    keyMilestones: Array<{
      time?: string;
      description: string;
    }>;
  };
  constraints: Array<{
    id: string;
    type: 'safety' | 'legal' | 'operational' | 'communications' | 'environmental';
    description: string;
    priority: 'low' | 'medium' | 'high' | 'critical';
  }>;
  routes: Array<{
    id: string;
    name: string;
    sectors: string[];
    status: 'planned' | 'fallback' | 'restricted' | 'unknown';
    notes?: string;
  }>;
  importantContext: string[];
};

export type TerrainMap = {
  mapId: string;
  name: string;
  sectors: Array<{
    id: string;
    name: string;
    description: string;
    coordinates: {
      x: number;
      y: number;
    };
    terrainType: 'urban' | 'forest' | 'mountain' | 'road' | 'bridge' | 'open_field' | 'unknown';
    riskLevel: 'low' | 'medium' | 'high' | 'critical';
    annotations: string[];
  }>;
  landmarks: Array<{
    id: string;
    name: string;
    sectorId: string;
    type:
      | 'checkpoint'
      | 'bridge'
      | 'building'
      | 'road'
      | 'extraction_point'
      | 'risk_zone'
      | 'other';
    description: string;
  }>;
};

export type TeamContext = {
  teamId: string;
  name: string;
  members: Array<{
    id: string;
    callSign: string;
    role: string;
    skills: string[];
    assets: string[];
    notes?: string;
  }>;
  units: Array<{
    id: string;
    name: string;
    members: string[];
    assignment: string;
  }>;
};

export type MissionEvent = {
  id: string;
  missionId: string;
  timestamp: string;
  source: {
    type:
      | 'comms'
      | 'gps'
      | 'drone_image'
      | 'mobile_capture'
      | 'command_update'
      | 'manual_note'
      | 'system';
    name: string;
    reliability: 'low' | 'medium' | 'high';
  };
  eventType:
    | 'position_update'
    | 'route_status_update'
    | 'visual_observation'
    | 'traffic'
    | 'crowd'
    | 'weather'
    | 'infrastructure'
    | 'protest'
    | 'incident'
    | 'command_update'
    | 'status_report'
    | 'risk_detected'
    | 'objective_update'
    | 'equipment_update'
    | 'transit_delay'
    | 'comms'
    | 'conflict'
    | 'unknown';
  summary: string;
  entities: Array<{
    id: string;
    type: 'team' | 'person' | 'route' | 'sector' | 'landmark' | 'vehicle' | 'unknown';
    label: string;
  }>;
  location?: {
    sectorId?: string;
    landmarkId?: string;
    coordinates?: {
      x: number;
      y: number;
    };
    description?: string;
  };
  confidence: number;
  urgency: 'low' | 'medium' | 'high' | 'critical';
  rawInput?: {
    modality: 'text' | 'audio' | 'image' | 'video_frame' | 'gps';
    contentRef?: string;
    transcript?: string;
  };
  extractedFields?: Record<string, unknown>;
  affectsWorldState: boolean;
};

export type WorldState = {
  missionId: string;
  updatedAt: string;
  currentObjective: string;
  teamPositions: Record<
    string,
    {
      sectorId: string;
      coordinates?: {
        x: number;
        y: number;
      };
      status: 'moving' | 'holding' | 'unknown' | 'offline';
      lastUpdated: string;
    }
  >;
  routeStatus: Record<
    string,
    {
      status: 'clear' | 'blocked' | 'risky' | 'unknown';
      confidence: number;
      reason: string;
      supportingEventIds: string[];
      lastUpdated: string;
    }
  >;
  knownRisks: Array<{
    id: string;
    summary: string;
    sectorId?: string;
    urgency: 'low' | 'medium' | 'high' | 'critical';
    confidence: number;
    supportingEventIds: string[];
    lastUpdated: string;
  }>;
  recentChanges: Array<{
    id: string;
    summary: string;
    eventIds: string[];
    significance: 'low' | 'medium' | 'high';
    timestamp: string;
  }>;
  openQuestions: Array<{
    id: string;
    question: string;
    whyItMatters: string;
    relatedSectorId?: string;
    priority: 'low' | 'medium' | 'high';
  }>;
};

export type VisionObservationCategory =
  | 'visual_observation'
  | 'traffic'
  | 'crowd'
  | 'weather'
  | 'infrastructure'
  | 'protest'
  | 'incident';

export type VisionParseResult = {
  observationCategory: VisionObservationCategory;
  summary: string;
  confidence: number;
  urgency: 'low' | 'medium' | 'high';
  riskAssessment: string;
  vehicles: { count: number; descriptions: string[] };
  peopleEstimate: {
    count: number | null;
    bucket: 'none' | 'few' | 'dozens' | 'hundreds' | 'thousands' | 'unknown';
  };
  infrastructureState:
    | 'normal' | 'damaged' | 'blocked' | 'under_construction' | 'unknown';
  locationGuess: {
    description: string;
    landmarks: string[];
    streets: string[];
    isSanFrancisco: boolean;
    confidence: number;
  };
  notableEntities: string[];
  rejectionReason?: string;
};
