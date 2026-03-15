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
}
