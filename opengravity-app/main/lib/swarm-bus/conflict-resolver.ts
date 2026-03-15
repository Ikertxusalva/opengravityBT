/**
 * Conflict Resolver — Protocol v2.1 Pragmático
 *
 * Tres reglas determinísticas, en orden de prioridad:
 * 1. Veto absoluto de Risk Agent
 * 2. Coincidencia mínima 2/3 fuentes
 * 3. Weighted scoring para position sizing
 *
 * Si puede ser un if, no es un LLM.
 */
import {
  AgentResponse,
  ConflictResult,
  Direction,
  PositionSize,
  AgentName,
  WEIGHTS,
  THRESHOLDS,
} from './types';

/**
 * Resolve conflict between agent responses.
 * Applies the 3 rules in strict priority order.
 */
export function resolve(responses: {
  funding?: AgentResponse;
  chart?: AgentResponse;
  risk?: AgentResponse;
}): ConflictResult {
  const { funding, chart, risk } = responses;
  const sources: AgentName[] = [];

  // ── Rule 1: Risk veto (absolute) ──
  if (risk && !risk.timedOut && risk.type === 'veto') {
    return {
      action: 'BLOCKED',
      reason: risk.reason || 'Risk agent vetoed the operation',
      sources: ['risk-agent'],
    };
  }

  // Collect available signals (non-timed-out agents with a direction)
  const signals: Array<{ agent: AgentName; direction: Direction; confidence: number }> = [];

  if (funding && !funding.timedOut && funding.direction !== 'NEUTRAL') {
    signals.push({ agent: 'funding-agent', direction: funding.direction, confidence: funding.confidence });
    sources.push('funding-agent');
  }
  if (chart && !chart.timedOut && chart.direction !== 'NEUTRAL') {
    signals.push({ agent: 'chart-agent', direction: chart.direction, confidence: chart.confidence });
    sources.push('chart-agent');
  }
  if (risk && !risk.timedOut && risk.direction !== 'NEUTRAL') {
    signals.push({ agent: 'risk-agent', direction: risk.direction, confidence: risk.confidence });
    sources.push('risk-agent');
  }

  // If fewer than 2 signals available, can't reach consensus
  if (signals.length < 2) {
    return {
      action: 'SKIP',
      reason: `Insufficient signals: only ${signals.length} agent(s) responded with direction`,
      sources,
    };
  }

  // ── Rule 2: Consensus 2/3 ──
  const longCount = signals.filter(s => s.direction === 'LONG').length;
  const shortCount = signals.filter(s => s.direction === 'SHORT').length;
  const maxAgreement = Math.max(longCount, shortCount);

  if (maxAgreement < THRESHOLDS.CONSENSUS_MIN) {
    return {
      action: 'SKIP',
      reason: `No consensus: ${longCount} LONG, ${shortCount} SHORT (need ${THRESHOLDS.CONSENSUS_MIN})`,
      sources,
    };
  }

  const direction: Direction = longCount > shortCount ? 'LONG' : 'SHORT';

  // ── Rule 3: Weighted scoring for position sizing ──
  const score = calcWeightedScore(responses);
  const size = scoreToSize(score);

  return {
    action: 'EXECUTE',
    direction,
    size,
    score,
    reason: `Consensus ${direction} (${maxAgreement}/${signals.length}), score ${score.toFixed(2)} → ${size}`,
    sources,
  };
}

/**
 * Calculate weighted score from agent confidences.
 * funding: 40%, chart: 35%, risk/stress: 25%
 */
function calcWeightedScore(responses: {
  funding?: AgentResponse;
  chart?: AgentResponse;
  risk?: AgentResponse;
}): number {
  let score = 0;
  let totalWeight = 0;

  if (responses.funding && !responses.funding.timedOut) {
    score += responses.funding.confidence * WEIGHTS['funding-agent'];
    totalWeight += WEIGHTS['funding-agent'];
  }
  if (responses.chart && !responses.chart.timedOut) {
    score += responses.chart.confidence * WEIGHTS['chart-agent'];
    totalWeight += WEIGHTS['chart-agent'];
  }
  if (responses.risk && !responses.risk.timedOut && responses.risk.type !== 'veto') {
    score += responses.risk.confidence * WEIGHTS['risk-agent'];
    totalWeight += WEIGHTS['risk-agent'];
  }

  // Normalize to 0-1 range if not all agents responded
  return totalWeight > 0 ? score / totalWeight : 0;
}

/** Map score to position size */
function scoreToSize(score: number): PositionSize {
  if (score >= THRESHOLDS.FULL_POSITION_SCORE) return 'full';
  if (score >= THRESHOLDS.HALF_POSITION_SCORE) return 'half';
  return 'quarter';
}

/**
 * Quick check: should we even bother consulting other agents?
 * Used for pre-filtering before expensive Promise.all calls.
 */
export function isWorthInvestigating(signal: {
  direction: Direction;
  confidence: number;
}): boolean {
  // Skip weak signals that won't reach consensus even with full agreement
  return signal.confidence >= 0.3 && signal.direction !== 'NEUTRAL';
}
