import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot, Play, Square, Activity, RefreshCw, Crosshair,
  Brain, CheckCircle2, Terminal, Zap
} from 'lucide-react';

import { MarketTabs, ALL_MARKET_TABS, useMarket, getApiBase } from '../components/MarketTabs';
import { API_BASE } from '../config';

export const AutoTrader = () => {
  const [market] = useMarket('US');
  const activeApiBase = getApiBase(market, API_BASE);

  // Per-market bot state keys
  const botStateKey  = `botRunning_${market}`;
  const riskModeKey  = `riskMode_${market}`;

  const [isBotRunning, setIsBotRunning] = useState(() => localStorage.getItem(botStateKey) === 'true');
  const [riskMode, setRiskMode] = useState(() => localStorage.getItem(riskModeKey) || 'Normal');
  const [logs, setLogs] = useState<{ id: number; time: string; msg: string; type: 'info' | 'trade' | 'alert' | 'error' }[]>([]);
  const [rlStats, setRlStats] = useState<any>(null);
  const [regime, setRegime] = useState<any>(null);
  const [openPositions, setOpenPositions] = useState(0);
  const [opportunities, setOpportunities] = useState<any[]>([]);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const logIdCounter = useRef(0);
  const lastLogCount = useRef(0);

  const addLog = (msg: string, type: 'info' | 'trade' | 'alert' | 'error' = 'info') => {
    setLogs(prev => {
      const newLog = {
        id: logIdCounter.current++,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        msg,
        type
      };
      return [...prev.slice(-49), newLog];
    });
  };

  // Persist bot state per market
  useEffect(() => {
    localStorage.setItem(botStateKey, isBotRunning.toString());
  }, [isBotRunning, botStateKey]);

  // Persist risk mode per market
  useEffect(() => {
    localStorage.setItem(riskModeKey, riskMode);
  }, [riskMode, riskModeKey]);

  // Reset log count & state when market switches
  useEffect(() => {
    setIsBotRunning(localStorage.getItem(botStateKey) === 'true');
    setRiskMode(localStorage.getItem(riskModeKey) || 'Normal');
    setLogs([]);
    setRlStats(null);
    setRegime(null);
    setOpenPositions(0);
    setOpportunities([]);
    lastLogCount.current = 0;
  }, [market]);

  // Auto-scroll terminal
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  // Combined poll — stats always + logs/opportunities when bot is running (5s cadence)
  useEffect(() => {
    const fetchAll = async () => {
      try {
        const baseRequests: Promise<Response>[] = [
          fetch(`${activeApiBase}/analytics/rl-stats`),
          fetch(`${activeApiBase}/data/regime`),
          fetch(`${activeApiBase}/portfolio/holdings`),
        ];
        const extraRequests: Promise<Response>[] = isBotRunning
          ? [fetch(`${activeApiBase}/bot/logs`), fetch(`${activeApiBase}/opportunities`)]
          : [];
        const [rlRes, regimeRes, holdingsRes, logRes, oppRes] = await Promise.all([
          ...baseRequests, ...extraRequests,
        ]);
        if (rlRes.ok) setRlStats(await rlRes.json());
        if (regimeRes.ok) setRegime(await regimeRes.json());
        if (holdingsRes.ok) {
          const h = await holdingsRes.json();
          setOpenPositions((h.holdings || []).length);
        }
        if (logRes?.ok) {
          const data = await logRes.json();
          const backendLogs = data.logs || [];
          if (backendLogs.length > lastLogCount.current) {
            const newLogs = backendLogs.slice(lastLogCount.current);
            newLogs.forEach((l: any) => {
              let uiType: 'info' | 'trade' | 'alert' | 'error' = 'info';
              if (l.level === 'success') uiType = 'trade';
              if (l.level === 'warning') uiType = 'alert';
              if (l.level === 'error') uiType = 'error';
              addLog(l.message, uiType);
            });
            lastLogCount.current = backendLogs.length;
          }
        }
        if (oppRes?.ok) {
          const oppData = await oppRes.json();
          if (oppData.opportunities) setOpportunities(oppData.opportunities);
        }
      } catch { /* backend offline */ }
    };
    fetchAll();
    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, [isBotRunning, activeApiBase]);

  const toggleBot = async () => {
    try {
      const endpoint = isBotRunning ? 'stop' : 'start';
      addLog(isBotRunning ? 'Sending termination signal...' : `Initializing Autonomous Engine in ${riskMode} Mode...`, 'info');
      const payload = isBotRunning ? undefined : JSON.stringify({ risk_mode: riskMode });
      const res = await fetch(`${activeApiBase}/bot/${endpoint}`, {
        method: 'POST',
        headers: payload ? { 'Content-Type': 'application/json' } : undefined,
        body: payload
      });
      if (res.ok) {
        setIsBotRunning(!isBotRunning);
        addLog(isBotRunning ? 'Engine offline. All active scans paused.' : 'Engine connected to Yahoo Finance. Scanning initiated.', isBotRunning ? 'alert' : 'trade');
        if (!isBotRunning) lastLogCount.current = 0;
      }
    } catch {
      addLog('Network error: backend not reachable on port 8080.', 'error');
    }
  };

  const retrainPct = rlStats?.retrain_progress_pct ?? 0;
  const tradesSinceRetrain = rlStats?.trades_since_last_retrain ?? 0;
  const retrainInterval = rlStats?.retrain_interval ?? 10;
  const winRate = rlStats?.win_rate_pct ?? null;
  const retrainCount = rlStats?.retrain_count ?? 0;
  const totalTrades = rlStats?.total_closed_trades ?? 0;

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12">

      {/* Header */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 bg-card border border-border p-6 rounded-3xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-64 h-64 bg-theme_blue/5 rounded-bl-[100px] -z-10" />
          <div>
            <h1 className="font-display text-4xl font-bold tracking-tight mb-2 flex items-center gap-3">
              <Bot className="w-10 h-10 text-theme_blue" /> Auto Trader
            </h1>
            <p className="text-muted-foreground text-lg">
              Autonomous AI execution engine — all data sourced from Yahoo Finance.
            </p>
          </div>
        <div className="flex gap-4 z-10 items-center">
          <select 
            value={riskMode}
            onChange={(e) => setRiskMode(e.target.value)}
            disabled={isBotRunning}
            className="bg-background border border-border rounded-xl py-4 px-4 text-sm font-bold focus:outline-none focus:border-theme_blue/50 disabled:opacity-50"
          >
            <option value="Safe">Safe Mode</option>
            <option value="Normal">Normal Mode</option>
            <option value="Aggressive">Aggressive</option>
          </select>
          <button
            onClick={toggleBot}
            className={`flex items-center justify-center gap-2 px-8 py-4 rounded-2xl font-bold text-lg transition-all shadow-lg min-w-[200px] ${
              isBotRunning
                ? 'bg-background border-2 border-theme_red text-theme_red hover:bg-theme_red/10'
                : 'bg-theme_blue text-white hover:bg-theme_blue/90 hover:scale-105 shadow-theme_blue/20'
            }`}
          >
            {isBotRunning ? <><Square className="w-6 h-6 fill-current" /> Stop Engine</> : <><Play className="w-6 h-6 fill-current" /> Start Engine</>}
          </button>
          </div>
        </div>
        <MarketTabs tabs={ALL_MARKET_TABS} />
      </div>

      <div className="grid xl:grid-cols-3 gap-8">

        {/* Left: Status + Terminal */}
        <div className="xl:col-span-2 space-y-6 flex flex-col" style={{ minHeight: 600 }}>

          {/* Status Cards */}
          <div className="grid sm:grid-cols-3 gap-4 shrink-0">
            <div className="bg-card border border-border rounded-3xl p-5 relative overflow-hidden flex items-center gap-4">
              <div className={`absolute top-0 left-0 w-1 h-full ${isBotRunning ? 'bg-theme_green animate-pulse' : 'bg-border'}`} />
              <div className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 ${isBotRunning ? 'bg-theme_green/20 text-theme_green' : 'bg-background text-muted-foreground'}`}>
                <Activity className="w-6 h-6" />
              </div>
              <div>
                <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-0.5">Engine</p>
                <p className="text-lg font-bold">{isBotRunning ? 'Active' : 'Offline'}</p>
              </div>
            </div>

            <div className="bg-card border border-border rounded-3xl p-5 flex items-center gap-4">
              <div className="w-12 h-12 rounded-2xl bg-theme_blue/10 text-theme_blue flex items-center justify-center shrink-0">
                <Crosshair className="w-6 h-6" />
              </div>
              <div>
                <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-0.5">Positions</p>
                <p className="text-lg font-bold">{openPositions}</p>
              </div>
            </div>

            <div className="bg-card border border-border rounded-3xl p-5 flex items-center gap-4">
              <div className="w-12 h-12 rounded-2xl bg-purple-500/10 text-purple-400 flex items-center justify-center shrink-0">
                <Zap className="w-6 h-6" />
              </div>
              <div>
                <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-0.5">Regime</p>
                <p className="text-sm font-bold truncate">{regime?.regime ?? 'Scanning...'}</p>
              </div>
            </div>
          </div>

          {/* Terminal Console */}
          <div className="bg-[#0c0c0e] border border-border rounded-3xl flex-1 flex flex-col overflow-hidden relative shadow-inner" style={{ minHeight: 420 }}>
            <div className="absolute top-0 left-0 w-full h-0.5 bg-gradient-to-r from-theme_blue via-purple-500 to-theme_green" />
            <div className="flex items-center justify-between border-b border-[#27272A] p-4 bg-black/40">
              <span className="text-sm font-mono text-muted-foreground flex items-center gap-2">
                <Terminal className="w-4 h-4" /> System_Logs.stdout — Yahoo Finance (real)
              </span>
              <div className="flex items-center gap-2">
                <span className="flex h-2 w-2 relative">
                  {isBotRunning && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-theme_green opacity-75" />}
                  <span className={`relative inline-flex rounded-full h-2 w-2 ${isBotRunning ? 'bg-theme_green' : 'bg-muted-foreground'}`} />
                </span>
                <span className="text-xs font-mono text-muted-foreground">{isBotRunning ? 'LIVE' : 'PAUSED'}</span>
              </div>
            </div>
            <div ref={logContainerRef} className="flex-1 overflow-y-auto p-6 font-mono text-xs space-y-1.5">
              {logs.length === 0 ? (
                <p className="text-muted-foreground/40 italic">Waiting for engine... Start the engine to begin scanning.</p>
              ) : (
                <AnimatePresence initial={false}>
                  {logs.map(log => (
                    <motion.div
                      key={log.id}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      className={`flex gap-3 leading-relaxed ${
                        log.type === 'trade' ? 'text-theme_green font-semibold' :
                        log.type === 'alert' ? 'text-theme_yellow' :
                        log.type === 'error' ? 'text-theme_red' :
                        'text-muted-foreground'
                      }`}
                    >
                      <span className="opacity-40 shrink-0">[{log.time}]</span>
                      <span className="break-all">{log.msg}</span>
                    </motion.div>
                  ))}
                </AnimatePresence>
              )}
            </div>
          </div>
        </div>

        {/* Right Sidebar */}
        <div className="xl:col-span-1 space-y-6">

          {/* ML Retrain Progress — Real data from RL engine */}
          <div className="bg-card border border-border rounded-3xl p-6">
            <h3 className="font-display font-bold text-lg mb-5 flex items-center gap-2">
              <Brain className="w-5 h-5 text-theme_blue" /> ML Retrain Progress
            </h3>

            <div className="space-y-5">
              {/* Progress bar — real */}
              <div>
                <div className="flex justify-between text-sm mb-2">
                  <span className="text-muted-foreground">Progress to next retrain</span>
                  <span className="font-bold tabular-nums">
                    {totalTrades === 0
                      ? 'No trades yet'
                      : `${tradesSinceRetrain} / ${retrainInterval} trades`}
                  </span>
                </div>
                <div className="w-full bg-background rounded-full h-2 overflow-hidden border border-border">
                  <motion.div
                    className="bg-gradient-to-r from-theme_blue to-purple-500 h-2 rounded-full"
                    animate={{ width: `${retrainPct}%` }}
                    transition={{ duration: 0.6 }}
                  />
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {retrainPct.toFixed(0)}% — computed from {totalTrades} real closed trade{totalTrades !== 1 ? 's' : ''}
                </p>
              </div>

              {/* Info box */}
              <div className="p-4 bg-background border border-border rounded-2xl flex items-start gap-3">
                <RefreshCw className="w-5 h-5 text-theme_blue shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-bold mb-1">Continuous Learning</p>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    Agent weights auto-adjust after every closed trade via RL. A full retrain triggers every {retrainInterval} trades.
                  </p>
                </div>
              </div>

              {/* Stats grid — real from backend */}
              <div className="grid grid-cols-2 gap-3">
                <div className="p-4 bg-background border border-border rounded-2xl text-center">
                  <div className="text-xs text-muted-foreground mb-1 uppercase tracking-wider">Win Rate</div>
                  {winRate !== null ? (
                    <div className={`font-bold text-xl ${winRate >= 50 ? 'text-theme_green' : 'text-theme_red'}`}>
                      {winRate}%
                    </div>
                  ) : (
                    <div className="text-xl font-bold text-muted-foreground">—</div>
                  )}
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {totalTrades > 0 ? `${totalTrades} trades` : 'No trades'}
                  </p>
                </div>
                <div className="p-4 bg-background border border-border rounded-2xl text-center">
                  <div className="text-xs text-muted-foreground mb-1 uppercase tracking-wider">Retrains</div>
                  <div className="font-bold text-xl text-theme_blue">{retrainCount}</div>
                  <p className="text-xs text-muted-foreground mt-0.5">auto-triggered</p>
                </div>
              </div>

              {/* Active strategy filters — real from regime + strategy manager */}
              <div className="pt-4 border-t border-border">
                <h4 className="text-sm font-bold mb-3">Active Engine Filters</h4>
                <div className="space-y-2">
                  {[
                    {
                      label: `Regime: ${regime?.regime ?? 'Detecting...'}`,
                      active: !!regime?.regime
                    },
                    {
                      label: regime?.active_strategy
                        ? `Strategy: ${regime.active_strategy.name}`
                        : 'Strategy: Selecting...',
                      active: !!regime?.active_strategy
                    },
                    {
                      label: 'Multi-Timeframe Alignment Check',
                      active: isBotRunning
                    },
                    {
                      label: 'RSI + MACD + VWAP Signal Filter',
                      active: true
                    },
                    {
                      label: 'Event Blackout Engine',
                      active: true
                    }
                  ].map((filter, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <CheckCircle2 className={`w-4 h-4 ${filter.active ? 'text-theme_green' : 'text-muted-foreground opacity-50'}`} />
                      <span className={filter.active ? 'text-foreground' : 'text-muted-foreground'}>{filter.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Live Opportunities Feed */}
          <div className="bg-card border border-border rounded-3xl p-6">
            <h3 className="font-display font-bold text-lg mb-5 flex items-center gap-2">
              <Crosshair className="w-5 h-5 text-theme_green" /> Today's Opportunities
            </h3>
            
            <div className="space-y-3">
              {opportunities.length === 0 ? (
                <p className="text-xs text-muted-foreground italic">Scanning market universe...</p>
              ) : (
                opportunities.slice(0, 5).map((opp, idx) => (
                  <div key={idx} className="p-3 bg-background border border-border rounded-xl flex items-center justify-between">
                    <div>
                      <p className="font-bold text-sm">{opp.symbol}</p>
                      <p className="text-xs text-muted-foreground">Conf: {opp.confidence}%</p>
                    </div>
                    <div className={`px-3 py-1 rounded-lg text-xs font-bold ${
                      opp.signal === 'BUY' ? 'bg-theme_green/20 text-theme_green' : 
                      opp.signal === 'SELL' ? 'bg-theme_red/20 text-theme_red' : 
                      'bg-theme_yellow/20 text-theme_yellow'
                    }`}>
                      {opp.signal}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* AI Coach */}
          <div className="bg-[#0c0c0e] border border-border rounded-3xl p-6 relative overflow-hidden">
             <div className="absolute top-0 right-0 w-32 h-32 bg-theme_blue/5 rounded-bl-[100px] -z-10" />
             <h3 className="font-display font-bold text-lg mb-3 flex items-center gap-2 text-theme_blue">
              <Brain className="w-5 h-5" /> AI Coach Insight
            </h3>
            
            {opportunities.length > 0 ? (
              <div className="space-y-3 relative z-10">
                <p className="text-sm font-semibold">{opportunities[0].symbol} Decision:</p>
                <div className="bg-black/40 p-3 rounded-lg border border-[#27272A]">
                  <p className="text-xs text-muted-foreground italic">Reason:</p>
                  <p className="text-sm">{opportunities[0].reason}</p>
                </div>
                <div className="bg-theme_blue/10 p-3 rounded-lg border border-theme_blue/20">
                  <p className="text-xs text-theme_blue italic font-bold">Recommendation:</p>
                  <p className="text-sm text-theme_blue">{opportunities[0].recommendation}</p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">Waiting for first scan to complete...</p>
            )}
          </div>

        </div>
      </div>
    </div>
  );
};
