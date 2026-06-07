'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Marker, Popup, Polyline } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { SECTOR_COORDS } from '@/lib/mission/demo-events';

// Sector tone helper.
const SECTOR_TONE: Record<string, { fill: string; border: string }> = {
  M1: { fill: '#38bdf8', border: '#0284c7' },  // cyan — Alpha start
  M2: { fill: '#94a3b8', border: '#475569' },
  M3: { fill: '#94a3b8', border: '#475569' },
  M4: { fill: '#f43f5e', border: '#be123c' },  // rose — RISKY
  M5: { fill: '#a78bfa', border: '#7c3aed' },  // violet — Bravo position
  M6: { fill: '#f59e0b', border: '#b45309' },  // amber — chokepoint
  W1: { fill: '#10b981', border: '#047857' },  // green — fallback path
  P1: { fill: '#facc15', border: '#a16207' },  // gold — extraction
};

type PinEvent = {
  id: string;
  ts: number;
  label: string;
  lat: number;
  lng: number;
  tone: 'green' | 'amber' | 'rose' | 'cyan' | 'slate';
};

type Position = {
  callsign: string;
  role: string;
  lat: number;
  lng: number;
  ts: string;
};

const PIN_COLORS = {
  green: '#10b981',
  amber: '#f59e0b',
  rose: '#f43f5e',
  cyan: '#38bdf8',
  slate: '#94a3b8',
};

function pinIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: 'mission-pin',
    html: `<div style="
      width: 18px; height: 18px; border-radius: 50%;
      background: ${color}; border: 3px solid #0f172a;
      box-shadow: 0 0 0 2px ${color}80, 0 0 16px ${color}80;
    "></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function soldierIcon(role: string): L.DivIcon {
  const color = role === 'medic' ? '#a78bfa' : '#22d3ee';
  return L.divIcon({
    className: 'soldier-pin',
    html: `<div style="
      width: 28px; height: 28px; border-radius: 50%;
      background: ${color}; border: 4px solid #0f172a;
      box-shadow: 0 0 0 3px ${color}40, 0 0 24px ${color}80;
      display: flex; align-items: center; justify-content: center;
      color: white; font-weight: 700; font-size: 12px; font-family: ui-sans-serif;
    ">${role === 'medic' ? 'M' : 'A'}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

// Bound the AO so panning stays in Mission Bay.
const CENTER: [number, number] = [37.7705, -122.388];

export function MissionMap({ pinEvents }: { pinEvents: PinEvent[] }) {
  const [positions, setPositions] = useState<Position[]>([]);
  const lastPollRef = useRef(0);

  // Poll positions every 3s
  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      try {
        const res = await fetch('/api/mission/position', { cache: 'no-store' });
        if (!res.ok) return;
        const body = await res.json();
        if (mounted && Array.isArray(body.positions)) {
          setPositions(body.positions);
          lastPollRef.current = Date.now();
        }
      } catch {
        /* silent */
      }
    };
    void poll();
    const t = setInterval(poll, 3000);
    return () => {
      mounted = false;
      clearInterval(t);
    };
  }, []);

  // Central route polyline (UCSF → M4 → P1)
  const centralRoute = useMemo<[number, number][]>(
    () => [
      [SECTOR_COORDS.M1.lat, SECTOR_COORDS.M1.lng],
      [SECTOR_COORDS.M2.lat, SECTOR_COORDS.M2.lng],
      [SECTOR_COORDS.M3.lat, SECTOR_COORDS.M3.lng],
      [SECTOR_COORDS.M4.lat, SECTOR_COORDS.M4.lng],
      [SECTOR_COORDS.P1.lat, SECTOR_COORDS.P1.lng],
    ],
    [],
  );

  // Waterfront fallback (UCSF → M5 → W1 → P1)
  const waterfrontRoute = useMemo<[number, number][]>(
    () => [
      [SECTOR_COORDS.M1.lat, SECTOR_COORDS.M1.lng],
      [SECTOR_COORDS.M5.lat, SECTOR_COORDS.M5.lng],
      [SECTOR_COORDS.W1.lat, SECTOR_COORDS.W1.lng],
      [SECTOR_COORDS.P1.lat, SECTOR_COORDS.P1.lng],
    ],
    [],
  );

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-700 bg-slate-900">
      <MapContainer
        center={CENTER}
        zoom={16}
        style={{ height: '60vh', width: '100%' }}
        scrollWheelZoom={true}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* Planned central route — dashed red */}
        <Polyline
          positions={centralRoute}
          pathOptions={{ color: '#f43f5e', weight: 4, opacity: 0.75, dashArray: '8 8' }}
        />
        {/* Waterfront fallback — solid green */}
        <Polyline
          positions={waterfrontRoute}
          pathOptions={{ color: '#10b981', weight: 4, opacity: 0.8 }}
        />

        {/* Sector markers */}
        {Object.entries(SECTOR_COORDS).map(([sid, s]) => {
          const tone = SECTOR_TONE[sid] ?? { fill: '#64748b', border: '#334155' };
          return (
            <CircleMarker
              key={sid}
              center={[s.lat, s.lng]}
              radius={12}
              pathOptions={{
                color: tone.border,
                fillColor: tone.fill,
                fillOpacity: 0.7,
                weight: 2,
              }}
            >
              <Popup>
                <div style={{ fontFamily: 'ui-sans-serif', fontSize: 12 }}>
                  <div style={{ fontWeight: 700 }}>{sid}</div>
                  <div>{s.label}</div>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}

        {/* Event pins (the last 12 injections) */}
        {pinEvents.map((ev) => (
          <Marker
            key={ev.id}
            position={[ev.lat, ev.lng]}
            icon={pinIcon(PIN_COLORS[ev.tone] ?? PIN_COLORS.slate)}
          >
            <Popup>
              <div style={{ fontFamily: 'ui-sans-serif', fontSize: 12 }}>
                <div style={{ fontWeight: 700 }}>{ev.label}</div>
                <div style={{ opacity: 0.7 }}>{new Date(ev.ts).toLocaleTimeString()}</div>
              </div>
            </Popup>
          </Marker>
        ))}

        {/* Live soldier positions */}
        {positions.map((p) => (
          <Marker
            key={`pos-${p.callsign}`}
            position={[p.lat, p.lng]}
            icon={soldierIcon(p.role)}
          >
            <Popup>
              <div style={{ fontFamily: 'ui-sans-serif', fontSize: 12 }}>
                <div style={{ fontWeight: 700 }}>{p.callsign}</div>
                <div>{p.role}</div>
                <div style={{ opacity: 0.7 }}>
                  {p.lat.toFixed(5)}, {p.lng.toFixed(5)}
                </div>
                <div style={{ opacity: 0.5 }}>{new Date(p.ts).toLocaleTimeString()}</div>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
