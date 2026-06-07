'use client';

import { type ReactNode, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  missionContext,
  scriptedMissionEvents,
  teamContext,
  terrainMap,
} from '@/lib/mission/fake-data';
import { applyEventToWorldState, resetWorldState } from '@/lib/mission/reducer';
import type { MissionEvent, WorldState } from '@/lib/mission/types';

function Panel({
  title,
  children,
  className = '',
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-2xl border border-slate-700/70 bg-slate-900/75 p-4 shadow-xl shadow-black/20 ${className}`}
    >
      <h2 className="mb-3 text-sm font-semibold tracking-[0.18em] text-cyan-300 uppercase">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Pill({
  children,
  tone = 'slate',
}: {
  children: ReactNode;
  tone?: 'slate' | 'green' | 'yellow' | 'red' | 'cyan';
}) {
  const tones = {
    slate: 'border-slate-600 bg-slate-800 text-slate-200',
    green: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
    yellow: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    red: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
    cyan: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200',
  };
  return (
    <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

function toneForUrgency(value: string) {
  if (value === 'critical' || value === 'high' || value === 'blocked' || value === 'risky')
    return 'red' as const;
  if (value === 'medium' || value === 'unknown') return 'yellow' as const;
  if (value === 'clear' || value === 'low') return 'green' as const;
  return 'slate' as const;
}

function MissionMap({ worldState }: { worldState: WorldState }) {
  const alpha = worldState.teamPositions.alpha;
  const bravo = worldState.teamPositions.bravo;
  const riskyB7 =
    worldState.routeStatus['route-a']?.status === 'risky' ||
    worldState.routeStatus['route-a']?.status === 'blocked';
  const sectors = terrainMap.sectors;

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-950 p-3">
      <svg
        viewBox="0 0 100 100"
        className="h-[310px] w-full rounded-lg bg-[radial-gradient(circle_at_top_left,_rgba(34,211,238,0.16),_transparent_35%),linear-gradient(135deg,_#0f172a,_#020617)]"
      >
        <defs>
          <filter id="glow">
            <feGaussianBlur stdDeviation="1.4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <polyline
          points="12,70 34,52 58,42 84,56"
          fill="none"
          stroke={riskyB7 ? '#fb7185' : '#22c55e'}
          strokeWidth="2.5"
          strokeDasharray="4 2"
        />
        <polyline
          points="12,70 42,82 84,56"
          fill="none"
          stroke="#38bdf8"
          strokeWidth="2.5"
          strokeDasharray="2 3"
        />
        {sectors.map((sector) => (
          <g key={sector.id}>
            <circle
              cx={sector.coordinates.x}
              cy={sector.coordinates.y}
              r="7"
              fill={sector.id === 'B7' && riskyB7 ? '#7f1d1d' : '#1e293b'}
              stroke={sector.id === 'B7' && riskyB7 ? '#fb7185' : '#64748b'}
              strokeWidth="1.2"
            />
            <text
              x={sector.coordinates.x}
              y={sector.coordinates.y + 1.5}
              textAnchor="middle"
              className="fill-slate-100 text-[4px] font-bold"
            >
              {sector.id}
            </text>
            <text
              x={sector.coordinates.x}
              y={sector.coordinates.y + 11}
              textAnchor="middle"
              className="fill-slate-300 text-[3px]"
            >
              {sector.name}
            </text>
          </g>
        ))}
        <text x="20" y="64" className="fill-emerald-300 text-[3.5px] font-semibold">
          Route A
        </text>
        <text x="28" y="88" className="fill-cyan-300 text-[3.5px] font-semibold">
          Route C
        </text>
        {alpha?.coordinates && (
          <g filter="url(#glow)">
            <circle cx={alpha.coordinates.x} cy={alpha.coordinates.y} r="3.2" fill="#facc15" />
            <text
              x={alpha.coordinates.x + 4}
              y={alpha.coordinates.y - 2}
              className="fill-yellow-200 text-[4px] font-bold"
            >
              Alpha
            </text>
          </g>
        )}
        {bravo?.coordinates && (
          <g>
            <rect
              x={bravo.coordinates.x - 2.5}
              y={bravo.coordinates.y - 2.5}
              width="5"
              height="5"
              fill="#a78bfa"
            />
            <text
              x={bravo.coordinates.x + 4}
              y={bravo.coordinates.y - 2}
              className="fill-violet-200 text-[4px] font-bold"
            >
              Bravo
            </text>
          </g>
        )}
      </svg>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-300">
        <Pill tone="green">Route A planned path</Pill>
        <Pill tone="cyan">Route C fallback</Pill>
        <Pill tone={riskyB7 ? 'red' : 'slate'}>
          B7 risk {riskyB7 ? 'elevated' : 'not elevated yet'}
        </Pill>
      </div>
    </div>
  );
}

async function persistMissionState(worldState: WorldState, injectedEvents: MissionEvent[]) {
  await fetch('/api/mission/state', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ action: 'set', worldState, injectedEvents }),
  }).catch(() => undefined);
}

export default function DashboardPage() {
  const [worldState, setWorldState] = useState<WorldState>(() => resetWorldState());
  const [injectedEvents, setInjectedEvents] = useState<MissionEvent[]>([]);
  const nextEvent = scriptedMissionEvents[injectedEvents.length];

  const injectEvent = (event: MissionEvent) => {
    setWorldState((current) => {
      const next = applyEventToWorldState(current, event);
      const events = [...injectedEvents, event];
      void persistMissionState(next, events);
      return next;
    });
    setInjectedEvents((current) => [...current, event]);
  };

  const injectNext = () => {
    if (nextEvent) injectEvent(nextEvent);
  };

  const injectAll = () => {
    const remaining = scriptedMissionEvents.slice(injectedEvents.length);
    if (remaining.length === 0) return;
    const nextWorldState = remaining.reduce(applyEventToWorldState, worldState);
    const nextEvents = [...injectedEvents, ...remaining];
    setWorldState(nextWorldState);
    setInjectedEvents(nextEvents);
    void persistMissionState(nextWorldState, nextEvents);
  };

  const resetMission = () => {
    const next = resetWorldState();
    setWorldState(next);
    setInjectedEvents([]);
    void fetch('/api/mission/state', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ action: 'reset' }),
    });
  };

  const rosterById = useMemo(
    () => new Map(teamContext.members.map((member) => [member.id, member])),
    []
  );

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-5 text-slate-100">
      <header className="mb-5 flex flex-col gap-4 rounded-3xl border border-cyan-400/30 bg-slate-900/80 p-5 shadow-2xl shadow-cyan-950/30 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-sm font-semibold tracking-[0.32em] text-cyan-300 uppercase">
            Live mission context, synthesized in real time.
          </p>
          <h1 className="mt-2 text-4xl font-black tracking-tight text-white">Mission Bay</h1>
          <p className="mt-1 text-lg text-slate-300">
            Real-time operating memory for high-pressure missions.
          </p>
          <p className="mt-2 text-sm text-slate-400">{missionContext.name}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone="green">Live/session status: demo ready</Pill>
          <Button variant="secondary" onClick={resetMission}>
            Reset Mission
          </Button>
          <Button onClick={injectNext} disabled={!nextEvent}>
            Inject Next Event
          </Button>
          <Button
            variant="outline"
            className="border-cyan-400/50 bg-cyan-400/10 text-cyan-100 hover:bg-cyan-400/20"
            onClick={injectAll}
          >
            Inject All Events
          </Button>
        </div>
      </header>

      <div className="grid gap-4 xl:grid-cols-[1.05fr_1.1fr_1.15fr]">
        <div className="space-y-4">
          <Panel title="Static Mission Context">
            <div className="space-y-4 text-sm text-slate-300">
              <div>
                <p className="font-semibold text-white">Primary objective</p>
                <p>{missionContext.objective.primary}</p>
              </div>
              <div>
                <p className="font-semibold text-white">Routes</p>
                <ul className="mt-1 space-y-1">
                  {missionContext.routes.map((route) => (
                    <li key={route.id}>
                      <span className="text-cyan-200">{route.name}</span>: {route.notes}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="font-semibold text-white">Team roster</p>
                <ul className="mt-1 grid gap-1 sm:grid-cols-2">
                  {teamContext.members.map((member) => (
                    <li key={member.id}>
                      {member.callSign}: {member.role}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="font-semibold text-white">Key constraints</p>
                <ul className="mt-1 space-y-1">
                  {missionContext.constraints.map((constraint) => (
                    <li key={constraint.id} className="flex gap-2">
                      <Pill tone={toneForUrgency(constraint.priority)}>{constraint.priority}</Pill>
                      <span>{constraint.description}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </Panel>

          <Panel title="Retrieved Evidence">
            <p className="text-sm text-slate-300">
              When the voice agent searches Moss, retrieved mission evidence appears in the voice
              session UI. Use this panel as the operator reminder to ground answers in static
              context, live events, and current world state.
            </p>
            <div className="mt-3 rounded-lg border border-slate-700 bg-slate-950 p-3 text-xs text-slate-400">
              Try from /mobile: “What is Sector B7?” or “Who can handle comms?”
            </div>
          </Panel>
        </div>

        <div className="space-y-4">
          <Panel title="Map / Team Positions">
            <MissionMap worldState={worldState} />
          </Panel>

          <Panel title="Live Event Stream">
            <div className="space-y-3">
              {injectedEvents.length === 0 && (
                <p className="text-sm text-slate-400">
                  No live events injected yet. The original plan still marks Route A as low risk.
                </p>
              )}
              {injectedEvents.map((event) => (
                <article
                  key={event.id}
                  className="rounded-xl border border-slate-700 bg-slate-950 p-3"
                >
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Pill tone="cyan">
                      {new Date(event.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </Pill>
                    <Pill>{event.source.name}</Pill>
                    <Pill>{event.eventType}</Pill>
                    <Pill tone={toneForUrgency(event.urgency)}>{event.urgency}</Pill>
                    <Pill>{Math.round(event.confidence * 100)}% confidence</Pill>
                  </div>
                  <p className="text-sm text-slate-200">{event.summary}</p>
                </article>
              ))}
            </div>
          </Panel>
        </div>

        <Panel
          title="Current World State"
          className="xl:sticky xl:top-5 xl:max-h-[calc(100vh-2.5rem)] xl:overflow-y-auto"
        >
          <div className="space-y-5 text-sm">
            <div>
              <p className="font-semibold text-cyan-100">Current objective</p>
              <p className="mt-1 rounded-lg bg-slate-950 p-3 text-slate-200">
                {worldState.currentObjective}
              </p>
            </div>
            <div>
              <p className="font-semibold text-cyan-100">Team positions</p>
              <div className="mt-2 grid gap-2">
                {Object.entries(worldState.teamPositions).map(([teamId, position]) => (
                  <div key={teamId} className="rounded-lg border border-slate-700 bg-slate-950 p-3">
                    <span className="font-semibold text-white capitalize">{teamId}</span> in{' '}
                    {position.sectorId} · {position.status} · last update{' '}
                    {new Date(position.lastUpdated).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="font-semibold text-cyan-100">Route status</p>
              <div className="mt-2 space-y-2">
                {Object.entries(worldState.routeStatus).map(([routeId, route]) => (
                  <div
                    key={routeId}
                    className="rounded-lg border border-slate-700 bg-slate-950 p-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-white uppercase">
                        {routeId.replace('-', ' ')}
                      </span>
                      <Pill tone={toneForUrgency(route.status)}>{route.status}</Pill>
                      <Pill>{Math.round(route.confidence * 100)}% confidence</Pill>
                    </div>
                    <p className="mt-2 text-slate-300">{route.reason}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      Evidence: {route.supportingEventIds.join(', ') || 'original plan only'}
                    </p>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="font-semibold text-cyan-100">Known risks</p>
              <div className="mt-2 space-y-2">
                {worldState.knownRisks.length === 0 ? (
                  <p className="text-slate-400">No live risks yet.</p>
                ) : (
                  worldState.knownRisks.map((risk) => (
                    <div
                      key={risk.id}
                      className="rounded-lg border border-rose-500/30 bg-rose-950/30 p-3"
                    >
                      <Pill tone={toneForUrgency(risk.urgency)}>{risk.urgency}</Pill>
                      <p className="mt-2 text-slate-200">{risk.summary}</p>
                      <p className="mt-1 text-xs text-slate-400">
                        Sector {risk.sectorId ?? 'unknown'} · {Math.round(risk.confidence * 100)}%
                        confidence
                      </p>
                    </div>
                  ))
                )}
              </div>
            </div>
            <div>
              <p className="font-semibold text-cyan-100">Recent changes</p>
              <ol className="mt-2 space-y-2">
                {worldState.recentChanges.length === 0 ? (
                  <li className="text-slate-400">No changes from the baseline plan.</li>
                ) : (
                  worldState.recentChanges.map((change) => (
                    <li
                      key={change.id}
                      className="rounded-lg border border-slate-700 bg-slate-950 p-3"
                    >
                      <Pill tone={toneForUrgency(change.significance)}>{change.significance}</Pill>
                      <p className="mt-2 text-slate-200">{change.summary}</p>
                    </li>
                  ))
                )}
              </ol>
            </div>
            <div>
              <p className="font-semibold text-cyan-100">Open questions</p>
              <div className="mt-2 space-y-2">
                {worldState.openQuestions.map((question) => (
                  <div
                    key={question.id}
                    className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-3"
                  >
                    <Pill tone={toneForUrgency(question.priority)}>{question.priority}</Pill>
                    <p className="mt-2 font-medium text-slate-100">{question.question}</p>
                    <p className="mt-1 text-slate-400">{question.whyItMatters}</p>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="font-semibold text-cyan-100">Units</p>
              <div className="mt-2 space-y-2">
                {teamContext.units.map((unit) => (
                  <div
                    key={unit.id}
                    className="rounded-lg border border-slate-700 bg-slate-950 p-3"
                  >
                    <span className="font-semibold text-white">{unit.name}</span>
                    <p className="text-slate-300">{unit.assignment}</p>
                    <p className="text-xs text-slate-500">
                      Members:{' '}
                      {unit.members.map((id) => rosterById.get(id)?.callSign ?? id).join(', ')}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Panel>
      </div>
    </main>
  );
}
