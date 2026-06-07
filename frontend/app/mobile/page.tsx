'use client';

import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { TokenSource } from 'livekit-client';
import {
  useAgent,
  useSession,
  useSessionContext,
  useSessionMessages,
} from '@livekit/components-react';
import { WarningIcon } from '@phosphor-icons/react/dist/ssr';
import { APP_CONFIG_DEFAULTS } from '@/app-config';
import { AgentChatTranscript } from '@/components/agents-ui/agent-chat-transcript';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { StartAudioButton } from '@/components/agents-ui/start-audio-button';
import { Button } from '@/components/ui/button';
import { Toaster } from '@/components/ui/sonner';
import { useAgentErrors } from '@/hooks/useAgentErrors';
import { useDebugMode } from '@/hooks/useDebug';
import { getSandboxTokenSource } from '@/lib/utils';

type Role = 'recon' | 'medic';

// ---------------------------------------------------------------------------
// Pre-connect soldier identity form
// ---------------------------------------------------------------------------

interface SoldierFormProps {
  callsign: string;
  role: Role;
  onCallsignChange: (v: string) => void;
  onRoleChange: (v: Role) => void;
  onConnect: () => void;
}

function SoldierForm({
  callsign,
  role,
  onCallsignChange,
  onRoleChange,
  onConnect,
}: SoldierFormProps) {
  return (
    <div className="mt-5 rounded-[2rem] border border-cyan-400/20 bg-slate-900 p-5">
      <p className="text-xs font-semibold tracking-[0.2em] text-cyan-300 uppercase mb-4">
        Soldier identity
      </p>

      <label className="block mb-3">
        <span className="text-xs text-slate-400 mb-1 block">Callsign</span>
        <input
          type="text"
          value={callsign}
          onChange={(e) => onCallsignChange(e.target.value)}
          placeholder="Alpha or Bravo"
          className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
        />
      </label>

      <label className="block mb-5">
        <span className="text-xs text-slate-400 mb-1 block">Role</span>
        <select
          value={role}
          onChange={(e) => onRoleChange(e.target.value as Role)}
          className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white focus:border-cyan-500 focus:outline-none"
        >
          <option value="recon">Recon (Unit: Bravo)</option>
          <option value="medic">Medic (Unit: Alpha)</option>
        </select>
      </label>

      <p className="rounded-2xl border border-amber-400/30 bg-amber-400/5 p-3 text-xs leading-relaxed text-amber-100 mb-4">
        Training exercise. Mission Bay is decision support only. It does not
        direct lethal action and does not identify individual persons from
        imagery.
      </p>

      <Button
        size="lg"
        className="h-14 w-full rounded-2xl text-base"
        onClick={onConnect}
        disabled={!callsign.trim()}
      >
        Connect to Mission Bay
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Photo upload widget
// ---------------------------------------------------------------------------

function PhotoUpload({ callsign }: { callsign: string }) {
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <section className="mt-5 rounded-[2rem] border border-cyan-400/20 bg-slate-900 p-5">
      <p className="text-xs font-semibold tracking-[0.2em] text-cyan-300 uppercase mb-3">
        Submit drone still / field photo
      </p>
      <input
        type="file"
        accept="image/jpeg,image/png,image/webp"
        capture="environment"
        id="photo-input"
        className="hidden"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          setBusy(true);
          setStatus('Parsing image...');
          const form = new FormData();
          form.append('image', file);
          form.append('submitter_id', callsign);
          try {
            const res = await fetch('/api/mission/ingest/photo', {
              method: 'POST',
              body: form,
            });
            if (res.ok) {
              const body = await res.json();
              setStatus(`Submitted: ${body.event?.summary ?? '(no summary)'}`);
            } else {
              const body = await res.json().catch(() => ({}));
              setStatus(
                `Submit failed (${res.status}): ${body.error ?? 'unknown error'}`
              );
            }
          } catch (err) {
            setStatus(`Submit failed: ${String(err)}`);
          } finally {
            setBusy(false);
            e.target.value = '';
          }
        }}
      />
      <label
        htmlFor="photo-input"
        className={`block w-full rounded-2xl border border-cyan-400/30 bg-slate-950 py-4 text-center text-sm font-medium text-cyan-100 ${
          busy ? 'opacity-60' : 'hover:bg-cyan-400/10 cursor-pointer'
        }`}
      >
        {busy ? 'Working...' : 'Take or choose photo'}
      </label>
      {status && (
        <p className="mt-3 text-xs text-slate-300 leading-relaxed">{status}</p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Connected session view
// ---------------------------------------------------------------------------

function useGpsBroadcast(callsign: string, role: string, enabled: boolean) {
  const lastSentRef = useRef(0);
  const [last, setLast] = useState<{ lat: number; lng: number; accuracy?: number } | null>(null);

  useEffect(() => {
    if (!enabled || typeof navigator === 'undefined' || !navigator.geolocation) return;
    const id = navigator.geolocation.watchPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        const accuracy = pos.coords.accuracy;
        setLast({ lat, lng, accuracy });
        // Throttle to one POST per 4s to avoid hammering the ingest pipe.
        const now = Date.now();
        if (now - lastSentRef.current < 4000) return;
        lastSentRef.current = now;
        try {
          await fetch('/api/mission/position', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              callsign,
              role,
              lat,
              lng,
              accuracy,
              heading: pos.coords.heading ?? null,
              speed: pos.coords.speed ?? null,
              ts: new Date().toISOString(),
            }),
          });
        } catch {
          /* best-effort */
        }
      },
      undefined,
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [callsign, role, enabled]);

  return last;
}

function MobileSession({ callsign, role }: { callsign: string; role: Role }) {
  useDebugMode({ enabled: process.env.NODE_ENV !== 'production' });
  useAgentErrors();
  const session = useSessionContext();
  const { state: agentState } = useAgent();
  const { messages } = useSessionMessages(session);
  const gps = useGpsBroadcast(callsign, role, session.isConnected);

  const status = !session.isConnected ? 'disconnected' : agentState || 'connected';

  return (
    <main className="flex min-h-svh flex-col bg-slate-950 px-5 py-6 text-slate-100">
      <header className="rounded-[2rem] border border-cyan-400/30 bg-slate-900 p-5 shadow-2xl shadow-cyan-950/30">
        <p className="text-xs font-semibold tracking-[0.28em] text-cyan-300 uppercase">
          Live mission context
        </p>
        <h1 className="mt-2 text-4xl font-black tracking-tight">Mission Bay</h1>
        <p className="mt-2 text-sm text-slate-300">
          {callsign} &middot; {role} &mdash; Operation Pier Glass
        </p>
        {gps ? (
          <p className="mt-2 text-[10px] text-emerald-300 font-mono">
            GPS {gps.lat.toFixed(5)}, {gps.lng.toFixed(5)}
            {gps.accuracy ? ` (±${Math.round(gps.accuracy)}m)` : ''}
          </p>
        ) : (
          <p className="mt-2 text-[10px] text-slate-500 font-mono">
            GPS: waiting for fix… (allow location access when prompted)
          </p>
        )}
      </header>

      <section className="mt-5 rounded-[2rem] border border-slate-700 bg-slate-900 p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-slate-400">Voice status</p>
            <p className="mt-1 text-2xl font-bold text-white capitalize">{status}</p>
          </div>
          <span
            className={`h-4 w-4 rounded-full ${session.isConnected ? 'bg-emerald-400 shadow-[0_0_18px_#34d399]' : 'bg-slate-600'}`}
          />
        </div>

        <Button
          size="lg"
          variant="secondary"
          className="mt-5 h-14 w-full rounded-2xl text-base"
          onClick={() => void session.end()}
        >
          Disconnect
        </Button>

        <div className="mt-4 grid grid-cols-2 gap-2 text-center text-xs text-slate-300">
          {['disconnected', 'connected', 'listening', 'thinking', 'speaking'].map((item) => (
            <div
              key={item}
              className={`rounded-xl border px-2 py-2 capitalize ${status === item ? 'border-cyan-400 bg-cyan-400/10 text-cyan-100' : 'border-slate-700 bg-slate-950'}`}
            >
              {item}
            </div>
          ))}
        </div>
      </section>

      <PhotoUpload callsign={callsign} />

      <section className="mt-5 min-h-0 flex-1 rounded-[2rem] border border-slate-700 bg-slate-900 p-3">
        <div className="mb-2 px-2 pt-2">
          <h2 className="font-semibold text-cyan-100">Transcript</h2>
          <p className="text-xs text-slate-400">Try: &ldquo;Catch me up&rdquo; or &ldquo;What is sector A four like right now?&rdquo;</p>
        </div>
        <AgentChatTranscript
          agentState={agentState}
          messages={messages}
          className="h-[42svh] rounded-2xl bg-slate-950 text-sm [&>div>div]:px-3 [&>div>div]:py-3"
        />
      </section>

      <StartAudioButton label="Enable audio" />
      <Toaster
        icons={{ warning: <WarningIcon weight="bold" /> }}
        position="top-center"
        className="toaster group"
        style={
          {
            '--normal-bg': 'var(--popover)',
            '--normal-text': 'var(--popover-foreground)',
            '--normal-border': 'var(--border)',
          } as CSSProperties
        }
      />
    </main>
  );
}

// ---------------------------------------------------------------------------
// Root page — pre-connect form gates entry to the session
// ---------------------------------------------------------------------------

export default function MobilePage() {
  const [callsign, setCallsign] = useState('');
  const [role, setRole] = useState<Role>('recon');
  const [connecting, setConnecting] = useState(false);

  const tokenSource = useMemo(() => {
    if (typeof process.env.NEXT_PUBLIC_CONN_DETAILS_ENDPOINT === 'string') {
      return getSandboxTokenSource(APP_CONFIG_DEFAULTS);
    }
    const fetcher = async (roomConfig?: object) => {
      const res = await fetch('/api/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          callsign: callsign.trim() || (role === 'medic' ? 'Bravo' : 'Alpha'),
          role,
          ...(roomConfig ? { room_config: roomConfig } : {}),
        }),
      });
      if (!res.ok) throw new Error(`Token fetch failed: ${res.status}`);
      return res.json() as Promise<{
        serverUrl: string;
        roomName: string;
        participantName: string;
        participantToken: string;
      }>;
    };
    return TokenSource.custom(fetcher as Parameters<typeof TokenSource.custom>[0]);
  }, [callsign, role]);

  const session = useSession(
    tokenSource,
    APP_CONFIG_DEFAULTS.agentName ? { agentName: APP_CONFIG_DEFAULTS.agentName } : undefined,
  );

  const handleConnect = useCallback(async () => {
    setConnecting(true);
    try {
      await session.start();
    } finally {
      setConnecting(false);
    }
  }, [session]);

  if (!session.isConnected && !connecting) {
    return (
      <main className="flex min-h-svh flex-col bg-slate-950 px-5 py-6 text-slate-100">
        <header className="rounded-[2rem] border border-cyan-400/30 bg-slate-900 p-5 shadow-2xl shadow-cyan-950/30">
          <p className="text-xs font-semibold tracking-[0.28em] text-cyan-300 uppercase">
            Live mission context
          </p>
          <h1 className="mt-2 text-4xl font-black tracking-tight">Mission Bay</h1>
          <p className="mt-2 text-sm text-slate-300">Operation South Beach &mdash; South Beach SF</p>
        </header>
        <SoldierForm
          callsign={callsign}
          role={role}
          onCallsignChange={setCallsign}
          onRoleChange={setRole}
          onConnect={() => void handleConnect()}
        />
        <Toaster
          icons={{ warning: <WarningIcon weight="bold" /> }}
          position="top-center"
          className="toaster group"
          style={
            {
              '--normal-bg': 'var(--popover)',
              '--normal-text': 'var(--popover-foreground)',
              '--normal-border': 'var(--border)',
            } as CSSProperties
          }
        />
      </main>
    );
  }

  return (
    <AgentSessionProvider session={session}>
      <MobileSession callsign={callsign || (role === 'medic' ? 'Bravo' : 'Alpha')} role={role} />
    </AgentSessionProvider>
  );
}
