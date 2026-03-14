import * as React from 'react';
import Head from 'next/head';

const { useState, useEffect, useCallback, useRef } = React;

// ── Agent definitions (from RBI's sidebar.py + moon-dev agents) ──
const AGENTS = [
  { id: 'claude-main', name: 'Claude (Principal)', model: 'sonnet', description: 'Orquestador principal' },
  { id: 'trading-agent', name: 'Trading Agent', model: 'sonnet', description: 'Decisiones de compra/venta' },
  { id: 'risk-agent', name: 'Risk Agent', model: 'sonnet', description: 'Métricas avanzadas y VaR' },
  { id: 'strategy-agent', name: 'Strategy Agent', model: 'sonnet', description: 'Ciclo de vida de estrategias' },
  { id: 'rbi-agent', name: 'RBI Agent', model: 'sonnet', description: 'Investigación de estrategias' },
  { id: 'solana-agent', name: 'Solana Agent', model: 'sonnet', description: 'Selector meme coins' },
  { id: 'sniper-agent', name: 'Sniper Agent', model: 'sonnet', description: 'Sniping tokens nuevos' },
  { id: 'sentiment-agent', name: 'Sentiment Agent', model: 'sonnet', description: 'Social sentiment' },
  { id: 'copy-agent', name: 'Copy Agent', model: 'sonnet', description: 'Mirror trading' },
  { id: 'whale-agent', name: 'Whale Agent', model: 'sonnet', description: 'Rastreo de ballenas' },
  { id: 'swarm-agent', name: 'Swarm Agent', model: 'opus', description: 'Orquestador multi-agente' },
  { id: 'regime-interpreter', name: 'Regime Interpreter', model: 'sonnet', description: 'Detección de régimen HMM' },
  { id: 'backtest-engineer', name: 'Backtest Engineer', model: 'sonnet', description: 'Ejecuta y valida backtests' },
  { id: 'tiktok-agent', name: 'TikTok Agent', model: 'haiku', description: 'Arbitraje social' },
];

// ── Startup terminals: same as RBI's _auto_open_startup_terminals ──
const STARTUP_AGENTS = [
  { agentId: 'claude-main', delay: 400 },
  { agentId: 'claude-main', delay: 750 },
];

// ── Terminal type ──
interface TerminalState {
  id: string;
  agentId: string;
  agentName: string;
  model: string;
}

// ── xterm.js dynamic import (only works in browser) ──
let Terminal: any = null;
let FitAddon: any = null;
let WebLinksAddon: any = null;

if (typeof window !== 'undefined') {
  // Dynamic imports for xterm.js
  import('xterm').then(mod => { Terminal = mod.Terminal; });
  import('xterm-addon-fit').then(mod => { FitAddon = mod.FitAddon; });
  import('xterm-addon-web-links').then(mod => { WebLinksAddon = mod.WebLinksAddon; });
}

export default function HomePage() {
  const [terminals, setTerminals] = useState<TerminalState[]>([]);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [isGridView, setIsGridView] = useState(true);
  const [showPicker, setShowPicker] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [clock, setClock] = useState('');
  const startupDoneRef = useRef(false);

  // Clock
  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setClock(now.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    };
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, []);

  // ── Auto-open 2 Claude terminals on startup (same as RBI showEvent) ──
  useEffect(() => {
    if (startupDoneRef.current) return;
    startupDoneRef.current = true;

    STARTUP_AGENTS.forEach(({ agentId, delay }) => {
      setTimeout(() => addTerminal(agentId), delay);
    });
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 't') { e.preventDefault(); setShowPicker(true); }
      if (e.ctrlKey && e.key === 'g') { e.preventDefault(); setIsGridView(v => !v); }
      if (e.ctrlKey && e.key === 'w') { e.preventDefault(); closeActiveTerminal(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [terminals, activeTab]);

  // ── Actions ──
  const addTerminal = useCallback((agentId: string) => {
    const agent = AGENTS.find(a => a.id === agentId) || AGENTS[0];
    const id = `term-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const newTerm: TerminalState = {
      id,
      agentId: agent.id,
      agentName: agent.name,
      model: agent.model,
    };
    setTerminals(prev => [...prev, newTerm]);
    setActiveTab(id);
    setShowPicker(false);
    setSearchQuery('');
  }, []);

  const closeTerminal = useCallback((id: string) => {
    // Kill the PTY process
    (window as any).electron?.pty?.kill(id);

    setTerminals(prev => {
      const next = prev.filter(t => t.id !== id);
      if (activeTab === id) {
        setActiveTab(next.length > 0 ? next[next.length - 1].id : null);
      }
      return next;
    });
  }, [activeTab]);

  const closeActiveTerminal = useCallback(() => {
    if (activeTab) closeTerminal(activeTab);
  }, [activeTab, closeTerminal]);

  // ── Filter agents ──
  const filteredAgents = AGENTS.filter(a =>
    !searchQuery || a.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    a.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // ── Grid class ──
  const gridClass = `terminal-grid grid-${Math.min(terminals.length, 6)}`;

  return (
    <>
      <Head>
        <title>OpenGravity</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css" />
      </Head>

      {/* Gradient accent bar */}
      <div className="accent-bar" />

      {/* Top Navigation Bar */}
      <nav className="top-nav">
        <span className="logo">OPENGRAVITY</span>
        <div className="separator" />

        <button className="nav-tab active">TERMINALS</button>

        <div className="nav-spacer" />

        <button className="btn-new-terminal" onClick={() => setShowPicker(true)}>
          +  Terminal
        </button>

        {terminals.length > 0 && (
          <div className="view-toggle">
            <button
              className={!isGridView ? 'active' : ''}
              onClick={() => setIsGridView(false)}
              title="Vista tabs (Ctrl+G)"
            >⊞</button>
            <button
              className={isGridView ? 'active' : ''}
              onClick={() => setIsGridView(true)}
              title="Vista grid (Ctrl+G)"
            >⊟</button>
          </div>
        )}

        <span className="clock">{clock}</span>

        {/* Window controls (for frameless window) */}
        <div className="window-controls">
          <button onClick={() => (window as any).electron?.minimize()}>─</button>
          <button onClick={() => (window as any).electron?.maximize()}>□</button>
          <button className="close" onClick={() => (window as any).electron?.close()}>✕</button>
        </div>
      </nav>

      {/* Main Area */}
      <div className="terminal-area">
        {terminals.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">⌨</div>
            <div className="empty-text">No hay terminales abiertas</div>
            <div className="empty-hint">Ctrl+T para abrir una nueva terminal</div>
            <button className="empty-btn" onClick={() => setShowPicker(true)}>
              +  Nueva Terminal
            </button>
          </div>
        ) : isGridView ? (
          /* Grid View */
          <div className={gridClass}>
            {terminals.map(term => (
              <XTermPanel key={term.id} terminal={term} onClose={() => closeTerminal(term.id)} />
            ))}
          </div>
        ) : (
          /* Tab View */
          <div className="terminal-tabs">
            <div className="tab-bar">
              {terminals.map(term => (
                <div
                  key={term.id}
                  className={`tab-item ${activeTab === term.id ? 'active' : ''}`}
                  onClick={() => setActiveTab(term.id)}
                >
                  <span>{term.agentName}</span>
                  <button className="tab-close" onClick={(e) => { e.stopPropagation(); closeTerminal(term.id); }}>✕</button>
                </div>
              ))}
            </div>
            <div className="tab-content">
              {terminals.filter(t => t.id === activeTab).map(term => (
                <XTermPanel key={term.id} terminal={term} onClose={() => closeTerminal(term.id)} showHeader={false} />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Agent Picker Modal */}
      {showPicker && (
        <div className="modal-overlay" onClick={() => setShowPicker(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">Selecciona un agente</div>
              <input
                className="modal-search"
                placeholder="🔍  Buscar agente..."
                autoFocus
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Escape') setShowPicker(false);
                  if (e.key === 'Enter' && filteredAgents.length > 0) addTerminal(filteredAgents[0].id);
                }}
              />
            </div>
            <div className="modal-body">
              {filteredAgents.map(agent => (
                <div key={agent.id} className="agent-option" onClick={() => addTerminal(agent.id)}>
                  <div className="agent-indicator" />
                  <span className="agent-name">{agent.name}</span>
                  <span className={`agent-badge ${agent.model}`}>[{agent.model}]</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ── XTerm Panel Component (real terminal with xterm.js + node-pty) ──
const XTermPanel: React.FC<{
  terminal: TerminalState;
  onClose: () => void;
  showHeader?: boolean;
}> = ({ terminal, onClose, showHeader = true }) => {
  const termRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<any>(null);
  const fitAddonRef = useRef<any>(null);

  useEffect(() => {
    if (!termRef.current || !Terminal) return;

    // Create xterm.js instance (same theme as RBI's TERMINAL_HTML)
    const xterm = new Terminal({
      cursorBlink: true,
      cursorStyle: 'bar',
      cursorWidth: 2,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace",
      fontWeight: '400',
      fontWeightBold: '600',
      lineHeight: 1.25,
      scrollback: 3000,
      allowProposedApi: true,
      theme: {
        background: '#000000',
        foreground: '#e6edf3',
        cursor: '#58a6ff',
        cursorAccent: '#000000',
        selectionBackground: 'rgba(88,166,255,0.25)',
        black: '#333333',
        red: '#ff7b72',
        green: '#3fb950',
        yellow: '#d29922',
        blue: '#58a6ff',
        magenta: '#bc8cff',
        cyan: '#39d2c0',
        white: '#e6edf3',
        brightBlack: '#6e7681',
        brightRed: '#ffa198',
        brightGreen: '#56d364',
        brightYellow: '#e3b341',
        brightBlue: '#79c0ff',
        brightMagenta: '#d2a8ff',
        brightCyan: '#56d4dd',
        brightWhite: '#f0f6fc',
      },
    });

    const fitAddon = new FitAddon();
    xterm.loadAddon(fitAddon);

    if (WebLinksAddon) {
      xterm.loadAddon(new WebLinksAddon());
    }

    xterm.open(termRef.current);
    fitAddon.fit();
    xtermRef.current = xterm;
    fitAddonRef.current = fitAddon;

    // ── Connect to node-pty via IPC ──
    const electron = (window as any).electron;

    // Forward xterm input to PTY
    xterm.onData((data: string) => {
      electron?.pty?.write(terminal.id, data);
    });

    // Forward xterm resize to PTY
    xterm.onResize(({ cols, rows }: { cols: number; rows: number }) => {
      electron?.pty?.resize(terminal.id, cols, rows);
    });

    // Receive PTY output
    electron?.pty?.onData((termId: string, data: string) => {
      if (termId === terminal.id && xtermRef.current) {
        xtermRef.current.write(data);
      }
    });

    // Create PTY session
    electron?.pty?.create(terminal.id, terminal.agentId, xterm.rows, xterm.cols);

    // Auto-fit on container resize
    const observer = new ResizeObserver(() => {
      try { fitAddon.fit(); } catch {}
    });
    observer.observe(termRef.current);

    return () => {
      observer.disconnect();
      xterm.dispose();
    };
  }, [terminal.id, terminal.agentId]);

  return (
    <div className="terminal-panel">
      {showHeader && (
        <div className="terminal-header">
          <div className="terminal-dot" />
          <span className="terminal-title">{terminal.agentName}</span>
          <span className="terminal-model">[{terminal.model}]</span>
          <button className="terminal-close-btn" onClick={onClose}>✕</button>
        </div>
      )}
      <div
        ref={termRef}
        style={{ flex: 1, overflow: 'hidden', background: '#000000' }}
      />
    </div>
  );
}
