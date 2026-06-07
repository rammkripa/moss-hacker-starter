'use client';

import { useState } from 'react';
import { SECTOR_COORDS } from '@/lib/mission/demo-events';
import type { MissionEvent } from '@/lib/mission/types';

type Status = { kind: 'idle' } | { kind: 'busy'; msg: string } | { kind: 'done'; event: MissionEvent } | { kind: 'error'; msg: string };

type Props = {
  onParsed: (event: MissionEvent, label: string) => void;
};

const SECTOR_OPTIONS = Object.entries(SECTOR_COORDS);

export function DroneUpload({ onParsed }: Props) {
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const [sectorId, setSectorId] = useState<string>('M4');
  const [submitterId, setSubmitterId] = useState<string>('drone');

  const handleFile = async (file: File) => {
    setStatus({ kind: 'busy', msg: 'Parsing image with vision model…' });
    const form = new FormData();
    form.append('image', file);
    form.append('submitter_id', submitterId);
    form.append(
      'location_hint',
      `${sectorId} — ${SECTOR_COORDS[sectorId]?.label ?? 'unknown sector'}`,
    );
    try {
      const res = await fetch('/api/mission/ingest/photo', { method: 'POST', body: form });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setStatus({ kind: 'error', msg: `HTTP ${res.status}: ${body.error ?? 'unknown error'}` });
        return;
      }
      const body = await res.json();
      const parsed = body.event as MissionEvent;
      // If the vision parser couldn't fix coords, attribute to the chosen sector.
      const coord = SECTOR_COORDS[sectorId];
      if (parsed.location && !parsed.location.coordinates && coord) {
        parsed.location.coordinates = { x: coord.lng, y: coord.lat };
        parsed.location.sectorId = sectorId;
      }
      setStatus({ kind: 'done', event: parsed });
      onParsed(parsed, `Drone: ${parsed.summary.slice(0, 60)}…`);
    } catch (err) {
      setStatus({ kind: 'error', msg: err instanceof Error ? err.message : String(err) });
    }
  };

  return (
    <section className="rounded-2xl border border-cyan-400/20 bg-slate-900 p-5">
      <h2 className="mb-4 text-sm font-semibold tracking-[0.18em] text-cyan-300 uppercase">
        Drone still upload
      </h2>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 mb-4">
        <label className="flex flex-col gap-1.5">
          <span className="text-[10px] uppercase tracking-widest text-slate-400">Sector hint</span>
          <select
            value={sectorId}
            onChange={(e) => setSectorId(e.target.value)}
            className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
            disabled={status.kind === 'busy'}
          >
            {SECTOR_OPTIONS.map(([sid, s]) => (
              <option key={sid} value={sid}>
                {sid} — {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-[10px] uppercase tracking-widest text-slate-400">Submitter</span>
          <input
            type="text"
            value={submitterId}
            onChange={(e) => setSubmitterId(e.target.value)}
            placeholder="e.g. drone, Alpha"
            className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
            disabled={status.kind === 'busy'}
          />
        </label>
      </div>

      <input
        type="file"
        id="dashboard-drone-input"
        accept="image/jpeg,image/png,image/webp"
        className="hidden"
        disabled={status.kind === 'busy'}
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (file) await handleFile(file);
          e.target.value = '';
        }}
      />
      <label
        htmlFor="dashboard-drone-input"
        className={`block w-full rounded-2xl border border-cyan-400/30 bg-slate-950 py-4 text-center text-sm font-medium text-cyan-100 ${
          status.kind === 'busy' ? 'opacity-60' : 'hover:bg-cyan-400/10 cursor-pointer'
        }`}
      >
        {status.kind === 'busy' ? status.msg : 'Choose image (JPG/PNG/WebP, ≤8MB)'}
      </label>

      {status.kind === 'done' && (
        <div className="mt-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs">
          <div className="font-semibold text-emerald-200">
            Parsed: {status.event.eventType} · urgency {status.event.urgency}
          </div>
          <div className="mt-1 text-slate-200 leading-relaxed">{status.event.summary}</div>
          <div className="mt-2 text-[10px] text-slate-500">
            Confidence {(status.event.confidence * 100).toFixed(0)}% ·{' '}
            {status.event.location?.sectorId ?? status.event.location?.description ?? 'no location'}
          </div>
        </div>
      )}

      {status.kind === 'error' && (
        <div className="mt-3 rounded-xl border border-rose-500/30 bg-rose-500/5 p-3 text-xs text-rose-200">
          {status.msg}
        </div>
      )}
    </section>
  );
}
