import * as path from 'path';
import { URL } from 'url';

// ── Filesystem allowlist ──────────────────────────────────────────────────────
interface FSPolicy {
  read: string[];
  write: string[];
}

const FS_POLICY: Record<string, FSPolicy> = {
  'rbi-agent': {
    read: ['data/', 'docs/', 'results/', 'src/rbi/'],
    write: ['docs/plans/', 'results/'],
  },
  'strategy-agent': {
    read: ['src/rbi/strategies/', 'data/', 'results/'],
    write: ['src/rbi/strategies/', 'results/'],
  },
  'trading-agent': {
    read: ['data/', 'results/'],
    write: ['results/'],
  },
  'risk-agent': {
    read: ['data/', 'results/'],
    write: ['results/'],
  },
  'solana-agent': {
    read: ['data/', 'results/'],
    write: ['results/'],
  },
  'sniper-agent': {
    read: ['data/', 'results/'],
    write: ['results/'],
  },
  'claude-main': {
    read: ['data/', 'docs/', 'results/', 'src/'],
    write: ['results/', 'docs/'],
  },
};

// Paths NUNCA accesibles por ningún agente (tienen prioridad sobre allowlist)
const BLOCKED_PATHS = ['.env', '.env.', '.claude/', 'secrets/', 'vault/'];

// ── URL allowlist ─────────────────────────────────────────────────────────────
const URL_POLICY: Record<string, string[]> = {
  'rbi-agent': [
    'youtube.com',
    'arxiv.org',
    'github.com',
    'medium.com',
    'tradingview.com',
    'investopedia.com',
    'ssrn.com',
  ],
  'trading-agent': [
    'binance.com',
    'api.hyperliquid.xyz',
    'api.coingecko.com',
    'pro-api.coinmarketcap.com',
  ],
  'sniper-agent': [
    'dexscreener.com',
    'mainnet.helius-rpc.com',
    'api.mainnet-beta.solana.com',
    'rpc.helius.xyz',
  ],
  'solana-agent': [
    'dexscreener.com',
    'helius-rpc.com',
    'birdeye.io',
    'api.dexscreener.com',
  ],
  'claude-main': [
    'github.com',
    'google.com',
    'anthropic.com',
    'openai.com',
  ],
};

function normalizePath(filePath: string): string {
  /** Normaliza y valida un path relativo. Retorna '' si es inválido. */
  const trimmed = filePath.trim();
  
  // Bloquear paths absolutos
  if (path.isAbsolute(trimmed)) {
    return '';
  }

  // Convertir separadores y resolver ..
  const resolved = path.normalize(trimmed).replace(/\\/g, '/');
  
  // Si el path intenta salir del proyecto (empieza con ..), es inválido
  if (resolved.startsWith('..')) {
    return '';
  }

  // Quitar ./ del inicio si queda
  return resolved.replace(/^\.\//, '').replace(/\/+$/, '');
}

export function canAccessPath(agent: string, filePath: string, mode: 'read' | 'write' = 'read'): boolean {
  const normalized = normalizePath(filePath);
  if (!normalized) {
    return false;
  }

  // Bloquear paths sensibles siempre
  for (const blocked of BLOCKED_PATHS) {
    const blockedNorm = blocked.replace(/\/+$/, '');
    if (normalized.startsWith(blockedNorm) || normalized === blockedNorm) {
      return false;
    }
  }

  const policy = FS_POLICY[agent];
  if (!policy) {
    return false;
  }

  const allowedPrefixes = policy[mode] || [];
  return allowedPrefixes.some((prefix) => {
    const normPrefix = prefix.replace(/\/+$/, '');
    return normalized.startsWith(normPrefix) || normalized === normPrefix;
  });
}

export function canAccessUrl(agent: string, urlStr: string): boolean {
  const allowedDomains = URL_POLICY[agent];
  if (!allowedDomains || allowedDomains.length === 0) {
    return false;
  }

  try {
    const parsedUrl = new URL(urlStr);
    let hostname = parsedUrl.hostname.toLowerCase();
    
    // Quitar www.
    if (hostname.startsWith('www.')) {
      hostname = hostname.substring(4);
    }

    return allowedDomains.some((domain) => {
      const d = domain.toLowerCase();
      return hostname === d || hostname.endsWith('.' + d);
    });
  } catch (e) {
    return false;
  }
}
