import * as React from 'react';
import Head from 'next/head';

// ── Agent definitions ──
const AGENTS = [
  { id: 'claude-main', name: 'Claude (Principal)', icon: '🤖', model: 'sonnet', description: 'Orquestador principal' },
  { id: 'trading-agent', name: 'Trading Agent', icon: '📈', model: 'sonnet', description: 'Decisiones de compra/venta' },
  { id: 'risk-agent', name: 'Risk Agent', icon: '🛡️', model: 'sonnet', description: 'Métricas avanzadas y VaR' },
  { id: 'strategy-agent', name: 'Strategy Agent', icon: '📋', model: 'sonnet', description: 'Ciclo de vida de estrategias' },
  { id: 'rbi-agent', name: 'RBI Agent', icon: '🧪', model: 'sonnet', description: 'Investigación de estrategias' },
  { id: 'backtest-architect', name: 'Backtest Architect', icon: '⚙️', model: 'sonnet', description: 'Ejecuta y valida backtests' },
  { id: 'chart-agent', name: 'Chart Agent', icon: '📉', model: 'sonnet', description: 'Price action y patrones' },
  { id: 'funding-agent', name: 'Funding Agent', icon: '💰', model: 'haiku', description: 'Funding rates HyperLiquid' },
  { id: 'swarm-agent', name: 'Swarm Agent', icon: '🐝', model: 'opus', description: 'Orquestador multi-agente' },
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
  const [swarmStatus, setSwarmStatus] = React.useState<'idle' | 'voting' | 'decided'>('idle');
  const [lastSwarmDecision, setLastSwarmDecision] = React.useState<{ decision: string; symbol: string; consensus_score: number } | null>(null);
  const [activeView, setActiveView] = React.useState<'terminals' | 'market' | 'polymarket'>('terminals');
  const [fundingData, setFundingData] = React.useState<Record<string, { h8_pct: number; annual_pct: number }>>({});
  const [stressData, setStressData] = React.useState<Array<{ coin: string; score: number; annual_funding_pct: number; direction: string; signals: string[] }>>([]);
  const [liquidationData, setLiquidationData] = React.useState<Array<{ coin: string; side: string; usd_size: number; px?: string; sz?: string; time_ms?: number; tid?: number; leverage?: number; liq_px?: string; entry_px?: string; margin_used?: string; _new?: boolean }>>([]);
  const [whaleData, setWhaleData] = React.useState<{ longs: any[]; shorts: any[] }>({ longs: [], shorts: [] });
  
  const startupDoneRef = React.useRef(false);
  const wsRef = React.useRef<WebSocket | null>(null);
  const tokenRef = React.useRef<string | null>(null);
  const xtermInstancesRef = React.useRef<Map<string, any>>(new Map());
  const CLOUD_URL = 'https://chic-encouragement-production.up.railway.app';

  // Fetch all market data in one request (for initial load / tab switch)
  const fetchMarketData = React.useCallback(async () => {
    try {
      const res = await fetch(`${CLOUD_URL}/api/market/snapshot`);
      const snap = await res.json();
      if (snap.stress?.length > 0) setStressData(snap.stress);
      if (snap.funding && Object.keys(snap.funding).length > 0) setFundingData(snap.funding);
      if (snap.liquidations?.length > 0) setLiquidationData(snap.liquidations.map((l: any) => ({ ...l, _new: false })));
      if (snap.whales?.longs?.length > 0 || snap.whales?.shorts?.length > 0) {
        setWhaleData(snap.whales);
      }
    } catch {}
  }, []);

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
          ws.send(JSON.stringify({
            type: 'subscribe',
            ...(tokenRef.current ? { token: tokenRef.current } : {}),
          }));
          // Fetch current market data immediately (don't wait for scheduler)
          fetchMarketData();
        };

        ws.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data);
            if (data.type === 'swarm_decision') {
              setLastSwarmDecision({ decision: data.decision, symbol: data.symbol, consensus_score: data.consensus_score });
              setSwarmStatus('decided');
              setTimeout(() => setSwarmStatus('idle'), 30000);
              if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
                new Notification(`Swarm: ${data.decision} ${data.symbol || ''}`, {
                  body: `Consenso: ${data.consensus_score != null ? Math.round(data.consensus_score * 100) + '%' : 'N/A'}`,
                });
              }
            }
            if (data.type === 'funding_update') setFundingData(data.rates || {});
            if (data.type === 'stress_update') setStressData(data.rankings || []);
            if (data.type === 'liquidation_update') {
              const incoming = (data.liquidations || []).map((l: any) => ({ ...l, _new: true }));
              setLiquidationData(prev => {
                // Deduplicate by tid, then merge (new first), keep max 50
                const existingTids = new Set(prev.map(p => p.tid).filter(Boolean));
                const fresh = incoming.filter((l: any) => !l.tid || !existingTids.has(l.tid));
                if (fresh.length === 0) return prev;
                const merged = [...fresh, ...prev.map(p => ({ ...p, _new: false }))].slice(0, 50);
                return merged;
              });
            }
            if (data.type === 'whale_update') setWhaleData({ longs: data.longs || [], shorts: data.shorts || [] });
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
      </Head>

      <div className="accent-bar" />

      <nav className="top-nav">
        <span className="logo">OPENGRAVITY</span>
        <div className="separator" />
        <button className={`nav-tab ${activeView === 'terminals' ? 'active' : ''}`} onClick={() => setActiveView('terminals')}>TERMINALS</button>
        <button className={`nav-tab ${activeView === 'market' ? 'active' : ''}`} onClick={() => { setActiveView('market'); fetchMarketData(); }}>MARKET</button>
        <button className={`nav-tab ${activeView === 'polymarket' ? 'active' : ''}`} onClick={() => setActiveView('polymarket')}>POLYMARKET</button>
        <div className="nav-spacer" />

        <button className="btn-new-terminal" onClick={() => setShowPicker(true)}>+ Terminal</button>

        {terminals.length > 0 && (
          <div className="view-toggle">
            <button className={!isGridView ? 'active' : ''} onClick={() => setIsGridView(false)}>⊞</button>
            <button className={isGridView ? 'active' : ''} onClick={() => setIsGridView(true)}>⊟</button>
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
        {/* All panels always mounted — hidden via CSS to preserve terminal state */}
        <div style={{ display: activeView === 'terminals' ? 'contents' : 'none' }}>
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
        <div style={{ display: activeView === 'market' ? 'contents' : 'none' }}>
          <MarketPanel fundingData={fundingData} stressData={stressData} liquidationData={liquidationData} whaleData={whaleData} />
        </div>
        <div style={{ display: activeView === 'polymarket' ? 'contents' : 'none' }}>
          <PolymarketPanel />
        </div>
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

// ── Polymarket Dashboard ───────────────────────────────────────────────────────

function PolymarketPanel() {
  const [data, setData] = React.useState<any>(null);
  const [lastUpdated, setLastUpdated] = React.useState<Date | null>(null);
  const [cycleRunning, setCycleRunning] = React.useState(false);
  const [nextCycle, setNextCycle] = React.useState<string | null>(null);
  const [botEnabled, setBotEnabled] = React.useState(true);

  const load = React.useCallback(async () => {
    const electron = (window as any).electron;
    if (!electron?.polymarket?.getData) return;
    try {
      const result = await electron.polymarket.getData();
      setData(result);
      setLastUpdated(new Date());
    } catch {}
  }, []);

  const manualRefresh = React.useCallback(async () => {
    const electron = (window as any).electron;
    if (!electron?.polymarket?.runCycle || cycleRunning) return;
    await electron.polymarket.runCycle();
  }, [cycleRunning]);

  const toggleBot = React.useCallback(async () => {
    const electron = (window as any).electron;
    if (!electron?.polymarket?.toggle) return;
    const result = await electron.polymarket.toggle();
    setBotEnabled(result.enabled);
  }, []);

  React.useEffect(() => {
    load();
    const electron = (window as any).electron;
    // Get initial bot enabled state
    electron?.polymarket?.getStatus?.().then((s: any) => setBotEnabled(s.enabled));
    // Real-time data push from fs.watch + bot cycles
    const unsubData = electron?.polymarket?.onUpdate?.((newData: any) => {
      setData(newData);
      setLastUpdated(new Date());
    });
    // Cycle status (running/done)
    const unsubStatus = electron?.polymarket?.onCycleStatus?.((status: any) => {
      setCycleRunning(status.running);
      if (!status.running && status.lastCycle) {
        const next = new Date(new Date(status.lastCycle).getTime() + 15 * 60 * 1000);
        setNextCycle(next.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }));
      }
    });
    return () => {
      unsubData?.();
      unsubStatus?.();
    };
  }, [load]);

  if (!data) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--muted)' }}>Cargando datos Polymarket...</div>;
  }

  const { portfolio, log, priors, scanReport, trackedWallets, walletPositions, copyPositions, walletSummary } = data;
  const positions: any[] = portfolio?.positions || [];
  const closed: any[] = portfolio?.closed || [];
  const stats = portfolio?.stats || {};
  const bank: number = portfolio?.bank ?? 0;
  const deployed: number = portfolio?.deployed ?? 0;
  const totalUnrealized: number = positions.reduce((s: number, p: any) => s + (p.unrealized_pnl ?? 0), 0);
  const totalPnl: number = (stats.total_pnl ?? 0) + totalUnrealized;
  const winRate: number = stats.trades > 0 ? Math.round((stats.wins / stats.trades) * 100) : 0;

  // P&L chart data — build a cumulative line from log entries
  const pnlPoints: number[] = [];
  let cumPnl = 0;
  for (const entry of log) {
    if (entry.type === 'CLOSE_PAPER' && entry.position?.realized_pnl != null) {
      cumPnl += entry.position.realized_pnl;
      pnlPoints.push(cumPnl);
    }
  }
  // Append current unrealized as last point
  pnlPoints.push(cumPnl + totalUnrealized);

  // SVG P&L line chart
  const chartW = 400;
  const chartH = 80;
  const padX = 4;
  const padY = 8;
  const innerW = chartW - padX * 2;
  const innerH = chartH - padY * 2;
  const minP = Math.min(0, ...pnlPoints);
  const maxP = Math.max(0, ...pnlPoints);
  const range = maxP - minP || 1;
  const toX = (i: number) => padX + (i / Math.max(pnlPoints.length - 1, 1)) * innerW;
  const toY = (v: number) => padY + innerH - ((v - minP) / range) * innerH;
  const linePath = pnlPoints.map((v, i) => `${i === 0 ? 'M' : 'L'}${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
  const zeroY = toY(0).toFixed(1);
  const lineColor = totalPnl >= 0 ? '#00ff88' : '#ff4455';

  // Scan signals from report
  const signals: any[] = scanReport?.signals || [];
  // Bayesian priors
  const priorEntries = Object.entries(priors || {});

  const fmt = (v: number, decimals = 2) => v >= 0 ? `+${v.toFixed(decimals)}` : v.toFixed(decimals);
  const fmtPct = (entry: number, base: number) => base !== 0 ? fmt((entry / base) * 100, 1) + '%' : '0%';
  const dirColor = (dir: string) => dir === 'BUY_YES' ? 'var(--neon-green)' : 'var(--neon-orange)';
  const pnlColor = (v: number) => v >= 0 ? 'var(--neon-green)' : 'var(--red)';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '16px', height: '100%', overflowY: 'auto', boxSizing: 'border-box' }}>

      {/* ── Header: Stats + Bot Controls ── */}
      <div style={{ display: 'flex', gap: '8px', alignItems: 'stretch' }}>
        {/* Stats cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '8px', flex: 1 }}>
          {[
            { label: 'BANK', value: `$${bank.toFixed(0)}`, color: 'var(--text-primary)' },
            { label: 'DEPLOYED', value: `$${deployed.toFixed(0)}`, color: 'var(--neon-cyan)' },
            { label: 'P&L TOTAL', value: `$${totalPnl.toFixed(2)}`, color: pnlColor(totalPnl) },
            { label: 'WIN RATE', value: `${winRate}% (${stats.trades ?? 0} trades)`, color: winRate >= 50 ? 'var(--neon-green)' : 'var(--muted)' },
            { label: 'ACTUALIZADO', value: lastUpdated ? lastUpdated.toLocaleTimeString('es-ES') : '—', color: 'var(--muted)' },
          ].map(s => (
            <div key={s.label} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px 12px' }}>
              <div style={{ fontSize: '10px', color: 'var(--muted)', marginBottom: '4px', letterSpacing: '0.05em' }}>{s.label}</div>
              <div style={{ fontSize: '15px', fontWeight: 600, color: s.color }}>{s.value}</div>
            </div>
          ))}
        </div>

        {/* Bot status + refresh */}
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: '6px', minWidth: '140px', justifyContent: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: !botEnabled ? '#ff4455' : cycleRunning ? '#ffab00' : '#00e676', animation: cycleRunning ? 'pulse 1s infinite' : 'none' }} />
            <span style={{ fontSize: '10px', color: !botEnabled ? '#ff4455' : cycleRunning ? '#ffab00' : 'var(--muted)', fontWeight: 600 }}>
              {!botEnabled ? 'DETENIDO' : cycleRunning ? 'EJECUTANDO...' : 'AUTO 15min'}
            </span>
          </div>
          {botEnabled && nextCycle && !cycleRunning && (
            <div style={{ fontSize: '9px', color: 'var(--muted)' }}>Prox: {nextCycle}</div>
          )}
          <div style={{ display: 'flex', gap: '4px' }}>
            <button
              disabled={cycleRunning}
              onClick={manualRefresh}
              title="Ejecutar ciclo ahora: scan + update + resolve"
              style={{
                flex: 1, padding: '5px 8px', fontSize: '10px', fontWeight: 600,
                background: cycleRunning ? '#1a1a2e' : 'var(--neon-cyan)',
                color: cycleRunning ? 'var(--muted)' : '#000',
                border: '1px solid var(--border)', borderRadius: '4px',
                cursor: cycleRunning ? 'wait' : 'pointer',
                transition: 'all 0.2s',
              }}
            >
              {cycleRunning ? '...' : 'REFRESH'}
            </button>
            <button
              onClick={toggleBot}
              title={botEnabled ? 'Detener auto-ciclo' : 'Iniciar auto-ciclo'}
              style={{
                padding: '5px 10px', fontSize: '10px', fontWeight: 700,
                background: botEnabled ? '#ff445520' : '#00e67620',
                color: botEnabled ? '#ff4455' : '#00e676',
                border: `1px solid ${botEnabled ? '#ff445540' : '#00e67640'}`, borderRadius: '4px',
                cursor: 'pointer', transition: 'all 0.2s',
              }}
            >
              {botEnabled ? 'OFF' : 'ON'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Two-column layout: positions + chart/signals ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 380px', gap: '12px', flex: 1, minHeight: 0 }}>

        {/* Left column: Open Positions */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', minHeight: 0 }}>
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden', flex: '0 0 auto' }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', fontSize: '11px', letterSpacing: '0.08em', color: 'var(--muted)' }}>
              POSICIONES ABIERTAS ({positions.length})
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ color: 'var(--muted)', fontSize: '10px' }}>
                    {['MERCADO', 'DIR', 'ENTRADA', 'ACTUAL', 'P&L $', 'P&L %', 'DIAS', 'SL', 'TP'].map(h => (
                      <th key={h} style={{ padding: '6px 8px', textAlign: h === 'MERCADO' ? 'left' : 'right', fontWeight: 400, borderBottom: '1px solid var(--border)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {positions.length === 0 ? (
                    <tr><td colSpan={9} style={{ padding: '16px', textAlign: 'center', color: 'var(--muted)' }}>Sin posiciones abiertas</td></tr>
                  ) : positions.map((p: any, i: number) => {
                    const pnlPct = p.entry_price > 0 ? ((p.current_price - p.entry_price) / p.entry_price) * 100 : 0;
                    return (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle, #1a1a2e)' }}>
                        <td style={{ padding: '6px 8px', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.question}>{p.question}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: dirColor(p.direction), fontWeight: 600 }}>{p.direction === 'BUY_YES' ? 'YES' : 'NO'}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right' }}>{(p.entry_price * 100).toFixed(1)}¢</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right' }}>{(p.current_price * 100).toFixed(1)}¢</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: pnlColor(p.unrealized_pnl ?? 0) }}>{fmt(p.unrealized_pnl ?? 0)}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: pnlColor(pnlPct) }}>{pnlPct.toFixed(1)}%</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: p.days_left < 14 ? 'var(--neon-orange)' : 'var(--muted)' }}>{p.days_left}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: 'var(--muted)' }}>{(p.stop_loss_price * 100).toFixed(1)}¢</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: 'var(--muted)' }}>{(p.take_profit_price * 100).toFixed(1)}¢</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Closed Trades */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden', flex: '0 0 auto' }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', fontSize: '11px', letterSpacing: '0.08em', color: 'var(--muted)' }}>
              HISTORIAL CERRADO ({closed.length})
            </div>
            {closed.length === 0 ? (
              <div style={{ padding: '12px', color: 'var(--muted)', fontSize: '12px', textAlign: 'center' }}>Sin trades cerrados aún</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                  <thead>
                    <tr style={{ color: 'var(--muted)', fontSize: '10px' }}>
                      {['MERCADO', 'DIR', 'ENTRADA', 'SALIDA', 'P&L $', 'MOTIVO'].map(h => (
                        <th key={h} style={{ padding: '6px 8px', textAlign: h === 'MERCADO' ? 'left' : 'right', fontWeight: 400, borderBottom: '1px solid var(--border)' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {closed.slice(-10).reverse().map((p: any, i: number) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle, #1a1a2e)' }}>
                        <td style={{ padding: '6px 8px', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.question}>{p.question}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: dirColor(p.direction) }}>{p.direction === 'BUY_YES' ? 'YES' : 'NO'}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right' }}>{(p.entry_price * 100).toFixed(1)}¢</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right' }}>{((p.exit_price ?? 0) * 100).toFixed(1)}¢</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: pnlColor(p.realized_pnl ?? 0) }}>{fmt(p.realized_pnl ?? 0)}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: 'var(--muted)', fontSize: '10px' }}>{p.close_reason ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Right column: P&L Chart + Signals + Priors */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', minHeight: 0 }}>

          {/* P&L Chart */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px' }}>
            <div style={{ fontSize: '11px', letterSpacing: '0.08em', color: 'var(--muted)', marginBottom: '8px' }}>P&L ACUMULADO</div>
            <svg width="100%" viewBox={`0 0 ${chartW} ${chartH}`} style={{ overflow: 'visible' }}>
              {/* Zero line */}
              <line x1={padX} y1={zeroY} x2={chartW - padX} y2={zeroY} stroke="var(--border)" strokeWidth="1" strokeDasharray="3,3" />
              {/* P&L line */}
              {pnlPoints.length > 1 && (
                <path d={linePath} fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" />
              )}
              {/* Last point dot */}
              {pnlPoints.length > 0 && (
                <circle cx={toX(pnlPoints.length - 1)} cy={toY(pnlPoints[pnlPoints.length - 1])} r="3" fill={lineColor} />
              )}
              {/* Axes labels */}
              <text x={padX} y={chartH - 1} fill="var(--muted)" fontSize="9">${minP.toFixed(0)}</text>
              <text x={padX} y={padY + 6} fill="var(--muted)" fontSize="9">${maxP.toFixed(0)}</text>
            </svg>
            <div style={{ fontSize: '11px', color: pnlColor(totalPnl), fontWeight: 600, marginTop: '4px' }}>
              {fmt(totalPnl)} USD total ({pnlPoints.length} puntos)
            </div>
          </div>

          {/* Last Scan Signals */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden', flex: 1, minHeight: 0 }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', fontSize: '11px', letterSpacing: '0.08em', color: 'var(--muted)' }}>
              ULTIMO SCAN ({signals.length} señales)
            </div>
            <div style={{ overflowY: 'auto', maxHeight: '180px' }}>
              {signals.length === 0 ? (
                <div style={{ padding: '12px', color: 'var(--muted)', fontSize: '12px', textAlign: 'center' }}>Sin señales. Ejecuta el bot para escanear.</div>
              ) : signals.slice(0, 10).map((s: any, i: number) => (
                <div key={i} style={{ padding: '6px 12px', borderBottom: '1px solid var(--border-subtle, #1a1a2e)', display: 'flex', gap: '8px', alignItems: 'center', fontSize: '11px' }}>
                  <span style={{ color: dirColor(s.direction), fontWeight: 600, flexShrink: 0 }}>{s.direction === 'BUY_YES' ? 'YES' : 'NO'}</span>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={s.question}>{s.question}</span>
                  <span style={{ color: 'var(--neon-cyan)', flexShrink: 0 }}>edge {(s.composite_edge * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          </div>

          {/* Bayesian Priors */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden' }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', fontSize: '11px', letterSpacing: '0.08em', color: 'var(--muted)' }}>
              PRIORS BAYESIANOS ({priorEntries.length})
            </div>
            <div style={{ overflowY: 'auto', maxHeight: '150px' }}>
              {priorEntries.length === 0 ? (
                <div style={{ padding: '12px', color: 'var(--muted)', fontSize: '12px', textAlign: 'center' }}>Sin priors registrados aún</div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
                  <thead>
                    <tr style={{ color: 'var(--muted)', fontSize: '10px' }}>
                      {['FUENTE', 'alpha', 'beta', 'TRADES'].map(h => (
                        <th key={h} style={{ padding: '5px 8px', textAlign: h === 'FUENTE' ? 'left' : 'right', fontWeight: 400, borderBottom: '1px solid var(--border)' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {priorEntries.map(([src, prior]: [string, any]) => (
                      <tr key={src} style={{ borderBottom: '1px solid var(--border-subtle, #1a1a2e)' }}>
                        <td style={{ padding: '5px 8px' }}>{src}</td>
                        <td style={{ padding: '5px 8px', textAlign: 'right', color: 'var(--neon-green)' }}>{(prior.alpha ?? 0).toFixed(1)}</td>
                        <td style={{ padding: '5px 8px', textAlign: 'right', color: 'var(--red)' }}>{(prior.beta ?? 0).toFixed(1)}</td>
                        <td style={{ padding: '5px 8px', textAlign: 'right', color: 'var(--muted)' }}>{prior.trades ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

        </div>
      </div>

      {/* ── Smart Money Radar ── */}
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden' }}>
        <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '11px', letterSpacing: '0.08em', color: 'var(--muted)' }}>
            SMART MONEY RADAR ({(trackedWallets || []).length} wallets)
          </span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button
              onClick={async () => { const e = (window as any).electron; await e?.polymarket?.walletDiscover?.(); }}
              title="Descubrir nuevas wallets del leaderboard"
              style={{ padding: '3px 8px', fontSize: '9px', fontWeight: 600, background: '#1a1a2e', color: 'var(--neon-cyan)', border: '1px solid var(--border)', borderRadius: '3px', cursor: 'pointer' }}
            >DISCOVER</button>
            <button
              onClick={async () => { const e = (window as any).electron; await e?.polymarket?.walletUpdate?.(); }}
              title="Actualizar posiciones de wallets tracked"
              style={{ padding: '3px 8px', fontSize: '9px', fontWeight: 600, background: '#1a1a2e', color: 'var(--neon-green)', border: '1px solid var(--border)', borderRadius: '3px', cursor: 'pointer' }}
            >UPDATE</button>
          </div>
        </div>

        {(!trackedWallets || trackedWallets.length === 0) ? (
          <div style={{ padding: '16px', color: 'var(--muted)', fontSize: '12px', textAlign: 'center' }}>
            Sin wallets tracked. Pulsa DISCOVER para escanear el leaderboard.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0', maxHeight: '220px', overflowY: 'auto' }}>
            {/* Left: Top wallets table */}
            <div style={{ borderRight: '1px solid var(--border)' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
                <thead>
                  <tr style={{ color: 'var(--muted)', fontSize: '9px' }}>
                    {['WALLET', 'PnL', 'ROI%', 'SCORE', 'STATUS'].map(h => (
                      <th key={h} style={{ padding: '4px 6px', textAlign: h === 'WALLET' ? 'left' : 'right', fontWeight: 400, borderBottom: '1px solid var(--border)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(trackedWallets || []).slice(0, 15).map((w: any, i: number) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle, #1a1a2e)' }}>
                      <td style={{ padding: '3px 6px', fontFamily: 'monospace', fontSize: '9px' }} title={w.address}>
                        {w.name || (w.address ? `${w.address.slice(0, 6)}...${w.address.slice(-4)}` : '—')}
                      </td>
                      <td style={{ padding: '3px 6px', textAlign: 'right', color: (w.pnl ?? 0) >= 0 ? 'var(--neon-green)' : 'var(--red)' }}>
                        ${((w.pnl ?? 0) / 1000).toFixed(0)}K
                      </td>
                      <td style={{ padding: '3px 6px', textAlign: 'right', color: (w.roi_pct ?? 0) >= 10 ? 'var(--neon-green)' : 'var(--muted)' }}>
                        {(w.roi_pct ?? 0).toFixed(1)}%
                      </td>
                      <td style={{ padding: '3px 6px', textAlign: 'right', color: (w.score ?? 0) >= 70 ? 'var(--neon-green)' : (w.score ?? 0) >= 40 ? '#ffab00' : 'var(--muted)' }}>
                        {w.score ?? 0}
                      </td>
                      <td style={{ padding: '3px 6px', textAlign: 'right' }}>
                        <span style={{
                          fontSize: '8px', padding: '1px 4px', borderRadius: '3px', fontWeight: 600,
                          background: w.validated ? '#00e67622' : '#ffab0022',
                          color: w.validated ? '#00e676' : '#ffab00',
                        }}>
                          {w.validated ? 'VALID' : 'TRACK'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Right: Smart money positions / hot markets */}
            <div>
              <div style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', fontSize: '9px', color: 'var(--muted)', letterSpacing: '0.06em' }}>
                HOT MARKETS (smart money concentración)
              </div>
              {(() => {
                const positions = walletPositions?.positions || walletPositions || {};
                const markets: Record<string, { yes: number; no: number; total: number; question: string }> = {};
                for (const [, wp] of Object.entries(positions)) {
                  const wPositions = Array.isArray(wp) ? wp : (wp as any)?.positions || [];
                  for (const p of wPositions) {
                    const cid = p.condition_id || p.market || '';
                    if (!cid) continue;
                    if (!markets[cid]) markets[cid] = { yes: 0, no: 0, total: 0, question: p.question || cid.slice(0, 20) };
                    const dir = (p.direction || '').toUpperCase();
                    if (dir.includes('YES') || dir === 'BUY') markets[cid].yes++;
                    else markets[cid].no++;
                    markets[cid].total++;
                  }
                }
                const sorted = Object.entries(markets).sort(([, a], [, b]) => b.total - a.total).slice(0, 8);
                if (sorted.length === 0) {
                  return <div style={{ padding: '12px', color: 'var(--muted)', fontSize: '11px', textAlign: 'center' }}>Sin datos de posiciones. Pulsa UPDATE.</div>;
                }
                return sorted.map(([cid, m]) => (
                  <div key={cid} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle, #1a1a2e)', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10px' }}>
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={m.question}>{m.question}</span>
                    <span style={{ color: 'var(--neon-green)', fontWeight: 600 }}>{m.yes}Y</span>
                    <span style={{ color: 'var(--neon-orange)', fontWeight: 600 }}>{m.no}N</span>
                    <span style={{ color: 'var(--muted)', fontSize: '9px' }}>{m.total}w</span>
                  </div>
                ));
              })()}
            </div>
          </div>
        )}
      </div>

      {/* ── Copy Trading Panel ── */}
      {(() => {
        const cp = copyPositions || {};
        const cpPositions: any[] = cp.positions || [];
        const cpClosed: any[] = (cp.closed || []).slice(-10).reverse();
        const cpStats = cp.stats || {};
        const cpBank = cp.bank ?? 0;
        const cpDeployed = cp.deployed ?? 0;
        const cpTotalPnl = cpStats.total_pnl ?? 0;
        const cpUnrealized = cpPositions.reduce((s: number, p: any) => s + (p.unrealized_pnl ?? 0), 0);
        const cpWR = cpStats.trades > 0 ? Math.round((cpStats.wins / cpStats.trades) * 100) : 0;
        const walletPnl = cp.wallet_pnl || {};
        const activeWallets = (trackedWallets || []).filter((w: any) => !w.discarded);
        const discardedWallets = (trackedWallets || []).filter((w: any) => w.discarded);

        return (
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden' }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', letterSpacing: '0.08em', color: 'var(--muted)' }}>
                COPY TRADING ({cpPositions.length} abiertas | {cpStats.trades ?? 0} cerradas)
              </span>
              <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                <span style={{ fontSize: '9px', color: 'var(--muted)' }}>Auto: 4h</span>
                <button
                  onClick={async () => { const e = (window as any).electron; await e?.polymarket?.copyCycle?.(); }}
                  title="Ejecutar ciclo copy trading: discover + copy + discard"
                  style={{ padding: '3px 8px', fontSize: '9px', fontWeight: 600, background: '#1a1a2e', color: '#ffab00', border: '1px solid var(--border)', borderRadius: '3px', cursor: 'pointer' }}
                >FULL CYCLE</button>
                <button
                  onClick={async () => {
                    const e = (window as any).electron;
                    const r = await e?.polymarket?.daemonInstall?.();
                    alert(r?.output || 'Daemon instalado. Se ejecutará al iniciar sesión (2 min tras login).');
                  }}
                  title="Instalar daemon en Windows Task Scheduler — corre automáticamente al login, sin app abierta"
                  style={{ padding: '3px 8px', fontSize: '9px', fontWeight: 600, background: '#0d2b0d', color: '#4caf50', border: '1px solid #4caf50', borderRadius: '3px', cursor: 'pointer' }}
                >INSTALL DAEMON</button>
                <button
                  onClick={async () => {
                    const e = (window as any).electron;
                    const r = await e?.polymarket?.daemonStatus?.();
                    alert(r?.output || 'Daemon no instalado.');
                  }}
                  title="Ver estado del daemon y últimas líneas del log"
                  style={{ padding: '3px 8px', fontSize: '9px', fontWeight: 600, background: '#1a1a1a', color: 'var(--muted)', border: '1px solid var(--border)', borderRadius: '3px', cursor: 'pointer' }}
                >DAEMON LOG</button>
              </div>
            </div>

            {/* Copy Stats Row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '0', borderBottom: '1px solid var(--border)' }}>
              {[
                { label: 'BANK', value: `$${cpBank.toFixed(0)}`, color: 'var(--text-primary)' },
                { label: 'DEPLOYED', value: `$${cpDeployed.toFixed(0)}`, color: 'var(--neon-cyan)' },
                { label: 'P&L REAL', value: `$${cpTotalPnl >= 0 ? '+' : ''}${cpTotalPnl.toFixed(2)}`, color: cpTotalPnl >= 0 ? 'var(--neon-green)' : 'var(--red)' },
                { label: 'UNREALIZED', value: `$${cpUnrealized >= 0 ? '+' : ''}${cpUnrealized.toFixed(2)}`, color: cpUnrealized >= 0 ? 'var(--neon-green)' : 'var(--red)' },
                { label: 'WIN RATE', value: `${cpWR}%`, color: cpWR >= 50 ? 'var(--neon-green)' : 'var(--muted)' },
                { label: 'WALLETS', value: `${activeWallets.length} act / ${discardedWallets.length} disc`, color: 'var(--muted)' },
              ].map(s => (
                <div key={s.label} style={{ padding: '6px 8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '8px', color: 'var(--muted)', letterSpacing: '0.05em' }}>{s.label}</div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: s.color }}>{s.value}</div>
                </div>
              ))}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0', maxHeight: '280px', overflowY: 'auto' }}>
              {/* Left: Open copy positions */}
              <div style={{ borderRight: '1px solid var(--border)' }}>
                <div style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', fontSize: '9px', color: 'var(--muted)', letterSpacing: '0.06em' }}>
                  POSICIONES COPY ({cpPositions.length})
                </div>
                {cpPositions.length === 0 ? (
                  <div style={{ padding: '12px', color: 'var(--muted)', fontSize: '11px', textAlign: 'center' }}>Sin posiciones copy abiertas</div>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '10px' }}>
                    <thead>
                      <tr style={{ color: 'var(--muted)', fontSize: '8px' }}>
                        {['MERCADO', 'DIR', 'ENTRY', 'ACTUAL', 'P&L', 'FROM'].map(h => (
                          <th key={h} style={{ padding: '3px 4px', textAlign: h === 'MERCADO' ? 'left' : 'right', fontWeight: 400, borderBottom: '1px solid var(--border)' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {cpPositions.map((p: any, i: number) => (
                        <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle, #1a1a2e)' }}>
                          <td style={{ padding: '3px 4px', maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.market}>{p.market}</td>
                          <td style={{ padding: '3px 4px', textAlign: 'right', color: p.direction === 'YES' ? 'var(--neon-green)' : 'var(--neon-orange)', fontWeight: 600 }}>{p.direction}</td>
                          <td style={{ padding: '3px 4px', textAlign: 'right' }}>{((p.entry_price ?? 0) * 100).toFixed(0)}c</td>
                          <td style={{ padding: '3px 4px', textAlign: 'right' }}>{((p.current_price ?? 0) * 100).toFixed(0)}c</td>
                          <td style={{ padding: '3px 4px', textAlign: 'right', color: (p.unrealized_pnl ?? 0) >= 0 ? 'var(--neon-green)' : 'var(--red)', fontWeight: 600 }}>
                            ${(p.unrealized_pnl ?? 0) >= 0 ? '+' : ''}{(p.unrealized_pnl ?? 0).toFixed(1)}
                          </td>
                          <td style={{ padding: '3px 4px', textAlign: 'right', color: 'var(--muted)', fontSize: '8px' }}>{p.source_name || '?'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {/* Closed copy trades */}
                {cpClosed.length > 0 && (
                  <>
                    <div style={{ padding: '4px 8px', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)', fontSize: '9px', color: 'var(--muted)', letterSpacing: '0.06em' }}>
                      CERRADAS ({(cp.closed || []).length})
                    </div>
                    {cpClosed.slice(0, 5).map((p: any, i: number) => (
                      <div key={i} style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, #1a1a2e)', display: 'flex', gap: '4px', alignItems: 'center', fontSize: '9px' }}>
                        <span style={{ color: (p.realized_pnl ?? 0) >= 0 ? 'var(--neon-green)' : 'var(--red)', fontWeight: 600, minWidth: '40px' }}>
                          ${(p.realized_pnl ?? 0) >= 0 ? '+' : ''}{(p.realized_pnl ?? 0).toFixed(1)}
                        </span>
                        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--muted)' }}>{p.market}</span>
                        <span style={{ fontSize: '8px', padding: '1px 3px', borderRadius: '2px', background: p.close_reason === 'TAKE_PROFIT' ? '#00e67622' : '#ff445522', color: p.close_reason === 'TAKE_PROFIT' ? '#00e676' : '#ff4455' }}>
                          {p.close_reason === 'TAKE_PROFIT' ? 'TP' : 'SL'}
                        </span>
                      </div>
                    ))}
                  </>
                )}
              </div>

              {/* Right: Per-wallet PnL tracker */}
              <div>
                <div style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', fontSize: '9px', color: 'var(--muted)', letterSpacing: '0.06em' }}>
                  PnL POR WALLET
                </div>
                {Object.keys(walletPnl).length === 0 ? (
                  <div style={{ padding: '12px', color: 'var(--muted)', fontSize: '11px', textAlign: 'center' }}>Sin datos de PnL por wallet</div>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '10px' }}>
                    <thead>
                      <tr style={{ color: 'var(--muted)', fontSize: '8px' }}>
                        {['WALLET', 'PnL', 'TRADES', 'STATUS'].map(h => (
                          <th key={h} style={{ padding: '3px 4px', textAlign: h === 'WALLET' ? 'left' : 'right', fontWeight: 400, borderBottom: '1px solid var(--border)' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(walletPnl)
                        .sort(([, a]: any, [, b]: any) => (b.pnl ?? 0) - (a.pnl ?? 0))
                        .slice(0, 15)
                        .map(([addr, wp]: [string, any]) => {
                          const walletInfo = (trackedWallets || []).find((w: any) => w.address === addr);
                          const name = walletInfo?.name || `${addr.slice(0, 6)}...`;
                          const isDiscarded = walletInfo?.discarded;
                          return (
                            <tr key={addr} style={{ borderBottom: '1px solid var(--border-subtle, #1a1a2e)', opacity: isDiscarded ? 0.4 : 1 }}>
                              <td style={{ padding: '3px 4px', fontSize: '9px' }} title={addr}>{name}</td>
                              <td style={{ padding: '3px 4px', textAlign: 'right', color: (wp.pnl ?? 0) >= 0 ? 'var(--neon-green)' : 'var(--red)', fontWeight: 600 }}>
                                ${(wp.pnl ?? 0) >= 0 ? '+' : ''}{(wp.pnl ?? 0).toFixed(1)}
                              </td>
                              <td style={{ padding: '3px 4px', textAlign: 'right', color: 'var(--muted)' }}>{wp.trades ?? 0}</td>
                              <td style={{ padding: '3px 4px', textAlign: 'right' }}>
                                <span style={{
                                  fontSize: '7px', padding: '1px 3px', borderRadius: '2px', fontWeight: 600,
                                  background: isDiscarded ? '#ff445522' : (wp.pnl ?? 0) >= 0 ? '#00e67622' : '#ffab0022',
                                  color: isDiscarded ? '#ff4455' : (wp.pnl ?? 0) >= 0 ? '#00e676' : '#ffab00',
                                }}>
                                  {isDiscarded ? 'DISC' : (wp.pnl ?? 0) >= 0 ? 'ACTIVE' : 'WARN'}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                )}

                {/* Discarded wallets count */}
                {discardedWallets.length > 0 && (
                  <div style={{ padding: '4px 8px', borderTop: '1px solid var(--border)', fontSize: '9px', color: '#ff4455' }}>
                    {discardedWallets.length} wallets descartadas por bajo rendimiento
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}


function MarketPanel(props: {
  fundingData: Record<string, { h8_pct: number; annual_pct: number }>;
  stressData: Array<{ coin: string; score: number; annual_funding_pct: number; direction: string; signals: string[] }>;
  liquidationData: Array<{ coin: string; side: string; usd_size: number; px?: string; sz?: string; time_ms?: number; tid?: number; leverage?: number; liq_px?: string; entry_px?: string; margin_used?: string; _new?: boolean }>;
  whaleData: { longs: any[]; shorts: any[] };
}) {
  const { fundingData, stressData, liquidationData } = props;

  const fundingColor = (annual: number) => {
    if (annual > 100) return '#ff4455';
    if (annual > 50) return '#ff8c00';
    if (annual > 20) return '#00e676';
    if (annual < -50) return '#448aff';
    if (annual < -20) return '#00e5ff';
    return '#8888aa';
  };

  const scoreColor = (score: number) =>
    score >= 70 ? '#ff4455' : score >= 50 ? '#ff8c00' : score >= 30 ? '#ffab00' : '#8888aa';

  const scoreBarGradient = (score: number) =>
    score >= 70 ? 'linear-gradient(90deg, #ff4455, #ff1744)' :
    score >= 50 ? 'linear-gradient(90deg, #ff8c00, #ff6d00)' :
    score >= 30 ? 'linear-gradient(90deg, #ffab00, #ff8f00)' :
    'linear-gradient(90deg, #3a3a5c, #4a4a6c)';

  const liqSizeColor = (usd: number) =>
    usd >= 1_000_000 ? '#ff1744' : usd >= 100_000 ? '#ff4455' : usd >= 10_000 ? '#ff8c00' : usd >= 1_000 ? '#ffab00' : '#b0b0cc';

  const formatLiqSize = (usd: number) =>
    usd >= 1_000_000 ? `$${(usd / 1_000_000).toFixed(2)}M` : usd >= 1_000 ? `$${(usd / 1_000).toFixed(1)}K` : `$${usd.toFixed(0)}`;

  const formatLiqTime = (ms?: number) => {
    if (!ms) return '';
    const d = new Date(ms);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const sortedFunding = Object.entries(fundingData)
    .sort(([, a], [, b]) => Math.abs(b.annual_pct) - Math.abs(a.annual_pct));

  // Split liquidations by coin
  const btcLiqs = liquidationData.filter(l => l.coin === 'BTC');
  const ethLiqs = liquidationData.filter(l => l.coin === 'ETH');
  const btcLongTotal = btcLiqs.filter(l => l.side === 'LONG').reduce((s, l) => s + l.usd_size, 0);
  const btcShortTotal = btcLiqs.filter(l => l.side === 'SHORT').reduce((s, l) => s + l.usd_size, 0);
  const ethLongTotal = ethLiqs.filter(l => l.side === 'LONG').reduce((s, l) => s + l.usd_size, 0);
  const ethShortTotal = ethLiqs.filter(l => l.side === 'SHORT').reduce((s, l) => s + l.usd_size, 0);

  const sectionStyle: React.CSSProperties = {
    background: '#0a0a14', border: '1px solid #1a1a2e', borderRadius: '8px', overflow: 'hidden',
    display: 'flex', flexDirection: 'column', minHeight: 0,
  };
  const titleStyle: React.CSSProperties = {
    padding: '8px 14px', borderBottom: '1px solid #1a1a2e', fontSize: '11px',
    letterSpacing: '0.1em', color: '#6a6a8a', fontWeight: 600, flexShrink: 0,
  };
  const emptyStyle: React.CSSProperties = {
    padding: '24px', textAlign: 'center', color: '#4a4a6a', fontSize: '12px',
  };
  const scrollStyle: React.CSSProperties = { overflowY: 'auto', flex: 1, minHeight: 0 };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px', padding: '12px', height: '100%', boxSizing: 'border-box', minHeight: 0 }}>

      {/* Column 1: Stress Index — full height */}
      <div style={sectionStyle}>
        <div style={titleStyle}>STRESS INDEX — ALL ASSETS</div>
        {stressData.length === 0 ? (
          <div style={emptyStyle}>Esperando datos...</div>
        ) : (
          <div style={scrollStyle}>
            {stressData.map(item => (
              <div key={item.coin} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '4px 12px', borderBottom: '1px solid #0e0e1a' }}>
                <span style={{ width: '38px', fontSize: '11px', fontWeight: 600, color: '#e0e0f0' }}>{item.coin}</span>
                <div style={{ flex: 1, height: '5px', background: '#12121e', borderRadius: '3px', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${item.score}%`, background: scoreBarGradient(item.score), borderRadius: '3px', transition: 'width 0.5s' }} />
                </div>
                <span style={{ width: '24px', fontSize: '10px', fontWeight: 700, color: scoreColor(item.score), textAlign: 'right' }}>{item.score}</span>
                <span style={{ width: '48px', fontSize: '10px', color: fundingColor(item.annual_funding_pct), textAlign: 'right' }}>
                  {item.annual_funding_pct > 0 ? '+' : ''}{item.annual_funding_pct.toFixed(0)}%
                </span>
                {(item.direction.includes('SQUEEZE') || item.direction.includes('CAPITULATION')) && (
                  <span style={{ fontSize: '8px', padding: '1px 4px', borderRadius: '3px', fontWeight: 700,
                    background: item.direction.includes('SQUEEZE') ? '#ff445522' : '#00e67622',
                    color: item.direction.includes('SQUEEZE') ? '#ff4455' : '#00e676' }}>
                    {item.direction.includes('SQUEEZE') ? 'SQZ' : 'CAP'}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Column 2: Funding Rates — full height */}
      <div style={sectionStyle}>
        <div style={{ ...titleStyle, display: 'flex', justifyContent: 'space-between' }}>
          <span>FUNDING RATES — ALL ASSETS</span>
          <span style={{ fontSize: '9px', color: '#6a6a8a', letterSpacing: '0', fontWeight: 400 }}>{sortedFunding.length} perps</span>
        </div>
        {sortedFunding.length === 0 ? (
          <div style={emptyStyle}>Esperando datos...</div>
        ) : (
          <div style={scrollStyle}>
            {sortedFunding.map(([coin, data]) => (
              <div key={coin} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '4px 12px', borderBottom: '1px solid #0e0e1a' }}>
                <span style={{ width: '38px', fontSize: '11px', fontWeight: 600, color: '#e0e0f0' }}>{coin}</span>
                <div style={{ flex: 1, height: '4px', background: '#12121e', borderRadius: '2px', overflow: 'hidden', position: 'relative' }}>
                  <div style={{
                    position: 'absolute', height: '100%', borderRadius: '2px',
                    left: data.annual_pct >= 0 ? '50%' : `${50 + Math.max(data.annual_pct / 4, -50)}%`,
                    width: `${Math.min(Math.abs(data.annual_pct) / 4, 50)}%`,
                    background: fundingColor(data.annual_pct),
                  }} />
                </div>
                <span style={{ width: '56px', fontSize: '10px', color: fundingColor(data.annual_pct), textAlign: 'right', fontFamily: 'monospace' }}>
                  {data.h8_pct > 0 ? '+' : ''}{data.h8_pct.toFixed(4)}%
                </span>
                <span style={{ width: '48px', fontSize: '10px', color: fundingColor(data.annual_pct), textAlign: 'right', fontWeight: 600 }}>
                  {data.annual_pct > 0 ? '+' : ''}{data.annual_pct.toFixed(0)}%/y
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Column 3: Liquidation Tracker BTC/ETH — full height */}
      <div style={sectionStyle}>
        <div style={{ ...titleStyle, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>PERP LIQUIDATIONS — x10+ LEVERAGE</span>
          <span style={{ fontSize: '9px', color: '#00e676', fontWeight: 700, letterSpacing: '0', animation: 'pulse 1.5s infinite' }}>● LIVE</span>
        </div>

        {/* Summary bars */}
        <div style={{ padding: '8px 12px', borderBottom: '1px solid #1a1a2e', flexShrink: 0 }}>
          {/* BTC summary */}
          <div style={{ marginBottom: '6px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
              <span style={{ fontSize: '11px', fontWeight: 700, color: '#f7931a' }}>BTC</span>
              <span style={{ fontSize: '10px', color: '#6a6a8a' }}>{btcLiqs.length} liqs</span>
            </div>
            <div style={{ display: 'flex', gap: '2px', height: '6px' }}>
              <div style={{ flex: btcLongTotal || 1, background: 'linear-gradient(90deg, #00e67680, #00e676)', borderRadius: '3px 0 0 3px', transition: 'flex 0.5s' }} />
              <div style={{ flex: btcShortTotal || 1, background: 'linear-gradient(90deg, #ff4455, #ff445580)', borderRadius: '0 3px 3px 0', transition: 'flex 0.5s' }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '2px' }}>
              <span style={{ fontSize: '9px', color: '#00e676' }}>LONG {formatLiqSize(btcLongTotal)}</span>
              <span style={{ fontSize: '9px', color: '#ff4455' }}>SHORT {formatLiqSize(btcShortTotal)}</span>
            </div>
          </div>
          {/* ETH summary */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
              <span style={{ fontSize: '11px', fontWeight: 700, color: '#627eea' }}>ETH</span>
              <span style={{ fontSize: '10px', color: '#6a6a8a' }}>{ethLiqs.length} liqs</span>
            </div>
            <div style={{ display: 'flex', gap: '2px', height: '6px' }}>
              <div style={{ flex: ethLongTotal || 1, background: 'linear-gradient(90deg, #00e67680, #00e676)', borderRadius: '3px 0 0 3px', transition: 'flex 0.5s' }} />
              <div style={{ flex: ethShortTotal || 1, background: 'linear-gradient(90deg, #ff4455, #ff445580)', borderRadius: '0 3px 3px 0', transition: 'flex 0.5s' }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '2px' }}>
              <span style={{ fontSize: '9px', color: '#00e676' }}>LONG {formatLiqSize(ethLongTotal)}</span>
              <span style={{ fontSize: '9px', color: '#ff4455' }}>SHORT {formatLiqSize(ethShortTotal)}</span>
            </div>
          </div>
        </div>

        {/* Live feed */}
        {(() => { const btcEthLiqs = liquidationData.filter(l => l.coin === 'BTC' || l.coin === 'ETH'); return btcEthLiqs.length === 0 ? (
          <div style={emptyStyle}>Esperando liquidaciones BTC/ETH...</div>
        ) : (
          <div style={scrollStyle}>
            {btcEthLiqs.slice(0, 30).map((liq, i) => (
              <div key={`${liq.coin}-${(liq as any).tid || liq.time_ms || i}`} style={{
                display: 'flex', alignItems: 'center', gap: '6px', padding: '5px 12px',
                borderBottom: '1px solid #0e0e1a',
                background: (liq as any)._new ? (liq.side === 'LONG' ? '#00e67615' : '#ff445515') : 'transparent',
                animation: (liq as any)._new ? 'liq-flash 1.5s ease-out' : 'none',
              }}>
                <span style={{ fontSize: '9px', color: '#4a4a6a', fontFamily: 'monospace', width: '52px', flexShrink: 0 }}>
                  {formatLiqTime(liq.time_ms)}
                </span>
                <span style={{
                  fontSize: '9px', fontWeight: 700, padding: '1px 5px', borderRadius: '3px', width: '36px', textAlign: 'center', flexShrink: 0,
                  background: liq.side === 'LONG' ? '#00e67620' : '#ff445520',
                  color: liq.side === 'LONG' ? '#00e676' : '#ff4455',
                }}>{liq.side}</span>
                <span style={{ fontSize: '11px', fontWeight: 700, color: liq.coin === 'BTC' ? '#f7931a' : '#627eea', width: '28px', flexShrink: 0 }}>
                  {liq.coin}
                </span>
                {liq.leverage && (
                  <span style={{
                    fontSize: '9px', fontWeight: 700, padding: '1px 4px', borderRadius: '3px', flexShrink: 0,
                    background: liq.leverage >= 25 ? '#ff445525' : liq.leverage >= 15 ? '#ff8c0020' : '#ffab0020',
                    color: liq.leverage >= 25 ? '#ff4455' : liq.leverage >= 15 ? '#ff8c00' : '#ffab00',
                  }}>x{Math.round(liq.leverage)}</span>
                )}
                <span style={{ fontSize: '10px', color: '#8888aa', fontFamily: 'monospace', flex: 1, textAlign: 'right' }}>
                  @{liq.px ? Number(liq.px).toLocaleString('en-US', { maximumFractionDigits: liq.coin === 'BTC' ? 0 : 2 }) : '—'}
                </span>
                <span style={{
                  fontSize: '11px', fontWeight: 700, fontFamily: 'monospace', textAlign: 'right', width: '68px', flexShrink: 0,
                  color: liqSizeColor(liq.usd_size),
                }}>
                  {formatLiqSize(liq.usd_size)}
                </span>
                {liq.usd_size >= 500_000 && (
                  <span style={{ fontSize: '10px' }}>🔥</span>
                )}
              </div>
            ))}
          </div>
        ); })()}
      </div>

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
    // xterm.open() + internal _innerRefresh crash if the container is not truly
    // visible (display:none ancestor, 0 dimensions, or not yet painted by browser).
    // We check offsetParent (null when hidden) + dimensions, and defer via double-rAF.
    let openPoll: ReturnType<typeof setInterval> | null = null;
    const isVisible = (el: HTMLElement) => el.offsetParent !== null && el.clientWidth > 0 && el.clientHeight > 0;
    const doOpen = (el: HTMLElement) => {
      // Double rAF ensures the browser has actually painted the element
      requestAnimationFrame(() => requestAnimationFrame(() => {
        try {
          xterm.open(el);
          fitAddonRef.current?.fit();
        } catch {}
        xterm.focus();
      }));
    };
    const el = xtermRef.current;
    if (el && isVisible(el)) {
      doOpen(el);
    } else {
      openPoll = setInterval(() => {
        const el2 = xtermRef.current;
        if (!el2) { clearInterval(openPoll!); openPoll = null; return; }
        if (isVisible(el2)) {
          clearInterval(openPoll!); openPoll = null;
          doOpen(el2);
        }
      }, 150);
      setTimeout(() => { if (openPoll) { clearInterval(openPoll); openPoll = null; } }, 10_000);
    }

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

    electron?.pty?.create(terminal.id, terminal.agentId, xterm.rows || 24, xterm.cols || 80);

    // Debounced fit helper — used by both window resize and ResizeObserver
    let resizeTimer: ReturnType<typeof setTimeout>;
    const doFit = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        try {
          const el = xtermRef.current;
          if (!el || el.clientWidth === 0 || el.clientHeight === 0) return;
          // Only fit if terminal has been opened (element prop exists after open())
          if (!termInstanceRef.current?.element) return;
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
      if (openPoll) clearInterval(openPoll);
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
