import { MISSION_ID, missionContext } from './fake-data';
import type { MissionEvent, WorldState } from './types';

function appendUnique(values: string[], next: string) {
  return values.includes(next) ? values : [...values, next];
}

function significanceForUrgency(urgency: MissionEvent['urgency']): 'low' | 'medium' | 'high' {
  if (urgency === 'critical' || urgency === 'high') return 'high';
  if (urgency === 'medium') return 'medium';
  return 'low';
}

function recentChangeFor(event: MissionEvent): WorldState['recentChanges'][number] {
  return {
    id: `change-${event.id}`,
    summary: event.summary,
    eventIds: [event.id],
    significance: significanceForUrgency(event.urgency),
    timestamp: event.timestamp,
  };
}

export function createInitialWorldState(missionId: string): WorldState {
  const now = missionContext.timeline.missionStart;

  return {
    missionId,
    updatedAt: now,
    currentObjective: missionContext.objective.primary,
    teamPositions: {
      alpha: {
        sectorId: 'C2',
        coordinates: { x: 12, y: 70 },
        status: 'holding',
        lastUpdated: now,
      },
      bravo: {
        sectorId: 'B6',
        coordinates: { x: 30, y: 48 },
        status: 'unknown',
        lastUpdated: now,
      },
    },
    routeStatus: {
      'route-a': {
        status: 'clear',
        confidence: 0.55,
        reason:
          'Original mission plan marks Route A through B7 as planned and low risk; no live contradiction yet.',
        supportingEventIds: [],
        lastUpdated: now,
      },
      'route-c': {
        status: 'unknown',
        confidence: 0.4,
        reason: 'Fallback Route C is planned but has not been recently verified.',
        supportingEventIds: [],
        lastUpdated: now,
      },
    },
    knownRisks: [],
    recentChanges: [],
    openQuestions: [
      {
        id: 'verify-route-c-clear',
        question: 'Is Route C currently clear enough to use as fallback?',
        whyItMatters: 'Route C avoids the bridge, but its live status is not confirmed.',
        relatedSectorId: 'D4',
        priority: 'medium',
      },
    ],
  };
}

export function applyEventToWorldState(current: WorldState, event: MissionEvent): WorldState {
  if (!event.affectsWorldState) {
    return current;
  }

  const next: WorldState = {
    ...current,
    updatedAt: event.timestamp,
    teamPositions: { ...current.teamPositions },
    routeStatus: { ...current.routeStatus },
    knownRisks: [...current.knownRisks],
    recentChanges: [...current.recentChanges],
    openQuestions: [...current.openQuestions],
  };

  if (event.eventType === 'position_update') {
    const teamId =
      typeof event.extractedFields?.teamId === 'string'
        ? event.extractedFields.teamId
        : event.entities.find((entity) => entity.type === 'team')?.id;
    if (teamId && event.location?.sectorId) {
      next.teamPositions[teamId] = {
        sectorId: event.location.sectorId,
        coordinates: event.location.coordinates,
        status: event.extractedFields?.positionStatus === 'holding' ? 'holding' : 'moving',
        lastUpdated: event.timestamp,
      };
    }
  }

  if (event.eventType === 'route_status_update') {
    const routeId =
      typeof event.extractedFields?.routeId === 'string'
        ? event.extractedFields.routeId
        : event.entities.find((entity) => entity.type === 'route')?.id;
    const statusRaw = event.extractedFields?.routeStatus;
    const status =
      statusRaw === 'blocked' ||
      statusRaw === 'risky' ||
      statusRaw === 'clear' ||
      statusRaw === 'unknown'
        ? statusRaw
        : 'unknown';
    if (routeId) {
      const existing = next.routeStatus[routeId];
      next.routeStatus[routeId] = {
        status,
        confidence: event.confidence,
        reason:
          typeof event.extractedFields?.reason === 'string'
            ? event.extractedFields.reason
            : event.summary,
        supportingEventIds: appendUnique(existing?.supportingEventIds ?? [], event.id),
        lastUpdated: event.timestamp,
      };
    }

    if (routeId === 'route-a' && (status === 'risky' || status === 'blocked')) {
      const riskId = 'risk-route-a-bridge';
      const existingRisk = next.knownRisks.find((risk) => risk.id === riskId);
      if (existingRisk) {
        existingRisk.supportingEventIds = appendUnique(existingRisk.supportingEventIds, event.id);
        existingRisk.confidence = Math.max(existingRisk.confidence, event.confidence);
        existingRisk.lastUpdated = event.timestamp;
      } else {
        next.knownRisks.push({
          id: riskId,
          summary: 'Route A may be blocked or risky near the bridge checkpoint.',
          sectorId: event.location?.sectorId,
          urgency: event.urgency,
          confidence: event.confidence,
          supportingEventIds: [event.id],
          lastUpdated: event.timestamp,
        });
      }
    }

    if (routeId === 'route-c' && status === 'unknown') {
      const questionId = 'verify-route-c-clear';
      if (!next.openQuestions.some((question) => question.id === questionId)) {
        next.openQuestions.push({
          id: questionId,
          question: 'Is Route C currently clear enough to use as fallback?',
          whyItMatters:
            'Bravo cannot confirm the fallback corridor, so rerouting depends on verification.',
          relatedSectorId: 'D4',
          priority: 'high',
        });
      } else {
        next.openQuestions = next.openQuestions.map((question) =>
          question.id === questionId ? { ...question, priority: 'high' } : question
        );
      }
    }
  }

  if (event.eventType === 'visual_observation' || event.eventType === 'risk_detected') {
    const riskId =
      typeof event.extractedFields?.riskId === 'string'
        ? event.extractedFields.riskId
        : `risk-${event.id}`;
    const existingRisk = next.knownRisks.find((risk) => risk.id === riskId);
    if (existingRisk) {
      existingRisk.summary = event.summary;
      existingRisk.confidence = Math.max(existingRisk.confidence, event.confidence);
      existingRisk.urgency = event.urgency;
      existingRisk.supportingEventIds = appendUnique(existingRisk.supportingEventIds, event.id);
      existingRisk.lastUpdated = event.timestamp;
    } else {
      next.knownRisks.push({
        id: riskId,
        summary: event.summary,
        sectorId: event.location?.sectorId,
        urgency: event.urgency,
        confidence: event.confidence,
        supportingEventIds: [event.id],
        lastUpdated: event.timestamp,
      });
    }

    const routeA = next.routeStatus['route-a'];
    next.routeStatus['route-a'] = {
      status: 'risky',
      confidence: Math.max(routeA?.confidence ?? 0, event.confidence),
      reason:
        'Drone imagery adds evidence of vehicles near the B7 bridge checkpoint, weakening the original low-risk assumption.',
      supportingEventIds: appendUnique(routeA?.supportingEventIds ?? [], event.id),
      lastUpdated: event.timestamp,
    };

    const questionId =
      typeof event.extractedFields?.openQuestionId === 'string'
        ? event.extractedFields.openQuestionId
        : `verify-${event.id}`;
    if (!next.openQuestions.some((question) => question.id === questionId)) {
      next.openQuestions.push({
        id: questionId,
        question:
          'What are the vehicles near the bridge checkpoint doing, and do they block Route A?',
        whyItMatters:
          'Alpha is moving toward B7, so the bridge checkpoint risk must be verified before treating Route A as safe.',
        relatedSectorId: event.location?.sectorId,
        priority: 'high',
      });
    }
  }

  if (event.eventType === 'command_update' || event.eventType === 'objective_update') {
    const currentObjective = event.extractedFields?.currentObjective;
    next.currentObjective = typeof currentObjective === 'string' ? currentObjective : event.summary;
  }

  next.recentChanges = [
    recentChangeFor(event),
    ...next.recentChanges.filter((change) => change.id !== `change-${event.id}`),
  ].slice(0, 8);

  return next;
}

export function resetWorldState(): WorldState {
  return createInitialWorldState(MISSION_ID);
}
