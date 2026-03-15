/**
 * Swarm Bus Types — Protocol v2.1 Pragmático
 *
 * Defines all interfaces and enums for the event bus.
 * TypeScript determinístico: si puede ser un if, no es un LLM.
 */

// ── Agent names ──
export type AgentName =
  | 'funding-agent'
  | 'chart-agent'
  | 'risk-agent'
  | 'trading-agent'
  | 'strategy-agent'
  | 'rbi-agent'
  | 'backtest-architect'
  | 'claude-main'
  | 'sentiment-agent'
  | 'whale-agent'
  | 'liquidation-agent'
  | 'polymarket-agent'
  | 'top-mover-agent'
  | 'news-agent'
  | 'signal-scanner';

// ── Event types ──
export type EventType =
  | 'signal'    // Sensor detecta anomalía
  | 'analysis'  // Agente provee análisis
  | 'veto'      // Risk bloquea operación
  | 'order'     // Orden de ejecución
  | 'result'    // Resultado de ejecución
  | 'finding';  // Hallazgo de research

// ── Channels ──
export type Channel = 'realtime' | 'research';

// ── Priority levels ──
export type Priority = 1 | 2 | 3; // 1=crítico, 2=importante, 3=info

// ── Direction ──
export type Direction = 'LONG' | 'SHORT' | 'NEUTRAL';

// ── Position size ──
export type PositionSize = 'full' | 'half' | 'quarter';

// ── Core event schema ──
export interface SwarmEvent {
  id: string;
  channel: Channel;
  from: AgentName;
  type: EventType;
  timestamp: string;    // ISO 8601 UTC
  ttl: number;          // seconds: 300 realtime, 86400 research
  priority: Priority;
  payload: Record<string, unknown>;
}

// ── Signal payload (from sensors) ──
export interface SignalPayload {
  symbol: string;
  direction: Direction;
  confidence: number;   // 0.0 - 1.0
  reason: string;
  data?: Record<string, unknown>;
}

// ── Analysis payload (from chart/risk) ──
export interface AnalysisPayload {
  symbol: string;
  direction: Direction;
  confidence: number;
  support?: number;
  resistance?: number;
  stopLoss?: number;
  takeProfit?: number;
  reason: string;
}

// ── Veto payload (from risk-agent) ──
export interface VetoPayload {
  reason: string;
  riskScore: number;    // 0-100
  maxDrawdown?: number;
  exposure?: number;
}

// ── Order payload (to trading-agent) ──
export interface OrderPayload {
  symbol: string;
  direction: Direction;
  size: PositionSize;
  score: number;
  stopLoss?: number;
  takeProfit?: number;
  sources: string[];    // agents that contributed
}

// ── Conflict resolution result ──
export interface ConflictResult {
  action: 'EXECUTE' | 'SKIP' | 'BLOCKED';
  direction?: Direction;
  size?: PositionSize;
  score?: number;
  reason: string;
  sources: AgentName[];
}

// ── Agent invocation result ──
export interface AgentResponse {
  agent: AgentName;
  type: EventType;
  direction: Direction;
  confidence: number;
  reason: string;
  timedOut: boolean;
  payload?: Record<string, unknown>;
}

// ── Circuit breaker state ──
export interface CircuitState {
  errorCount: number;
  lastError?: string;
  disabledAt?: string;
  lastHealthCheck?: string;
}

// ── TTL defaults ──
export const TTL = {
  REALTIME: 300,     // 5 minutes
  RESEARCH: 86_400,  // 24 hours
} as const;

// ── Weights for conflict resolution ──
export const WEIGHTS = {
  'funding-agent': 0.40,
  'chart-agent': 0.35,
  'risk-agent': 0.25,  // stress/risk score weight (veto is separate)
} as const;

// ── Thresholds ──
export const THRESHOLDS = {
  CONSENSUS_MIN: 2,           // minimum 2/3 sources must agree
  FULL_POSITION_SCORE: 0.80,
  HALF_POSITION_SCORE: 0.60,
  CIRCUIT_BREAKER_MAX: 3,     // consecutive errors before disable
  HEALTH_CHECK_INTERVAL: 300_000, // 5 minutes
  AGENT_TIMEOUT: 30_000,      // 30 seconds per agent invocation (Claude needs time to think + execute)
} as const;
