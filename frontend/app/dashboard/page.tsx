'use client';

import dynamic from 'next/dynamic';
import { type ReactNode, useState } from 'react';
import { DEMO_EVENTS, SECTOR_COORDS, type DemoEvent } from '@/lib/mission/demo-events';
import type { MissionEvent } from '@/lib/mission/types';
import { DroneUpload } from '@/components/dashboard/drone-upload';

// Map uses Leaflet which depends on `window`; load it client-side only.
const MissionMap = dynamic(
  () => import('@/components/dashboard/mission-map').then((m) => m.MissionMap),
  { ssr: false, loading: () => <div className="h-[60vh] rounded-2xl border border-slate-700 bg-slate-900/40" /> },
);

type PinEvent = {
  id: string;
  ts: number;
  label: string;
  lat: number;
  lng: number;
  tone: 'green' | 'amber' | 'rose' | 'cyan' | 'slate';
};

type Log = {
  id: string;
  ts: string;
  label: string;
  status: 'pending' | 'ok' | 'error';
  detail?: string;
};

const TONE_CLASSES: Record<DemoEvent['tone'], string> = {
  slate: 'border-slate-700 bg-slate-900 hover:bg-slate-800',
  green: 'border-emerald-500/40 bg-emerald-500/5 hover:bg-emerald-500/10',
  amber: 'border-amber-500/40 bg-amber-500/5 hover:bg-amber-500/10',
  rose: 'border-rose-500/40 bg-rose-500/5 hover:bg-rose-500/10',
  cyan: 'border-cyan-500/40 bg-cyan-500/5 hover:bg-cyan-500/10',
};

function Pill({ children, tone = 'slate' }: { children: ReactNode; tone?: DemoEvent['tone'] }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${TONE_CLASSES[tone]} text-slate-100`}>
      {children}
    </span>
  );
}

async function postEvent(event: MissionEvent): Promise<void> {
  const res = await fetch('/api/mission/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event }),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '(no body)');
    throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
  }
}

export default function DashboardPage() {
  const [logs, setLogs] = useState<Log[]>([]);
  const [pins, setPins] = useState<PinEvent[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const inject = async (demo: DemoEvent) => {
    if (busy) return;
    const event = demo.build();
    const log: Log = {
      id: event.id,
      ts: new Date().toLocaleTimeString(),
      label: demo.label,
      status: 'pending',
    };
    setBusy(event.id);
    setLogs((cur) => [log, ...cur].slice(0, 30));
    // Drop a pin on the map if the event has coords.
    const c = event.location?.coordinates;
    if (c) {
      setPins((cur) =>
        [
          {
            id: event.id,
            ts: Date.now(),
            label: demo.label,
            lat: c.y,
            lng: c.x,
            tone: demo.tone,
          },
          ...cur,
        ].slice(0, 12),
      );
    }
    try {
      await postEvent(event);
      setLogs((cur) => cur.map((l) => (l.id === event.id ? { ...l, status: 'ok' } : l)));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setLogs((cur) => cur.map((l) => (l.id === event.id ? { ...l, status: 'error', detail: msg } : l)));
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-8 text-slate-100">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8">
          <p className="text-xs font-semibold tracking-[0.28em] text-cyan-300 uppercase">
            Operation South Beach &mdash; EXCON injection panel
          </p>
          <h1 className="mt-2 text-4xl font-black tracking-tight">Mission Bay Dashboard</h1>
          <p className="mt-3 max-w-2xl text-sm text-slate-300">
            Operation Pier Glass &mdash; Mission Bay, San Francisco. Click an
            event below to push it to{' '}
            <code className="rounded bg-slate-800 px-1.5 py-0.5">/api/mission/ingest</code>{' '}
            &rarr; Moss <code className="rounded bg-slate-800 px-1.5 py-0.5">events</code>{' '}
            index + LiveKit room. Soldier GPS is reported from{' '}
            <code className="rounded bg-slate-800 px-1.5 py-0.5">/mobile</code>.
          </p>
        </header>

        <section className="mb-8">
          <h2 className="mb-3 text-sm font-semibold tracking-[0.18em] text-cyan-300 uppercase">
            AO map &mdash; Mission Bay, SF
          </h2>
          <MissionMap pinEvents={pins} />
          <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-400">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full bg-cyan-400" /> M1 — Alpha start (UCSF)
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full bg-violet-400" /> M5 — Bravo (Chase Center)
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full bg-rose-500" /> M4 — Risky central
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full bg-emerald-500" /> W1 — Waterfront fallback
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full bg-yellow-400" /> P1 — Pier 50 extraction
            </span>
          </div>
        </section>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
          <section className="space-y-6">
            <DroneUpload
              onParsed={(event, label) => {
                const c = event.location?.coordinates;
                if (c) {
                  setPins((cur) =>
                    [
                      {
                        id: event.id,
                        ts: Date.now(),
                        label,
                        lat: c.y,
                        lng: c.x,
                        tone: (event.urgency === 'high' || event.urgency === 'critical'
                          ? 'rose'
                          : event.urgency === 'medium'
                            ? 'amber'
                            : 'cyan') as PinEvent['tone'],
                      },
                      ...cur,
                    ].slice(0, 12),
                  );
                }
                setLogs((cur) =>
                  [
                    {
                      id: event.id,
                      ts: new Date().toLocaleTimeString(),
                      label: `📷 ${label}`,
                      status: 'ok' as const,
                    },
                    ...cur,
                  ].slice(0, 30),
                );
              }}
            />

            <div>
            <h2 className="mb-4 text-sm font-semibold tracking-[0.18em] text-cyan-300 uppercase">
              Inject event
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {DEMO_EVENTS.map((demo) => (
                <button
                  key={demo.label}
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void inject(demo)}
                  className={`group rounded-2xl border p-4 text-left transition-colors disabled:opacity-50 ${TONE_CLASSES[demo.tone]}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="text-sm font-bold text-white">{demo.label}</div>
                    <Pill tone={demo.tone}>
                      {demo.tone === 'rose' ? 'High' : demo.tone === 'amber' ? 'Med' : 'Inject'}
                    </Pill>
                  </div>
                  <div className="mt-2 text-xs text-slate-300 leading-relaxed">{demo.hint}</div>
                </button>
              ))}
            </div>
            </div>
          </section>

          <aside>
            <h2 className="mb-4 text-sm font-semibold tracking-[0.18em] text-cyan-300 uppercase">
              Injection log
            </h2>
            <div className="space-y-2 max-h-[70vh] overflow-y-auto rounded-2xl border border-slate-800 bg-slate-900/40 p-3">
              {logs.length === 0 ? (
                <p className="text-xs text-slate-500">No events injected yet.</p>
              ) : (
                logs.map((log) => (
                  <div
                    key={log.id}
                    className="rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-white">{log.label}</span>
                      <span className={
                        log.status === 'ok'
                          ? 'text-emerald-400'
                          : log.status === 'error'
                            ? 'text-rose-400'
                            : 'text-slate-400'
                      }>
                        {log.status === 'pending' ? '…' : log.status === 'ok' ? '✓' : '✗'}
                      </span>
                    </div>
                    <div className="mt-1 text-slate-500">{log.ts} &middot; <span className="font-mono">{log.id.slice(0, 22)}…</span></div>
                    {log.detail && (
                      <div className="mt-1 text-rose-400 break-all">{log.detail}</div>
                    )}
                  </div>
                ))
              )}
            </div>

            <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/40 p-4 text-xs text-slate-300">
              <p className="font-semibold text-cyan-200 mb-2">Operation Pier Glass — demo flow</p>
              <ol className="list-decimal pl-5 space-y-1">
                <li>Connect <em>Alpha</em> (recon) on a phone — opens GPS tracking</li>
                <li>Connect <em>Bravo</em> (medic) on a second phone</li>
                <li>Click <em>1. Alpha starts moving</em></li>
                <li>Click <em>2. Bravo: smoke at 3rd &amp; Mission Rock</em></li>
                <li>Click <em>3. Alpha approaching M4 (RISKY)</em></li>
                <li>Click <em>4. Drone: waterfront may be clearer</em></li>
                <li>Click <em>5. Command: extraction priority</em></li>
                <li>Click <em>6. Bravo offers waterfront guidance</em></li>
                <li>Ask the agent: &ldquo;What changed? Where should I go?&rdquo;</li>
              </ol>
              <p className="mt-3 text-slate-500">
                Each click takes ~2-3s. Live phone GPS shows up as the cyan/violet
                soldier dots on the map.
              </p>
            </div>
          </aside>
        </div>
      </div>
    </main>
  );
}
