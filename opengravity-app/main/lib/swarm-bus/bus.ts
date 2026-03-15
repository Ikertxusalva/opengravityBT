/**
 * Swarm Event Bus — Protocol v2.1 Pragmático
 *
 * Append-only JSONL file + WebSocket broadcast.
 * TTL enforcement before processing each event.
 * No SQLite, no Redis — just a file and a WebSocket.
 */
import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';
import { SwarmEvent, Channel, AgentName, EventType, Priority, TTL } from './types';

// ── Bus file path ──
// Electron's cwd is opengravity-app/, but the bus lives in the project root
const PROJECT_ROOT = path.resolve(process.cwd(), '..');
const BUS_DIR = path.join(PROJECT_ROOT, '.claude', 'swarm-bus');
const BUS_FILE = path.join(BUS_DIR, 'events.jsonl');
const STATUS_FILE = path.join(BUS_DIR, 'status.json');

// ── WebSocket broadcast callback (set by pty-manager) ──
let wsBroadcast: ((event: SwarmEvent) => void) | null = null;

function ensureBusDir() {
  if (!fs.existsSync(BUS_DIR)) fs.mkdirSync(BUS_DIR, { recursive: true });
}

/** Register a WebSocket broadcast function */
export function setBroadcast(fn: (event: SwarmEvent) => void) {
  wsBroadcast = fn;
}

/** Create and publish a new event to the bus */
export function publish(params: {
  channel: Channel;
  from: AgentName;
  type: EventType;
  priority: Priority;
  payload: Record<string, unknown>;
  ttl?: number;
}): SwarmEvent {
  ensureBusDir();

  const event: SwarmEvent = {
    id: crypto.randomUUID(),
    channel: params.channel,
    from: params.from,
    type: params.type,
    timestamp: new Date().toISOString(),
    ttl: params.ttl ?? (params.channel === 'realtime' ? TTL.REALTIME : TTL.RESEARCH),
    priority: params.priority,
    payload: params.payload,
  };

  // Append to JSONL
  try {
    fs.appendFileSync(BUS_FILE, JSON.stringify(event) + '\n', 'utf-8');
  } catch (e) {
    console.error('[SwarmBus] Failed to write event:', e);
  }

  // Broadcast via WebSocket
  if (wsBroadcast) {
    try { wsBroadcast(event); } catch {}
  }

  console.log(`[SwarmBus] ${event.from} → ${event.type} (${event.channel}) [${event.priority}]`);
  return event;
}

/** Check if an event is still valid (not expired) */
export function isAlive(event: SwarmEvent): boolean {
  const created = new Date(event.timestamp).getTime();
  const now = Date.now();
  return now < created + (event.ttl * 1000);
}

/** Read all live events from the bus, optionally filtered by channel */
export function readEvents(channel?: Channel): SwarmEvent[] {
  ensureBusDir();
  if (!fs.existsSync(BUS_FILE)) return [];

  try {
    const lines = fs.readFileSync(BUS_FILE, 'utf-8').trim().split('\n').filter(Boolean);
    const events: SwarmEvent[] = [];
    let expiredCount = 0;

    for (const line of lines) {
      try {
        const event: SwarmEvent = JSON.parse(line);
        if (isAlive(event)) {
          if (!channel || event.channel === channel) {
            events.push(event);
          }
        } else {
          expiredCount++;
        }
      } catch {}
    }

    if (expiredCount > 0) {
      console.log(`[SwarmBus] Filtered out ${expiredCount} expired events`);
    }

    return events;
  } catch {
    return [];
  }
}

/** Read events from a specific agent */
export function readFrom(agent: AgentName, channel?: Channel): SwarmEvent[] {
  return readEvents(channel).filter(e => e.from === agent);
}

/** Read events of a specific type */
export function readByType(type: EventType, channel?: Channel): SwarmEvent[] {
  return readEvents(channel).filter(e => e.type === type);
}

/** Get the most recent event matching criteria */
export function latest(params?: {
  channel?: Channel;
  from?: AgentName;
  type?: EventType;
}): SwarmEvent | null {
  let events = readEvents(params?.channel);
  if (params?.from) events = events.filter(e => e.from === params.from);
  if (params?.type) events = events.filter(e => e.type === params.type);

  if (events.length === 0) return null;
  return events.reduce((a, b) =>
    new Date(a.timestamp) > new Date(b.timestamp) ? a : b
  );
}

/** Compact the bus file — remove expired events */
export function compact(): number {
  ensureBusDir();
  if (!fs.existsSync(BUS_FILE)) return 0;

  try {
    const lines = fs.readFileSync(BUS_FILE, 'utf-8').trim().split('\n').filter(Boolean);
    const alive: string[] = [];
    let removed = 0;

    for (const line of lines) {
      try {
        const event: SwarmEvent = JSON.parse(line);
        if (isAlive(event)) {
          alive.push(line);
        } else {
          removed++;
        }
      } catch {
        removed++;
      }
    }

    fs.writeFileSync(BUS_FILE, alive.join('\n') + (alive.length > 0 ? '\n' : ''), 'utf-8');
    if (removed > 0) console.log(`[SwarmBus] Compacted: removed ${removed} expired events`);
    return removed;
  } catch {
    return 0;
  }
}

/** Update swarm status file */
export function setStatus(status: string, workflow?: string) {
  ensureBusDir();
  const data = {
    status,
    workflow: workflow ?? null,
    updated_at: new Date().toISOString(),
  };
  try {
    fs.writeFileSync(STATUS_FILE, JSON.stringify(data, null, 2), 'utf-8');
  } catch {}
}

/** Get current swarm status */
export function getStatus(): { status: string; workflow: string | null; updated_at: string | null } {
  try {
    if (fs.existsSync(STATUS_FILE)) {
      return JSON.parse(fs.readFileSync(STATUS_FILE, 'utf-8'));
    }
  } catch {}
  return { status: 'idle', workflow: null, updated_at: null };
}

/** Clear all events from the bus */
export function clear() {
  ensureBusDir();
  try { fs.writeFileSync(BUS_FILE, '', 'utf-8'); } catch {}
}

/** Count events by channel */
export function stats(): { realtime: number; research: number; total: number } {
  const events = readEvents();
  const realtime = events.filter(e => e.channel === 'realtime').length;
  const research = events.filter(e => e.channel === 'research').length;
  return { realtime, research, total: events.length };
}
