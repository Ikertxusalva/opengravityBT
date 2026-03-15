/**
 * Agent Memory Manager — Structured memory system for Claude agents.
 *
 * 4 memory types: semantic, episodic, procedural, working
 * 2 scopes: private (per-agent), shared (cross-agent)
 * Storage: JSONL files locally + async sync to Railway
 */
import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';
import { Vault } from './security/vault';

// ── Types ──

export type MemoryType = 'semantic' | 'episodic' | 'procedural' | 'working';
export type MemoryScope = 'private' | 'shared';

export interface AgentMemory {
  id: string;
  agent_id: string;
  type: MemoryType;
  scope: MemoryScope;
  content: string;
  context: string;
  tags: string[];
  importance: number;       // 0.0 - 1.0
  access_count: number;
  created_at: string;       // ISO
  updated_at: string;       // ISO
  expires_at: string | null; // ISO or null (permanent)
  links: string[];           // IDs of related memories
}

// ── Limits per type ──
const TYPE_LIMITS: Record<MemoryType, number> = {
  semantic: 50,
  episodic: 20,
  procedural: 20,
  working: 10,
};

const EPISODIC_TTL_DAYS = 30;
const CLOUD_URL = 'https://chic-encouragement-production.up.railway.app';
const MEMORY_BASE = path.join(process.cwd(), '.claude', 'agent-memory');
const SHARED_DIR = path.join(MEMORY_BASE, 'shared');

// ── Decay & consolidation config ──
const DECAY_RATE = 0.02;            // importance drops 0.02 per day without access
const DECAY_FLOOR = 0.05;           // minimum importance before auto-deletion
const CONSOLIDATION_THRESHOLD = 0.6; // Jaccard similarity to consider duplicates
const MAINTENANCE_INTERVAL_MS = 3600_000; // run maintenance every hour

// ── Helpers ──

function ensureDir(dir: string) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function agentDir(agentId: string): string {
  return path.join(MEMORY_BASE, agentId);
}

function memoryFile(agentId: string): string {
  return path.join(agentDir(agentId), 'memories.jsonl');
}

function sharedFile(): string {
  return path.join(SHARED_DIR, 'memories.jsonl');
}

function readJsonl(filepath: string): AgentMemory[] {
  try {
    if (!fs.existsSync(filepath)) return [];
    const content = fs.readFileSync(filepath, 'utf-8').trim();
    if (!content) return [];
    return content.split('\n').map(line => JSON.parse(line));
  } catch {
    return [];
  }
}

function writeJsonl(filepath: string, memories: AgentMemory[]) {
  ensureDir(path.dirname(filepath));
  const content = memories.map(m => JSON.stringify(m)).join('\n');
  fs.writeFileSync(filepath, content + '\n', 'utf-8');
}

function generateId(): string {
  return `mem-${crypto.randomUUID().slice(0, 12)}`;
}

function isExpired(memory: AgentMemory): boolean {
  if (!memory.expires_at) return false;
  return new Date(memory.expires_at) < new Date();
}

// ── Core Memory API ──

export class MemoryManager {

  /**
   * Store a new memory for an agent.
   */
  static save(params: {
    agent_id: string;
    type: MemoryType;
    content: string;
    context?: string;
    tags?: string[];
    importance?: number;
    scope?: MemoryScope;
    links?: string[];
  }): AgentMemory {
    const now = new Date().toISOString();
    const scope = params.scope || 'private';

    const memory: AgentMemory = {
      id: generateId(),
      agent_id: params.agent_id,
      type: params.type,
      scope,
      content: params.content,
      context: params.context || '',
      tags: params.tags || [],
      importance: params.importance ?? 0.5,
      access_count: 0,
      created_at: now,
      updated_at: now,
      expires_at: params.type === 'episodic'
        ? new Date(Date.now() + EPISODIC_TTL_DAYS * 86400000).toISOString()
        : params.type === 'working'
          ? new Date(Date.now() + 86400000).toISOString() // 24h for working
          : null,
      links: params.links || [],
    };

    // Choose file based on scope
    const file = scope === 'shared' ? sharedFile() : memoryFile(params.agent_id);
    const memories = readJsonl(file);

    // Check for similar existing memory — merge instead of duplicating
    const existing = memories.find(m =>
      m.type === memory.type &&
      m.agent_id === memory.agent_id &&
      this.similarity(m.content, memory.content) >= CONSOLIDATION_THRESHOLD
    );

    if (existing) {
      // Merge into existing: boost importance, combine metadata
      existing.importance = Math.min(1.0, existing.importance + memory.importance * 0.3);
      existing.access_count++;
      existing.tags = [...new Set([...existing.tags, ...memory.tags])];
      existing.updated_at = new Date().toISOString();
      if (memory.context && !existing.context.includes(memory.context)) {
        existing.context = (existing.context + ' | ' + memory.context).slice(0, 500);
      }
      writeJsonl(file, memories);
      console.log(`[Memory] Merged with existing memory for ${params.agent_id}: ${memory.content.slice(0, 50)}...`);
      return existing;
    }

    memories.push(memory);

    // Enforce limits: prune lowest importance if over limit
    const pruned = this.pruneByType(memories, params.type, params.agent_id);
    writeJsonl(file, pruned);

    // Async cloud sync (fire-and-forget)
    this.syncToCloud(memory).catch(() => {});

    return memory;
  }

  /**
   * Get all memories for an agent (private + shared relevant).
   */
  static getAll(agentId: string): AgentMemory[] {
    const privateMemories = readJsonl(memoryFile(agentId)).filter(m => !isExpired(m));
    const sharedMemories = readJsonl(sharedFile()).filter(m => !isExpired(m));

    // Combine and sort by importance
    return [...privateMemories, ...sharedMemories]
      .sort((a, b) => b.importance - a.importance);
  }

  /**
   * Get memories by type for an agent.
   */
  static getByType(agentId: string, type: MemoryType): AgentMemory[] {
    return this.getAll(agentId).filter(m => m.type === type);
  }

  /**
   * Search memories by tags (any match).
   */
  static searchByTags(agentId: string, tags: string[], limit = 5): AgentMemory[] {
    const all = this.getAll(agentId);
    const tagSet = new Set(tags.map(t => t.toLowerCase()));

    return all
      .filter(m => m.tags.some(t => tagSet.has(t.toLowerCase())))
      .sort((a, b) => {
        // Score by tag overlap + importance
        const aOverlap = a.tags.filter(t => tagSet.has(t.toLowerCase())).length;
        const bOverlap = b.tags.filter(t => tagSet.has(t.toLowerCase())).length;
        return (bOverlap + b.importance) - (aOverlap + a.importance);
      })
      .slice(0, limit);
  }

  /**
   * Search memories by content keyword match.
   */
  static search(agentId: string, query: string, limit = 5): AgentMemory[] {
    const all = this.getAll(agentId);
    const q = query.toLowerCase();

    return all
      .filter(m => m.content.toLowerCase().includes(q) || m.context.toLowerCase().includes(q))
      .sort((a, b) => b.importance - a.importance)
      .slice(0, limit);
  }

  /**
   * Increment access count (for relevance tracking).
   */
  static touch(memoryId: string, agentId: string) {
    const file = memoryFile(agentId);
    const memories = readJsonl(file);
    const mem = memories.find(m => m.id === memoryId);
    if (mem) {
      mem.access_count++;
      mem.updated_at = new Date().toISOString();
      writeJsonl(file, memories);
    }
  }

  /**
   * Delete a specific memory.
   */
  static delete(memoryId: string, agentId: string) {
    const file = memoryFile(agentId);
    const memories = readJsonl(file).filter(m => m.id !== memoryId);
    writeJsonl(file, memories);
  }

  /**
   * Build prompt injection block for agent context.
   * 3-level strategy: always-inject rules → relevance-based → available for recall.
   */
  static buildPromptBlock(agentId: string, contextTags?: string[]): string {
    const all = this.getAll(agentId);
    if (all.length === 0) return '';

    const lines: string[] = ['<agent-memory>'];

    // Level 1: Always-inject — procedural rules (top 5 by importance)
    const procedural = all
      .filter(m => m.type === 'procedural')
      .slice(0, 5);
    if (procedural.length > 0) {
      lines.push('## Reglas aprendidas');
      procedural.forEach(m => lines.push(`- ${m.content}`));
    }

    // Level 2: Relevance-based — semantic memories matching context tags
    let semantic: AgentMemory[] = [];
    if (contextTags && contextTags.length > 0) {
      semantic = this.searchByTags(agentId, contextTags, 5)
        .filter(m => m.type === 'semantic');
    }
    if (semantic.length === 0) {
      // Fallback: top 5 semantic by importance
      semantic = all.filter(m => m.type === 'semantic').slice(0, 5);
    }
    if (semantic.length > 0) {
      lines.push('## Conocimiento relevante');
      semantic.forEach(m => {
        const tagStr = m.tags.length > 0 ? ` [${m.tags.join(', ')}]` : '';
        lines.push(`- ${m.content}${tagStr}`);
      });
    }

    // Level 3: Recent episodic (last 3)
    const episodic = all
      .filter(m => m.type === 'episodic')
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 3);
    if (episodic.length > 0) {
      lines.push('## Eventos recientes');
      episodic.forEach(m => {
        const date = new Date(m.created_at).toLocaleDateString('es-ES');
        lines.push(`- [${date}] ${m.content}`);
      });
    }

    lines.push('</agent-memory>');

    // Only return if there's actual content
    return lines.length > 2 ? lines.join('\n') : '';
  }

  /**
   * Prune memories to stay within type limits.
   * Removes expired first, then lowest importance.
   */
  private static pruneByType(memories: AgentMemory[], type: MemoryType, agentId: string): AgentMemory[] {
    // Remove expired
    const valid = memories.filter(m => !isExpired(m));

    // Count this type for this agent
    const ofType = valid.filter(m => m.type === type && m.agent_id === agentId);
    const others = valid.filter(m => !(m.type === type && m.agent_id === agentId));

    if (ofType.length <= TYPE_LIMITS[type]) return valid;

    // Sort by importance (keep highest)
    const sorted = ofType.sort((a, b) => b.importance - a.importance);
    const kept = sorted.slice(0, TYPE_LIMITS[type]);

    return [...others, ...kept];
  }

  /**
   * Sync a memory to Railway cloud (async, non-blocking).
   */
  private static async syncToCloud(memory: AgentMemory) {
    try {
      const token = await Vault.get('OPENGRAVITY_API_TOKEN');
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      await fetch(`${CLOUD_URL}/api/agent/memory/${memory.agent_id}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(memory),
      });
    } catch {
      // Cloud sync is best-effort
    }
  }

  /**
   * Hydrate memories from cloud on startup.
   */
  static async hydrateFromCloud(agentId: string) {
    try {
      const resp = await fetch(`${CLOUD_URL}/api/agent/memory/${agentId}`);
      if (!resp.ok) return;
      const data = await resp.json() as { memories: AgentMemory[] };
      if (!data.memories || data.memories.length === 0) return;

      const localMemories = readJsonl(memoryFile(agentId));
      const localIds = new Set(localMemories.map(m => m.id));

      // Merge: add cloud memories not present locally
      let added = 0;
      for (const cloudMem of data.memories) {
        if (!localIds.has(cloudMem.id) && !isExpired(cloudMem)) {
          localMemories.push(cloudMem);
          added++;
        }
      }

      if (added > 0) {
        writeJsonl(memoryFile(agentId), localMemories);
        console.log(`[Memory] Hydrated ${added} memories for ${agentId} from cloud`);
      }
    } catch {
      // Cloud hydration is best-effort
    }
  }

  /**
   * Get memory stats for an agent (for UI/debugging).
   */
  static getStats(agentId: string): Record<string, number> {
    const all = this.getAll(agentId);
    return {
      total: all.length,
      semantic: all.filter(m => m.type === 'semantic').length,
      episodic: all.filter(m => m.type === 'episodic').length,
      procedural: all.filter(m => m.type === 'procedural').length,
      working: all.filter(m => m.type === 'working').length,
      shared: all.filter(m => m.scope === 'shared').length,
      private: all.filter(m => m.scope === 'private').length,
    };
  }

  // ── Intelligent Memory: Similarity ──

  /**
   * Tokenize content into a set of normalized words for comparison.
   */
  private static tokenize(text: string): Set<string> {
    return new Set(
      text.toLowerCase()
        .replace(/[^a-záéíóúñü0-9\s]/g, '')
        .split(/\s+/)
        .filter(w => w.length > 2)
    );
  }

  /**
   * Jaccard similarity between two texts (0.0 - 1.0).
   */
  private static similarity(a: string, b: string): number {
    const setA = this.tokenize(a);
    const setB = this.tokenize(b);
    if (setA.size === 0 && setB.size === 0) return 1.0;
    if (setA.size === 0 || setB.size === 0) return 0.0;

    let intersection = 0;
    for (const word of setA) {
      if (setB.has(word)) intersection++;
    }
    const union = setA.size + setB.size - intersection;
    return union > 0 ? intersection / union : 0;
  }

  // ── Intelligent Memory: Auto-Consolidation ──

  /**
   * Find and merge duplicate/similar memories for an agent.
   * Keeps the one with higher importance, merges tags and links, deletes the other.
   * Returns number of memories consolidated.
   */
  static consolidate(agentId: string): number {
    const file = memoryFile(agentId);
    const memories = readJsonl(file).filter(m => !isExpired(m));
    if (memories.length < 2) return 0;

    const toRemove = new Set<string>();
    let consolidated = 0;

    for (let i = 0; i < memories.length; i++) {
      if (toRemove.has(memories[i].id)) continue;

      for (let j = i + 1; j < memories.length; j++) {
        if (toRemove.has(memories[j].id)) continue;
        // Only consolidate same type
        if (memories[i].type !== memories[j].type) continue;

        const sim = this.similarity(memories[i].content, memories[j].content);
        if (sim >= CONSOLIDATION_THRESHOLD) {
          // Keep the one with higher importance
          const [keeper, duplicate] = memories[i].importance >= memories[j].importance
            ? [memories[i], memories[j]]
            : [memories[j], memories[i]];

          // Merge: boost importance, combine tags and links
          keeper.importance = Math.min(1.0, keeper.importance + duplicate.importance * 0.3);
          keeper.access_count += duplicate.access_count;
          keeper.tags = [...new Set([...keeper.tags, ...duplicate.tags])];
          keeper.links = [...new Set([...keeper.links, ...duplicate.links])];
          keeper.updated_at = new Date().toISOString();

          // If duplicate has newer/richer content, append context
          if (duplicate.context && !keeper.context.includes(duplicate.context)) {
            keeper.context = (keeper.context + ' | ' + duplicate.context).slice(0, 500);
          }

          toRemove.add(duplicate.id);
          consolidated++;
        }
      }
    }

    if (consolidated > 0) {
      const cleaned = memories.filter(m => !toRemove.has(m.id));
      writeJsonl(file, cleaned);
      console.log(`[Memory] Consolidated ${consolidated} duplicate memories for ${agentId}`);
    }

    return consolidated;
  }

  // ── Intelligent Memory: Decay Scoring ──

  /**
   * Apply time-based decay to all memories of an agent.
   * Memories lose importance based on days since last access/update.
   * Memories below DECAY_FLOOR are auto-deleted (obsolete).
   * Returns { decayed: number, deleted: number }.
   */
  static applyDecay(agentId: string): { decayed: number; deleted: number } {
    const file = memoryFile(agentId);
    const memories = readJsonl(file);
    if (memories.length === 0) return { decayed: 0, deleted: 0 };

    const now = Date.now();
    let decayed = 0;
    let deleted = 0;

    for (const mem of memories) {
      // Skip working memories (they have their own TTL)
      if (mem.type === 'working') continue;

      const lastActivity = new Date(mem.updated_at).getTime();
      const daysSinceActivity = (now - lastActivity) / 86400000;

      if (daysSinceActivity < 1) continue; // No decay in first 24h

      // Decay formula: importance -= DECAY_RATE * days * (1 / (1 + access_count))
      // More accessed memories decay slower
      const accessFactor = 1 / (1 + mem.access_count * 0.5);
      const decay = DECAY_RATE * daysSinceActivity * accessFactor;
      const newImportance = Math.max(0, mem.importance - decay);

      if (newImportance !== mem.importance) {
        mem.importance = Math.round(newImportance * 1000) / 1000;
        decayed++;
      }
    }

    // Remove expired + obsolete (below floor)
    const before = memories.length;
    const surviving = memories.filter(m => {
      if (isExpired(m)) return false;
      if (m.importance < DECAY_FLOOR && m.type !== 'procedural') return false; // Never auto-delete procedural
      return true;
    });
    deleted = before - surviving.length;

    if (decayed > 0 || deleted > 0) {
      writeJsonl(file, surviving);
      if (deleted > 0) {
        console.log(`[Memory] Decay: ${decayed} decayed, ${deleted} obsolete removed for ${agentId}`);
      }
    }

    return { decayed, deleted };
  }

  // ── Intelligent Memory: Full Maintenance Cycle ──

  /**
   * Run full maintenance: decay → consolidate → prune expired.
   * Should run periodically (every hour via startMaintenance).
   */
  static runMaintenance() {
    try {
      ensureDir(MEMORY_BASE);
      const agentDirs = fs.readdirSync(MEMORY_BASE).filter(d => {
        const full = path.join(MEMORY_BASE, d);
        return fs.statSync(full).isDirectory() && d !== 'shared';
      });

      let totalDecayed = 0;
      let totalDeleted = 0;
      let totalConsolidated = 0;

      for (const agId of agentDirs) {
        const { decayed, deleted } = this.applyDecay(agId);
        const consolidated = this.consolidate(agId);
        totalDecayed += decayed;
        totalDeleted += deleted;
        totalConsolidated += consolidated;
      }

      // Also maintain shared memories
      const sharedMems = readJsonl(sharedFile());
      if (sharedMems.length > 0) {
        const cleaned = sharedMems.filter(m => !isExpired(m) && m.importance >= DECAY_FLOOR);
        if (cleaned.length !== sharedMems.length) {
          writeJsonl(sharedFile(), cleaned);
          totalDeleted += sharedMems.length - cleaned.length;
        }
      }

      if (totalDecayed > 0 || totalDeleted > 0 || totalConsolidated > 0) {
        console.log(`[Memory] Maintenance complete: ${totalDecayed} decayed, ${totalDeleted} deleted, ${totalConsolidated} consolidated`);
      }
    } catch (e) {
      console.warn('[Memory] Maintenance error:', e);
    }
  }

  // ── Maintenance Timer ──

  private static maintenanceTimer: ReturnType<typeof setInterval> | null = null;

  /**
   * Start periodic maintenance (decay + consolidation + cleanup).
   * Call once at app startup.
   */
  static startMaintenance() {
    if (this.maintenanceTimer) return;

    // Run immediately on first call
    setTimeout(() => this.runMaintenance(), 5000);

    // Then every hour
    this.maintenanceTimer = setInterval(() => {
      this.runMaintenance();
    }, MAINTENANCE_INTERVAL_MS);

    console.log('[Memory] Maintenance scheduler started (every 1h)');
  }

  static stopMaintenance() {
    if (this.maintenanceTimer) {
      clearInterval(this.maintenanceTimer);
      this.maintenanceTimer = null;
    }
  }
}
