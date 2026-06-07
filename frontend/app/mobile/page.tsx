'use client';

import { type CSSProperties, useMemo } from 'react';
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

function MobileSession() {
  useDebugMode({ enabled: process.env.NODE_ENV !== 'production' });
  useAgentErrors();
  const session = useSessionContext();
  const { state: agentState } = useAgent();
  const { messages } = useSessionMessages(session);

  const status = !session.isConnected ? 'disconnected' : agentState || 'connected';

  return (
    <main className="flex min-h-svh flex-col bg-slate-950 px-5 py-6 text-slate-100">
      <header className="rounded-[2rem] border border-cyan-400/30 bg-slate-900 p-5 shadow-2xl shadow-cyan-950/30">
        <p className="text-xs font-semibold tracking-[0.28em] text-cyan-300 uppercase">
          Live mission context
        </p>
        <h1 className="mt-2 text-4xl font-black tracking-tight">Mission Bay</h1>
        <p className="mt-2 text-sm text-slate-300">Voice access for Operation Checkpoint Echo.</p>
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

        {!session.isConnected ? (
          <Button
            size="lg"
            className="mt-5 h-16 w-full rounded-2xl text-lg"
            onClick={() => void session.start()}
          >
            Connect to Mission Bay
          </Button>
        ) : (
          <Button
            size="lg"
            variant="secondary"
            className="mt-5 h-14 w-full rounded-2xl text-base"
            onClick={() => void session.end()}
          >
            Disconnect
          </Button>
        )}

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

      <section className="mt-5 min-h-0 flex-1 rounded-[2rem] border border-slate-700 bg-slate-900 p-3">
        <div className="mb-2 px-2 pt-2">
          <h2 className="font-semibold text-cyan-100">Transcript</h2>
          <p className="text-xs text-slate-400">Try: “Catch me up” or “Who can handle comms?”</p>
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

export default function MobilePage() {
  const tokenSource = useMemo(() => {
    return typeof process.env.NEXT_PUBLIC_CONN_DETAILS_ENDPOINT === 'string'
      ? getSandboxTokenSource(APP_CONFIG_DEFAULTS)
      : TokenSource.endpoint('/api/token');
  }, []);
  const session = useSession(
    tokenSource,
    APP_CONFIG_DEFAULTS.agentName ? { agentName: APP_CONFIG_DEFAULTS.agentName } : undefined
  );

  return (
    <AgentSessionProvider session={session}>
      <MobileSession />
    </AgentSessionProvider>
  );
}
