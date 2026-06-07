'use client';

import { useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  CheckCircle2,
  FileArchive,
  FileText,
  FolderUp,
  Image,
  Loader2,
  Map,
  RadioTower,
  ShieldCheck,
  Upload,
  Users,
  X,
} from 'lucide-react';

type SlotId = 'briefing' | 'team' | 'objective' | 'map' | 'comms' | 'attachments';
type SlotState = 'empty' | 'queued' | 'processing' | 'ready';

type UploadSlot = {
  id: SlotId;
  title: string;
  eyebrow: string;
  accept: string;
  icon: typeof FileText;
  required: boolean;
};

type FileRecord = {
  name: string;
  size: number;
  type: string;
  state: SlotState;
};

const SLOTS: UploadSlot[] = [
  {
    id: 'briefing',
    title: 'Mission Briefing',
    eyebrow: 'PDF, DOCX, TXT',
    accept: '.pdf,.doc,.docx,.txt,.md',
    icon: FileText,
    required: true,
  },
  {
    id: 'team',
    title: 'Team Roster',
    eyebrow: 'CSV, XLSX, PDF',
    accept: '.csv,.xls,.xlsx,.pdf,.txt',
    icon: Users,
    required: true,
  },
  {
    id: 'objective',
    title: 'Objectives',
    eyebrow: 'PDF, DOCX, TXT',
    accept: '.pdf,.doc,.docx,.txt,.md',
    icon: ShieldCheck,
    required: true,
  },
  {
    id: 'map',
    title: 'AO Map',
    eyebrow: 'PNG, JPG, PDF, GEOJSON',
    accept: '.png,.jpg,.jpeg,.webp,.pdf,.geojson,.json',
    icon: Map,
    required: true,
  },
  {
    id: 'comms',
    title: 'Comms Plan',
    eyebrow: 'PDF, DOCX, TXT',
    accept: '.pdf,.doc,.docx,.txt,.md',
    icon: RadioTower,
    required: false,
  },
  {
    id: 'attachments',
    title: 'Supporting Files',
    eyebrow: 'Images, archives, notes',
    accept: '.zip,.png,.jpg,.jpeg,.webp,.pdf,.txt,.md',
    icon: FileArchive,
    required: false,
  },
];

const seededFiles: Partial<Record<SlotId, FileRecord>> = {
  briefing: {
    name: 'operation-pier-glass-briefing.pdf',
    size: 1240000,
    type: 'application/pdf',
    state: 'ready',
  },
  team: {
    name: 'alpha-bravo-roster.csv',
    size: 82000,
    type: 'text/csv',
    state: 'ready',
  },
};

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function statusText(state: SlotState): string {
  if (state === 'ready') return 'Ready';
  if (state === 'processing') return 'Indexing';
  if (state === 'queued') return 'Queued';
  return 'Waiting';
}

function SlotStatus({ state }: { state: SlotState }) {
  if (state === 'processing') {
    return <Loader2 className="size-4 animate-spin text-cyan-300" aria-hidden="true" />;
  }
  if (state === 'ready') {
    return <CheckCircle2 className="size-4 text-emerald-300" aria-hidden="true" />;
  }
  return <Upload className="size-4 text-slate-500" aria-hidden="true" />;
}

export default function StartMissionPage() {
  const router = useRouter();
  const [files, setFiles] = useState<Partial<Record<SlotId, FileRecord>>>(seededFiles);
  const [launching, setLaunching] = useState(false);
  const inputs = useRef<Partial<Record<SlotId, HTMLInputElement | null>>>({});

  const requiredReady = useMemo(
    () => SLOTS.filter((slot) => slot.required).every((slot) => files[slot.id]?.state === 'ready'),
    [files]
  );
  const readyCount = useMemo(
    () => SLOTS.filter((slot) => files[slot.id]?.state === 'ready').length,
    [files]
  );

  const receiveFile = (slot: UploadSlot, selected: File | undefined) => {
    if (!selected) return;
    setFiles((current) => ({
      ...current,
      [slot.id]: {
        name: selected.name,
        size: selected.size,
        type: selected.type || 'application/octet-stream',
        state: 'processing',
      },
    }));

    window.setTimeout(
      () => {
        setFiles((current) => {
          const existing = current[slot.id];
          if (!existing || existing.name !== selected.name) return current;
          return {
            ...current,
            [slot.id]: { ...existing, state: 'ready' },
          };
        });
      },
      700 + Math.round(Math.random() * 900)
    );
  };

  const removeFile = (slotId: SlotId) => {
    setFiles((current) => {
      const next = { ...current };
      delete next[slotId];
      return next;
    });
  };

  const launchMission = () => {
    setLaunching(true);
    window.setTimeout(() => {
      router.push('/dashboard?mission=operation-pier-glass');
    }, 900);
  };

  return (
    <main className="min-h-screen bg-slate-950 px-5 py-8 text-slate-100 md:px-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-8">
        <header className="grid gap-5 border-b border-slate-800 pb-6 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <p className="text-xs font-semibold tracking-[0.28em] text-cyan-300 uppercase">
              Mission Bay Intake
            </p>
            <h1 className="mt-3 text-4xl font-black tracking-tight md:text-5xl">
              Start Operation Pier Glass
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
              Assemble the starter packet for the live mission workspace.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="border border-slate-800 bg-slate-900 px-4 py-3">
              <div className="text-2xl font-black text-white">{readyCount}</div>
              <div className="mt-1 text-[10px] font-semibold tracking-widest text-slate-500 uppercase">
                Files
              </div>
            </div>
            <div className="border border-slate-800 bg-slate-900 px-4 py-3">
              <div className="text-2xl font-black text-emerald-300">
                {requiredReady ? 'Go' : 'Hold'}
              </div>
              <div className="mt-1 text-[10px] font-semibold tracking-widest text-slate-500 uppercase">
                Gate
              </div>
            </div>
            <div className="border border-slate-800 bg-slate-900 px-4 py-3">
              <div className="text-2xl font-black text-cyan-300">M4</div>
              <div className="mt-1 text-[10px] font-semibold tracking-widest text-slate-500 uppercase">
                Focus
              </div>
            </div>
          </div>
        </header>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {SLOTS.map((slot) => {
            const record = files[slot.id];
            const state = record?.state ?? 'empty';
            const Icon = slot.icon;
            return (
              <div key={slot.id} className="min-h-[190px] border border-slate-800 bg-slate-900 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="grid size-10 shrink-0 place-items-center border border-cyan-400/30 bg-cyan-400/10">
                      <Icon className="size-5 text-cyan-200" aria-hidden="true" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-sm font-bold text-white">{slot.title}</h2>
                        {slot.required && (
                          <span className="border border-amber-400/30 px-1.5 py-0.5 text-[10px] font-semibold text-amber-200 uppercase">
                            Required
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-[10px] font-semibold tracking-widest text-slate-500 uppercase">
                        {slot.eyebrow}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <SlotStatus state={state} />
                    <span>{statusText(state)}</span>
                  </div>
                </div>

                <input
                  ref={(node) => {
                    inputs.current[slot.id] = node;
                  }}
                  type="file"
                  accept={slot.accept}
                  className="hidden"
                  onChange={(event) => {
                    receiveFile(slot, event.target.files?.[0]);
                    event.target.value = '';
                  }}
                />

                {record ? (
                  <div className="mt-5 flex min-h-[82px] items-start justify-between gap-3 border border-slate-800 bg-slate-950 p-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-slate-100">
                        {record.name}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
                        <span>{formatBytes(record.size)}</span>
                        <span>{record.type || 'file'}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      aria-label={`Remove ${slot.title}`}
                      onClick={() => removeFile(slot.id)}
                      className="grid size-8 shrink-0 place-items-center border border-slate-700 text-slate-400 hover:border-rose-400/50 hover:text-rose-200"
                    >
                      <X className="size-4" aria-hidden="true" />
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => inputs.current[slot.id]?.click()}
                    className="mt-5 flex min-h-[82px] w-full items-center justify-center gap-2 border border-dashed border-slate-700 bg-slate-950 px-3 text-sm font-semibold text-cyan-100 hover:border-cyan-400/60 hover:bg-cyan-400/10"
                  >
                    <FolderUp className="size-4" aria-hidden="true" />
                    Upload
                  </button>
                )}
              </div>
            );
          })}
        </section>

        <section className="grid gap-4 border border-slate-800 bg-slate-900 p-5 lg:grid-cols-[1fr_auto] lg:items-center">
          <div className="flex items-start gap-3">
            <div className="grid size-10 shrink-0 place-items-center border border-emerald-400/30 bg-emerald-400/10">
              <Image className="size-5 text-emerald-200" aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white">Mission Workspace</h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-300">
                Operation packet staged for dashboard handoff. Live context will use the current
                demo state.
              </p>
            </div>
          </div>
          <button
            type="button"
            disabled={!requiredReady || launching}
            onClick={launchMission}
            className="inline-flex h-12 items-center justify-center gap-2 border border-emerald-400/40 bg-emerald-400 px-5 text-sm font-black text-slate-950 transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-800 disabled:text-slate-500"
          >
            {launching ? (
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <CheckCircle2 className="size-4" aria-hidden="true" />
            )}
            Enter Dashboard
          </button>
        </section>
      </div>
    </main>
  );
}
