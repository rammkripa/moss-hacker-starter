import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { AccessToken, AgentDispatchClient, type AccessTokenOptions, type VideoGrant } from 'livekit-server-sdk';
import { randomUUID } from 'node:crypto';
import { RoomAgentDispatch, RoomConfiguration } from '@livekit/protocol';

type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
};

// NOTE: you are expected to define the following environment variables in `.env.local`:
const API_KEY = process.env.LIVEKIT_API_KEY;
const API_SECRET = process.env.LIVEKIT_API_SECRET;
const LIVEKIT_URL = process.env.LIVEKIT_URL;
// Agent dispatch name — must match the agent's registered name (`agent-py`). See `.env.local`.
const AGENT_NAME = process.env.AGENT_NAME;
const ROOM_NAME = process.env.LIVEKIT_ROOM_NAME ?? 'mission_bay_demo_room';

// httpOnly cookie that persists a stable per-user id across visits. Stamped into the agent
// dispatch metadata as `{ "user_id": <uuid> }` so the agent can scope its Moss memory per user.
const USER_COOKIE = 'lk_moss_user';
const USER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // 1 year

// don't cache the results
export const revalidate = 0;

export async function POST(req: Request) {
  try {
    if (LIVEKIT_URL === undefined) {
      throw new Error('LIVEKIT_URL is not defined');
    }
    if (API_KEY === undefined) {
      throw new Error('LIVEKIT_API_KEY is not defined');
    }
    if (API_SECRET === undefined) {
      throw new Error('LIVEKIT_API_SECRET is not defined');
    }

    // Resolve a stable per-user id from the httpOnly cookie, minting one on first visit.
    const cookieStore = await cookies();
    let userId = cookieStore.get(USER_COOKIE)?.value;
    const isNewUser = !userId;
    if (!userId) {
      userId = randomUUID();
    }

    // Parse room config and optional soldier identity from request body.
    // Body may be empty (some clients ping with no payload during health
    // checks or warmups) — fall back to an empty object rather than crashing.
    const body = await req.json().catch(() => ({} as Record<string, unknown>));
    const roomConfig = body?.room_config
      ? RoomConfiguration.fromJson(body.room_config, { ignoreUnknownFields: true })
      : new RoomConfiguration();

    // Extract soldier identity fields supplied by the pre-connect form in
    // /mobile/page.tsx. Both fields are optional; the agent falls back to its
    // own defaults when absent.
    const callsign: string = typeof body?.callsign === 'string' ? body.callsign.trim() : '';
    const role: string =
      body?.role === 'recon' || body?.role === 'medic' ? body.role : 'recon';

    // Derive unit from role using the same defaults as the Python agent.
    const unitByRole: Record<string, string> = { recon: 'bravo', medic: 'alpha' };
    const unit: string = unitByRole[role] ?? 'bravo';

    // Pack the full soldier profile + user_id into the agent dispatch metadata.
    // The Python agent reads this via ctx.job.metadata.
    const dispatchMetadata = JSON.stringify({
      user_id: userId,
      callsign: callsign || (role === 'medic' ? 'Bravo' : 'Alpha'),
      role,
      unit,
      current_sector: callsign && callsign.toLowerCase() === 'bravo' ? 'M5' : 'M1',
    });

    // Stamp dispatch metadata onto all agent entries.  Ensure an agent dispatch
    // entry exists (using AGENT_NAME for explicit dispatch) and preserve any
    // agent name already supplied by the client.
    if (roomConfig.agents.length === 0) {
      roomConfig.agents.push(new RoomAgentDispatch({ agentName: AGENT_NAME ?? '' }));
    }
    for (const agent of roomConfig.agents) {
      if (!agent.agentName && AGENT_NAME) {
        agent.agentName = AGENT_NAME;
      }
      agent.metadata = dispatchMetadata;
    }

    // Use callsign as the participant display name so the LiveKit room roster
    // shows human-readable names instead of random UUIDs.
    const participantName = callsign || 'soldier';
    const participantIdentity = `soldier_${role}_${Math.floor(Math.random() * 10_000)}`;
    const roomName = ROOM_NAME;

    const participantToken = await createParticipantToken(
      { identity: participantIdentity, name: participantName },
      roomName,
      roomConfig
    );

    // Explicitly dispatch the agent via the AgentDispatch API.
    //
    // Why: agent dispatch in a join token is honored ONLY at room creation.
    // If the room already exists (e.g., feed worker or prior session created
    // it), the token's dispatch is silently ignored.
    // AgentDispatchClient.createDispatch works for both new and existing rooms.
    //
    // We listDispatch first so we don't spawn duplicate agents when the
    // frontend hits /api/token more than once (React strict mode, reconnect,
    // remount). One dispatch per room is what we want.
    //
    // Docs: https://docs.livekit.io/agents/server/agent-dispatch/
    if (AGENT_NAME) {
      try {
        const dispatchClient = new AgentDispatchClient(LIVEKIT_URL, API_KEY, API_SECRET);
        const existing = await dispatchClient.listDispatch(roomName).catch(() => []);
        const hasMine = existing.some((d) => d.agentName === AGENT_NAME);
        if (!hasMine) {
          await dispatchClient.createDispatch(roomName, AGENT_NAME, {
            metadata: dispatchMetadata,
          });
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        if (!msg.toLowerCase().includes('already')) {
          console.warn('[token] AgentDispatch wiring failed:', msg);
        }
      }
    }

    // Return connection details
    const data: ConnectionDetails = {
      serverUrl: LIVEKIT_URL,
      roomName,
      participantName,
      participantToken,
    };
    const headers = new Headers({
      'Cache-Control': 'no-store',
    });
    const response = NextResponse.json(data, { headers });

    // Persist the per-user id for subsequent visits (only needs writing when freshly minted).
    if (isNewUser) {
      response.cookies.set(USER_COOKIE, userId, {
        httpOnly: true,
        sameSite: 'lax',
        secure: (process.env.NODE_ENV as string) === 'production',
        path: '/',
        maxAge: USER_COOKIE_MAX_AGE,
      });
    }

    return response;
  } catch (error) {
    if (error instanceof Error) {
      console.error(error);
      return new NextResponse(error.message, { status: 500 });
    }
  }
}

function createParticipantToken(
  userInfo: AccessTokenOptions,
  roomName: string,
  roomConfig: RoomConfiguration | undefined
): Promise<string> {
  const at = new AccessToken(API_KEY, API_SECRET, {
    ...userInfo,
    ttl: '15m',
  });
  const grant: VideoGrant = {
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canPublishData: true,
    canSubscribe: true,
  };
  at.addGrant(grant);

  if (roomConfig) {
    at.roomConfig = roomConfig;
  }

  return at.toJwt();
}
