import * as React from 'react';
import Head from 'next/head';

// ── Agent definitions ──
const AGENTS = [
  { id: 'claude-main', name: 'Claude (Principal)', icon: '🤖', model: 'sonnet', description: 'Orquestador principal' },
  { id: 'trading-agent', name: 'Trading Agent', icon: '📈', model: 'sonnet', description: 'Decisiones de compra/venta' },
  { id: 'risk-agent', name: 'Risk Agent', icon: '🛡️', model: 'sonnet', description: 'Métricas avanzadas y VaR' },
  { id: 'strategy-agent', name: 'Strategy Agent', icon: '📋', model: 'sonnet', description: 'Ciclo de vida de estrategias' },
  { id: 'rbi-agent', name: 'RBI Agent', icon: '🧪', model: 'sonnet', description: 'Investigación de estrategias' },
  { id: 'solana-agent', name: 'Solana Agent', icon: '🟣', model: 'sonnet', description: 'Selector meme coins' },
  { id: 'sniper-agent', name: 'Sniper Agent', icon: '🎯', model: 'sonnet', description: 'Sniping tokens nuevos' },
  { id: 'sentiment-agent', name: 'Sentiment Agent', icon: '🧠', model: 'sonnet', description: 'Social sentiment' },
  { id: 'copy-agent', name: 'Copy Agent', icon: '👥', model: 'sonnet', description: 'Mirror trading' },
  { id: 'whale-agent', name: 'Whale Agent', icon: '🐳', model: 'sonnet', description: 'Rastreo de ballenas' },
  { id: 'swarm-agent', name: 'Swarm Agent', icon: '🐝', model: 'opus', description: 'Orquestador multi-agente' },
  { id: 'regime-interpreter', name: 'Regime Interpreter', icon: '📊', model: 'sonnet', description: 'Detección de régimen HMM' },
  { id: 'backtest-architect', name: 'Backtest Architect', icon: '⚙️', model: 'sonnet', description: 'Ejecuta y valida backtests' },
  { id: 'chart-agent', name: 'Chart Agent', icon: '📉', model: 'sonnet', description: 'Price action y patrones' },
  { id: 'funding-agent', name: 'Funding Agent', icon: '💰', model: 'haiku', description: 'Funding rates HyperLiquid' },
  { id: 'liquidation-agent', name: 'Liquidation Agent', icon: '⚡', model: 'haiku', description: 'Cascadas de liquidaciones' },
  { id: 'news-agent', name: 'News Agent', icon: '📰', model: 'haiku', description: 'Noticias crypto filtradas' },
  { id: 'research-agent', name: 'Research Agent', icon: '🔬', model: 'haiku', description: 'Genera ideas de estrategias' },
  { id: 'coingecko-agent', name: 'CoinGecko Agent', icon: '🦎', model: 'sonnet', description: 'Análisis macro dual' },
  { id: 'new-listing-agent', name: 'New Listing Agent', icon: '🆕', model: 'haiku', description: 'Arbitraje de listings' },
  { id: 'top-mover-agent', name: 'Top Mover Agent', icon: '🚀', model: 'haiku', description: 'Gainers/Losers 24h' },
  { id: 'code-reviewer', name: 'Code Reviewer', icon: '🔍', model: 'sonnet', description: 'Revisión de código' },
  { id: 'tiktok-agent', name: 'TikTok Agent', icon: '📱', model: 'haiku', description: 'Arbitraje social' },
  { id: 'polymarket-agent', name: 'Polymarket Agent', icon: '🎲', model: 'opus', description: 'Mercados de predicción · CLOB · Edge detection' },
];

const STARTUP_AGENTS = [
  { agentId: 'claude-main', delay: 400 },
  { agentId: 'trading-agent', delay: 900 },
];

interface TerminalState {
  id: string;
  agentId: string;
  agentName: string;
  agentIcon: string;
  model: string;
}

// Global xterm refs
let Terminal: any = null;
let FitAddon: any = null;
let WebLinksAddon: any = null;

if (typeof window !== 'undefined') {
  import('xterm').then(mod => { Terminal = mod.Terminal; });
  import('xterm-addon-fit').then(mod => { FitAddon = mod.FitAddon; });
  import('xterm-addon-web-links').then(mod => { WebLinksAddon = mod.WebLinksAddon; });
}

export default function HomePage() {
  const [terminals, setTerminals] = React.useState<TerminalState[]>([]);
  const [activeTab, setActiveTab] = React.useState<string | null>(null);
  const [isGridView, setIsGridView] = React.useState(true);
  const [showPicker, setShowPicker] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState('');
  const [clock, setClock] = React.useState('');
  const [cloudStatus, setCloudStatus] = React.useState<'connected' | 'disconnected' | 'connecting'>('disconnected');
  const [prices, setPrices] = React.useState<Record<string, number>>({});
  const [fearGreed, setFearGreed] = React.useState<{ value: number; classification: string } | null>(null);
  const [swarmStatus, setSwarmStatus] = React.useState<'idle' | 'voting' | 'decided'>('idle');
  const [lastSwarmDecision, setLastSwarmDecision] = React.useState<{ decision: string; symbol: string; consensus_score: number } | null>(null);
  const [fundingRates, setFundingRates] = React.useState<Record<string, { h8_pct: number; annual_pct: number }>>({});
  const [topMovers, setTopMovers] = React.useState<{ gainers: { symbol: string; change_24h: number }[]; losers: { symbol: string; change_24h: number }[] } | null>(null);
  
  const startupDoneRef = React.useRef(false);
  const wsRef = React.useRef<WebSocket | null>(null);
  const tokenRef = React.useRef<string | null>(null);
  const xtermInstancesRef = React.useRef<Map<string, any>>(new Map());

  React.useEffect(() => {
    const electron = (window as any).electron;
    if (electron?.vault?.get) {
      electron.vault.get('OPENGRAVITY_API_TOKEN').then((t: string) => { tokenRef.current = t; });
    }
    // Request notification permission
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, []);

  React.useEffect(() => {
    const tick = () => {
      setClock(new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    };
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, []);

  const addTerminal = React.useCallback((agentId: string) => {
    const agent = AGENTS.find(a => a.id === agentId) || AGENTS[0];
    const id = `term-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const newTerm: TerminalState = {
      id,
      agentId: agent.id,
      agentName: agent.name,
      agentIcon: agent.icon,
      model: agent.model,
    };
    setTerminals(prev => [...prev, newTerm]);
    setActiveTab(id);
    setShowPicker(false);
    setSearchQuery('');
    // El nuevo XTermPanel montará y llamará xterm.focus() solo.
    // Re-enfocamos también en el siguiente tick para garantizarlo.
    setTimeout(() => xtermInstancesRef.current.get(id)?.focus(), 50);
  }, []);

  const closeTerminal = React.useCallback((id: string) => {
    (window as any).electron?.pty?.kill(id);
    setTerminals(prev => {
      const next = prev.filter(t => t.id !== id);
      if (activeTab === id) setActiveTab(next.length > 0 ? next[next.length - 1].id : null);
      return next;
    });
  }, [activeTab]);

  const closeActiveTerminal = React.useCallback(() => {
    if (activeTab) closeTerminal(activeTab);
  }, [activeTab, closeTerminal]);

  React.useEffect(() => {
    if (startupDoneRef.current) return;
    startupDoneRef.current = true;
    STARTUP_AGENTS.forEach(({ agentId, delay }) => {
      setTimeout(() => addTerminal(agentId), delay);
    });
  }, [addTerminal]);

  React.useEffect(() => {
    const railwayUrl = 'wss://chic-encouragement-production.up.railway.app/ws';
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let alive = true;

    const connect = () => {
      if (!alive) return;
      setCloudStatus('connecting');
      try {
        const ws = new WebSocket(railwayUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!alive) { ws.close(); return; }
          setCloudStatus('connected');
          // Token is optional — server skips check if OPENGRAVITY_API_TOKEN not set on Railway
          ws.send(JSON.stringify({
            type: 'subscribe',
            symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
            ...(tokenRef.current ? { token: tokenRef.current } : {}),
          }));
        };

        ws.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data);
            if (data.type === 'price_update') {
              setPrices((prev: Record<string, number>) => ({ ...prev, [data.symbol]: data.price }));
            } else if (data.type === 'fear_greed') {
              setFearGreed({ value: data.value, classification: data.classification });
            } else if (data.type === 'funding_update') {
              setFundingRates(data.rates || {});
            } else if (data.type === 'top_movers') {
              setTopMovers({ gainers: (data.gainers || []).slice(0, 3), losers: (data.losers || []).slice(0, 3) });
            } else if (data.type === 'swarm_decision') {
              setLastSwarmDecision({ decision: data.decision, symbol: data.symbol, consensus_score: data.consensus_score });
              setSwarmStatus('decided');
              setTimeout(() => setSwarmStatus('idle'), 30000);
              // Native notification
              if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
                new Notification(`Swarm: ${data.decision} ${data.symbol || ''}`, {
                  body: `Consenso: ${data.consensus_score != null ? Math.round(data.consensus_score * 100) + '%' : 'N/A'}`,
                });
              }
            }
          } catch {}
        };

        ws.onclose = (ev) => {
          console.info('[WS] Closed', ev.code, ev.reason);
          setCloudStatus('disconnected');
          if (alive) retryTimer = setTimeout(connect, 5000);
        };

        ws.onerror = (err) => {
          console.warn('[WS] Error', err);
          ws.close();
        };
      } catch (err) {
        console.error('[WS] Failed to create WebSocket', err);
        setCloudStatus('disconnected');
        if (alive) retryTimer = setTimeout(connect, 5000);
      }
    };

    connect();
    return () => {
      alive = false;
      if (retryTimer) clearTimeout(retryTimer);
      wsRef.current?.close();
    };
  }, []);

  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 't') { e.preventDefault(); setShowPicker(true); }
      if (e.ctrlKey && e.key === 'g') { e.preventDefault(); setIsGridView(v => !v); }
      if (e.ctrlKey && e.key === 'w') { e.preventDefault(); closeActiveTerminal(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [terminals, activeTab, closeActiveTerminal]);

  const filteredAgents = AGENTS.filter(a =>
    !searchQuery || a.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    a.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const gridClass = `terminal-grid grid-${Math.min(terminals.length, 6)}`;

  return (
    <div className="app-container">
      <Head>
        <title>OpenGravity</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css" />
      </Head>

      <div className="accent-bar" />

      <nav className="top-nav">
        <span className="logo">OPENGRAVITY</span>
        <div className="separator" />
        <button className="nav-tab active">TERMINALS</button>
        <div className="nav-spacer" />

        <button className="btn-new-terminal" onClick={() => setShowPicker(true)}>+ Terminal</button>

        {terminals.length > 0 && (
          <div className="view-toggle">
            <button className={!isGridView ? 'active' : ''} onClick={() => setIsGridView(false)}>⊞</button>
            <button className={isGridView ? 'active' : ''} onClick={() => setIsGridView(true)}>⊟</button>
          </div>
        )}

        {Object.keys(prices).length > 0 && (
          <div className="price-ticker">
            {prices['BTCUSDT'] && <span>BTC <b>${prices['BTCUSDT'].toLocaleString()}</b></span>}
            {prices['ETHUSDT'] && <span>ETH <b>${prices['ETHUSDT'].toLocaleString()}</b></span>}
            {prices['SOLUSDT'] && <span>SOL <b>${prices['SOLUSDT'].toLocaleString()}</b></span>}
          </div>
        )}

        {fearGreed && (
          <div
            className={`fear-greed-badge ${fearGreed.value <= 25 ? 'extreme-fear' : fearGreed.value <= 45 ? 'fear' : fearGreed.value <= 55 ? 'neutral' : fearGreed.value <= 75 ? 'greed' : 'extreme-greed'}`}
            title={`Fear & Greed: ${fearGreed.classification}`}
          >
            F&G <b>{fearGreed.value}</b>
          </div>
        )}

        {Object.keys(fundingRates).length > 0 && (
          <div className="funding-ticker" title="Funding rates 8h (HyperLiquid)">
            {['BTC', 'ETH', 'SOL'].filter(c => fundingRates[c]).map(coin => {
              const r = fundingRates[coin];
              const isPos = r.h8_pct >= 0;
              return (
                <span key={coin} style={{ color: isPos ? '#00e676' : '#ff5252' }} title={`Anual: ${r.annual_pct}%`}>
                  {coin} <b>{isPos ? '+' : ''}{r.h8_pct}%</b>
                </span>
              );
            })}
          </div>
        )}

        {topMovers && ((topMovers.gainers?.length || 0) > 0 || (topMovers.losers?.length || 0) > 0) && (
          <div className="top-movers-ticker" title="Top movers 24h (CoinGecko)">
            {(topMovers.gainers || []).slice(0, 2).map(g => (
              <span key={g.symbol} style={{ color: '#00e676' }}>▲{g.symbol} <b>{g.change_24h > 0 ? '+' : ''}{g.change_24h}%</b></span>
            ))}
            {(topMovers.losers || []).slice(0, 2).map(l => (
              <span key={l.symbol} style={{ color: '#ff5252' }}>▼{l.symbol} <b>{l.change_24h}%</b></span>
            ))}
          </div>
        )}

        <button
          className="btn-swarm"
          title="Iniciar Swarm Analysis"
          onClick={() => {
            const existing = terminals.find(t => t.agentId === 'swarm-agent');
            if (!existing) addTerminal('swarm-agent');
            else setActiveTab(existing.id);
            setSwarmStatus('voting');
          }}
        >
          {swarmStatus === 'idle' ? '🐝 Swarm' : swarmStatus === 'voting' ? '🐝 Voting...' : `🐝 ${lastSwarmDecision?.decision || 'OK'}`}
        </button>

        {lastSwarmDecision && swarmStatus === 'decided' && (
          <div className={`swarm-badge decided-${(lastSwarmDecision.decision || 'hold').toLowerCase()}`}>
            {lastSwarmDecision.decision} {lastSwarmDecision.symbol} {lastSwarmDecision.consensus_score != null ? `${Math.round(lastSwarmDecision.consensus_score * 100)}%` : ''}
          </div>
        )}

        <div className={`cloud-indicator ${cloudStatus}`} title={`Railway: ${cloudStatus.toUpperCase()}`}>
          <div className="dot" />
          <span className="cloud-label">{cloudStatus === 'connected' ? 'LIVE' : cloudStatus === 'connecting' ? '...' : 'OFF'}</span>
        </div>

        <span className="clock">{clock}</span>

        <div className="window-controls">
          <button onClick={() => (window as any).electron?.minimize()}>─</button>
          <button onClick={() => (window as any).electron?.maximize()}>□</button>
          <button className="close" onClick={() => (window as any).electron?.close()}>✕</button>
        </div>
      </nav>

      <div className="terminal-area">
        {terminals.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">⌨</div>
            <button className="empty-btn" onClick={() => setShowPicker(true)}>+ Nueva Terminal</button>
          </div>
        ) : isGridView ? (
          <div className={gridClass}>
            {terminals.map(term => (
              <XTermPanel key={term.id} terminal={term} onClose={() => closeTerminal(term.id)} instancesRef={xtermInstancesRef} />
            ))}
          </div>
        ) : (
          <div className="terminal-tabs">
            <div className="tab-bar">
              {terminals.map(term => (
                <div key={term.id} className={`tab-item ${activeTab === term.id ? 'active' : ''}`} onClick={() => setActiveTab(term.id)}>
                  <span>{term.agentIcon} {term.agentName}</span>
                  <button className="tab-close" onClick={(e) => { e.stopPropagation(); closeTerminal(term.id); }}>✕</button>
                </div>
              ))}
            </div>
            <div className="tab-content">
              {terminals.filter(t => t.id === activeTab).map(term => (
                <XTermPanel key={term.id} terminal={term} onClose={() => closeTerminal(term.id)} showHeader={false} instancesRef={xtermInstancesRef} />
              ))}
            </div>
          </div>
        )}
      </div>

      {showPicker && (
        <div className="modal-overlay" onClick={() => {
          setShowPicker(false);
          setTimeout(() => {
            const target = activeTab ?? terminals[terminals.length - 1]?.id;
            if (target) xtermInstancesRef.current.get(target)?.focus();
          }, 50);
        }}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <input
              className="modal-search"
              placeholder="🔍 Buscar agente..."
              autoFocus
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
            <div className="modal-body">
              {filteredAgents.map(agent => (
                <div key={agent.id} className="agent-option" onClick={() => addTerminal(agent.id)} style={{flexWrap: 'wrap'}}>
                  <span className="agent-name" style={{flex: 1}}>{agent.icon} {agent.name}</span>
                  <span className={`agent-badge ${agent.model}`}>{agent.model}</span>
                  <span style={{width: '100%', fontSize: '10px', color: '#666', marginTop: '2px'}}>{agent.description}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function XTermPanel(props: { terminal: TerminalState; onClose: () => void; showHeader?: boolean; instancesRef?: React.MutableRefObject<Map<string, any>> }) {
  const { terminal, onClose, showHeader = true, instancesRef } = props;
  const xtermRef = React.useRef<HTMLDivElement>(null);
  const termInstanceRef = React.useRef<any>(null);
  const fitAddonRef = React.useRef<any>(null);

  React.useEffect(() => {
    if (!Terminal || !xtermRef.current) return;
    const xterm = new Terminal({
      theme: { background: '#050505', foreground: '#ffffff', selectionBackground: '#3a3a5c' },
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 13,
      scrollback: 10000,
      smoothScrollDuration: 100,
      allowProposedApi: true,
      rightClickSelectsWord: true,
    });
    termInstanceRef.current = xterm;
    instancesRef?.current.set(terminal.id, xterm);
    if (FitAddon) {
      const fit = new FitAddon();
      fitAddonRef.current = fit;
      xterm.loadAddon(fit);
    }
    xterm.open(xtermRef.current);
    fitAddonRef.current?.fit();
    xterm.focus();

    const electron = (window as any).electron;

    // Ctrl+C copies when text is selected, otherwise sends SIGINT
    // Ctrl+V pastes from clipboard
    xterm.attachCustomKeyEventHandler((e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'c' && e.type === 'keydown' && xterm.hasSelection()) {
        navigator.clipboard.writeText(xterm.getSelection());
        return false; // prevent sending to PTY
      }
      if (e.ctrlKey && e.key === 'v' && e.type === 'keydown') {
        navigator.clipboard.readText().then(text => {
          electron?.pty?.write(terminal.id, text);
        }).catch(() => {});
        return false;
      }
      return true;
    });

    xterm.onData((d: string) => electron?.pty?.write(terminal.id, d));

    // Use cleanup-capable listener to prevent memory leaks
    const removeDataListener = electron?.pty?.onData((id: string, d: string) => {
      if (id === terminal.id) xterm.write(d);
    });

    electron?.pty?.create(terminal.id, terminal.agentId, xterm.rows, xterm.cols);

    // Debounced fit helper — used by both window resize and ResizeObserver
    let resizeTimer: ReturnType<typeof setTimeout>;
    const doFit = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        try {
          fitAddonRef.current?.fit();
          const cols = termInstanceRef.current?.cols;
          const rows = termInstanceRef.current?.rows;
          if (cols && rows) electron?.pty?.resize(terminal.id, cols, rows);
        } catch {}
      }, 80);
    };

    // Window resize (maximize, restore, drag edges)
    window.addEventListener('resize', doFit);

    // ResizeObserver — detects grid layout changes (add/remove terminals)
    let observer: ResizeObserver | null = null;
    if (xtermRef.current) {
      observer = new ResizeObserver(doFit);
      observer.observe(xtermRef.current);
    }

    return () => {
      clearTimeout(resizeTimer);
      removeDataListener?.();
      window.removeEventListener('resize', doFit);
      observer?.disconnect();
      instancesRef?.current.delete(terminal.id);
      xterm.dispose();
    };
  }, [terminal.id, terminal.agentId]);

  return (
    <div className="terminal-panel">
      {showHeader && (
        <div className="terminal-header">
          <span>{terminal.agentIcon} {terminal.agentName}</span>
          <button onClick={onClose}>✕</button>
        </div>
      )}
      <div className="terminal-body" ref={xtermRef} />
    </div>
  );
}
