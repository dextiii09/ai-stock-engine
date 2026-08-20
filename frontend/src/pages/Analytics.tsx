import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { BarChart2, Brain, AlertTriangle, Calendar, BookOpen, TrendingUp, TrendingDown, RefreshCw, Shield, Zap, Layers, Cpu, CheckCircle2, Clock, Activity, Target, Flame, ArrowDownRight } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell } from 'recharts';
import { MarketTabs, ALL_MARKET_TABS, useMarket } from '../components/MarketTabs';
import { API_BASE } from '../config';

export const Analytics = () => {
  const [market] = useMarket('US');
  const [report, setReport] = useState<any>(null);
  const [agentWeights, setAgentWeights] = useState<any>({});
  const [journal, setJournal] = useState<any[]>([]);
  const [events, setEvents] = useState<any>({ upcoming_events: [], trading_blackout: false });
  const [strategies, setStrategies] = useState<any>(null);
  const [builderStatus, setBuilderStatus] = useState<any>(null);
  const [attribution, setAttribution] = useState<any>(null);
  const [perfMetrics, setPerfMetrics] = useState<any>(null);

  const fetchAll = async () => {
    try {
      // Route per-market endpoints to the correct market prefix
      const prefix: Record<string, string> = {
        US:     API_BASE,
        INDIA:  `${API_BASE}/indian`,
        STOCKS: `${API_BASE}/stocks`,
        CRYPTO: `${API_BASE}/crypto`,
        FOREX:  `${API_BASE}/forex`,
      };
      const BASE = prefix[market] ?? API_BASE;

      const [reportRes, weightsRes, journalRes, eventsRes, stratRes, builderRes, attributionRes, riskRes] = await Promise.all([
        fetch(`${BASE}/analytics/report`),
        fetch(`${BASE}/analytics/agent-weights`),
        fetch(`${BASE}/analytics/journal`),
        fetch(`${API_BASE}/analytics/events`),   // global — macro events affect all markets
        fetch(`${API_BASE}/strategies/library`),  // global — same strategy set for all
        fetch(`${API_BASE}/strategies/builder`),  // global
        fetch(`${BASE}/analytics/attribution`),
        fetch(`${BASE}/portfolio/risk`),
      ]);

      if (reportRes.ok) setReport(await reportRes.json());
      if (weightsRes.ok) {
        const w = await weightsRes.json();
        setAgentWeights(w.weights || {});
      }
      if (journalRes.ok) {
        const j = await journalRes.json();
        setJournal(j.journal || []);
      }
      if (eventsRes.ok) setEvents(await eventsRes.json());
      if (stratRes.ok) setStrategies(await stratRes.json());
      if (builderRes.ok) setBuilderStatus(await builderRes.json());
      if (attributionRes.ok) setAttribution(await attributionRes.json());
      if (riskRes.ok) {
        const riskData = await riskRes.json();
        setPerfMetrics(riskData.performance || null);
      }
    } catch (e) {
      // Backend offline
    }
  };

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, [market]);

  const agentChartData = Object.entries(agentWeights).map(([name, weight]) => ({
    name: name.replace(' AI', '').replace(' Analyst', '').replace('News & Sentiment', 'Sentiment').replace('Macro Economic', 'Macro'),
    weight: parseFloat((weight as number).toFixed(3)),
    fill: (weight as number) >= 0.5 ? '#00C853' : '#FF3D00',
  }));

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-20">
      {/* Header */}
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-4xl md:text-5xl font-bold tracking-tight mb-2 flex items-center gap-3">
              <Activity className="w-10 h-10 text-theme_blue" /> AI Analytics
            </h1>
            <p className="text-muted-foreground text-lg">Self-Diagnosing AI · Trade Journal · Agent Intelligence</p>
          </div>
          <button onClick={fetchAll} className="flex items-center gap-2 px-4 py-2 bg-card border border-border rounded-xl text-sm font-medium hover:bg-border/50 transition-colors">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        </div>
        <MarketTabs tabs={ALL_MARKET_TABS} />
      </div>

      {/* Event Blackout Banner */}
      {events.trading_blackout && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-theme_red/10 border border-theme_red/40 rounded-2xl p-4 flex items-center gap-4"
        >
          <AlertTriangle className="w-6 h-6 text-theme_red shrink-0" />
          <div>
            <p className="font-bold text-theme_red">Trading Blackout Active</p>
            <p className="text-sm text-muted-foreground">Reason: {events.blackout_reason}. All autonomous trading has been paused.</p>
          </div>
        </motion.div>
      )}

      {/* Daily Report */}
      {report && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {[
            { label: 'Journal Actions', value: report.total_trades, sub: 'All BUY + SELL signals', icon: Zap, color: 'text-theme_blue' },
            { label: 'Closed Trades', value: report.closed_trades_count ?? 0, sub: 'Matches Money Tracker', icon: BarChart2, color: 'text-theme_blue' },
            { label: 'Buy Orders', value: report.buy_count ?? 0, sub: 'Entry signals', icon: TrendingUp, color: 'text-theme_green' },
            { label: 'Sell Orders', value: report.sell_count ?? 0, sub: 'Exit signals', icon: TrendingDown, color: 'text-theme_red' },
            { label: 'Avg Confidence', value: `${report.avg_confidence_pct ?? '—'}${report.avg_confidence_pct != null ? '%' : ''}`, sub: 'AI committee score', icon: Shield, color: 'text-purple-400' },
          ].map((stat, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="bg-card border border-border rounded-2xl p-5 flex items-center gap-4"
            >
              <div className={`w-12 h-12 rounded-xl bg-background border border-border flex items-center justify-center ${stat.color} shrink-0`}>
                <stat.icon className="w-6 h-6" />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium truncate">{stat.label}</p>
                <p className="font-display text-2xl font-bold">{stat.value}</p>
                <p className="text-xs text-muted-foreground/60 mt-0.5">{stat.sub}</p>
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {/* ── Performance Metrics ── */}
      {perfMetrics && (
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="bg-card border border-border rounded-3xl p-6">
          <h2 className="font-display font-bold text-xl mb-1 flex items-center gap-2">
            <Target className="w-5 h-5 text-theme_green" /> Institutional Performance Metrics
          </h2>
          <p className="text-sm text-muted-foreground mb-6">Risk-adjusted returns computed from all closed trades.</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
            {[
              {
                label: 'Sharpe Ratio',
                value: perfMetrics.sharpe_ratio != null ? perfMetrics.sharpe_ratio.toFixed(2) : '—',
                sub: 'Risk-adj return',
                icon: TrendingUp,
                good: (v: any) => v !== null && v > 1,
                color: perfMetrics.sharpe_ratio != null && perfMetrics.sharpe_ratio > 1 ? 'text-theme_green' : perfMetrics.sharpe_ratio != null && perfMetrics.sharpe_ratio > 0 ? 'text-theme_yellow' : 'text-theme_red',
              },
              {
                label: 'Sortino Ratio',
                value: perfMetrics.sortino_ratio != null ? perfMetrics.sortino_ratio.toFixed(2) : '—',
                sub: 'Downside-adj',
                icon: Shield,
                color: perfMetrics.sortino_ratio != null && perfMetrics.sortino_ratio > 1.5 ? 'text-theme_green' : perfMetrics.sortino_ratio != null && perfMetrics.sortino_ratio > 0 ? 'text-theme_yellow' : 'text-theme_red',
              },
              {
                label: 'Calmar Ratio',
                value: perfMetrics.calmar_ratio != null ? perfMetrics.calmar_ratio.toFixed(2) : '—',
                sub: 'Return / DrawDown',
                icon: Flame,
                color: perfMetrics.calmar_ratio != null && perfMetrics.calmar_ratio > 1 ? 'text-theme_green' : perfMetrics.calmar_ratio != null && perfMetrics.calmar_ratio > 0 ? 'text-theme_yellow' : 'text-theme_red',
              },
              {
                label: 'Max Drawdown',
                value: perfMetrics.max_drawdown != null ? `$${Number(perfMetrics.max_drawdown).toLocaleString()}` : '—',
                sub: 'Peak-to-trough',
                icon: ArrowDownRight,
                color: perfMetrics.max_drawdown === 0 ? 'text-theme_green' : 'text-theme_red',
              },
              {
                label: 'VaR 95%',
                value: perfMetrics.var_95 != null ? `$${Number(perfMetrics.var_95).toLocaleString()}` : '—',
                sub: '1-trade max loss',
                icon: AlertTriangle,
                color: 'text-theme_yellow',
              },
              {
                label: 'CVaR 95%',
                value: perfMetrics.cvar_95 != null ? `$${Number(perfMetrics.cvar_95).toLocaleString()}` : '—',
                sub: 'Expected shortfall',
                icon: AlertTriangle,
                color: 'text-theme_red',
              },
            ].map((m, i) => (
              <div key={i} className="bg-background border border-border rounded-2xl p-4 flex flex-col gap-1">
                <div className="flex items-center gap-2 mb-1">
                  <m.icon className={`w-4 h-4 ${m.color}`} />
                  <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">{m.label}</span>
                </div>
                <p className={`font-display text-2xl font-bold ${m.color}`}>{m.value}</p>
                <p className="text-xs text-muted-foreground">{m.sub}</p>
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-4 pt-4 border-t border-border">
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">Profit Factor</p>
              <p className={`font-bold text-lg ${perfMetrics.profit_factor != null && perfMetrics.profit_factor > 1 ? 'text-theme_green' : 'text-theme_red'}`}>
                {perfMetrics.profit_factor != null ? perfMetrics.profit_factor.toFixed(2) : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">Expectancy</p>
              <p className={`font-bold text-lg ${perfMetrics.expectancy >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
                ${perfMetrics.expectancy != null ? perfMetrics.expectancy.toFixed(2) : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">Win Rate</p>
              <p className={`font-bold text-lg ${perfMetrics.win_rate_pct >= 50 ? 'text-theme_green' : 'text-theme_yellow'}`}>
                {perfMetrics.win_rate_pct != null ? `${perfMetrics.win_rate_pct.toFixed(1)}%` : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">Closed Trades</p>
              <p className="font-bold text-lg text-foreground">{perfMetrics.trade_count ?? report?.closed_trades_count ?? 0}</p>
            </div>
          </div>
        </motion.div>
      )}

      <div className="grid lg:grid-cols-2 gap-8">

        {/* Agent Weights (RL Adjusted) */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="bg-card border border-border rounded-3xl p-6">
          <h2 className="font-display font-bold text-xl mb-1 flex items-center gap-2">
            <Brain className="w-5 h-5 text-theme_blue" /> Committee Agent Weights
          </h2>
          <p className="text-sm text-muted-foreground mb-6">Live RL-adjusted influence scores. Higher = more trusted by Master AI.</p>
          {agentChartData.length === 0 ? (
            <div className="text-center text-muted-foreground py-12 text-sm">Start the engine to initialize RL weights.</div>
          ) : (
            <>
              <div className="h-48 mb-6">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={agentChartData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                    <XAxis dataKey="name" tick={{ fill: '#888', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#888', fontSize: 11 }} domain={[0, 1]} />
                    <Tooltip
                      contentStyle={{ background: '#111', border: '1px solid #333', borderRadius: '8px' }}
                      labelStyle={{ color: '#fff' }}
                    />
                    <Bar dataKey="weight" radius={[6, 6, 0, 0]}>
                      {agentChartData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="space-y-3">
                {Object.entries(agentWeights).map(([name, weight]) => (
                  <div key={name} className="flex items-center justify-between">
                    <span className="text-sm font-medium text-muted-foreground">{name}</span>
                    <div className="flex items-center gap-3">
                      <div className="w-32 bg-background rounded-full h-1.5 overflow-hidden border border-border">
                        <div
                          className={`h-1.5 rounded-full ${(weight as number) >= 0.5 ? 'bg-theme_green' : 'bg-theme_red'}`}
                          style={{ width: `${Math.min((weight as number) * 100, 100)}%` }}
                        />
                      </div>
                      <span className={`text-sm font-bold font-mono w-10 text-right ${(weight as number) >= 0.5 ? 'text-theme_green' : 'text-theme_red'}`}>
                        {(weight as number).toFixed(2)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </motion.div>

        {/* Macro Event Calendar */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="bg-card border border-border rounded-3xl p-6">
          <h2 className="font-display font-bold text-xl mb-1 flex items-center gap-2">
            <Calendar className="w-5 h-5 text-purple-400" /> {
              market === 'INDIA'  ? 'Indian Macro Radar (RBI/CPI)'    :
              market === 'FOREX'  ? 'Forex Macro Radar (FOMC/NFP/DXY)' :
              'Macro Event Radar (FOMC/NFP)'}
          </h2>
          <p className="text-sm text-muted-foreground mb-6">{
            market === 'INDIA'  ? 'RBI MPC, India CPI, and earnings events the Indian engine tracks.' :
            market === 'FOREX'  ? 'FOMC, NFP, CPI events the forex engine monitors for session gates.' :
            'Events the engine is actively tracking for trading blackouts.'
          }</p>
          {events.upcoming_events.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-4 text-muted-foreground">
              <Calendar className="w-12 h-12 opacity-30" />
              <p className="text-sm">No high-risk events detected today.</p>
              <p className="text-xs opacity-60">Trading is currently clear to proceed.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {events.upcoming_events.map((ev: any, i: number) => (
                <div key={i} className={`flex items-center justify-between p-4 rounded-2xl border ${ev.blackout ? 'border-theme_red/30 bg-theme_red/5' : 'border-theme_yellow/30 bg-theme_yellow/5'}`}>
                  <div className="flex items-center gap-3">
                    <AlertTriangle className={`w-5 h-5 ${ev.blackout ? 'text-theme_red' : 'text-theme_yellow'}`} />
                    <div>
                      <p className="font-bold text-sm">{ev.name}</p>
                      <p className="text-xs text-muted-foreground capitalize">{ev.type}</p>
                    </div>
                  </div>
                  <span className={`text-xs font-bold px-2 py-1 rounded-md ${ev.risk === 'HIGH' ? 'bg-theme_red/20 text-theme_red' : 'bg-theme_yellow/20 text-theme_yellow'}`}>
                    {ev.risk}
                  </span>
                </div>
              ))}
            </div>
          )}
        </motion.div>
      </div>

      {/* Causal Attribution & Insights */}
      {attribution && attribution.status === "success" && (
        <div className="grid lg:grid-cols-2 gap-8">
          {/* Agent PnL Attribution */}
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="bg-card border border-border rounded-3xl p-6">
            <h2 className="font-display font-bold text-xl mb-1 flex items-center gap-2">
              <Brain className="w-5 h-5 text-theme_green" /> Agent PnL Attribution
            </h2>
            <p className="text-sm text-muted-foreground mb-6">
              Cumulative profit/loss impact from each agent's vote direction multiplied by trade return ({attribution.total_analyzed_trades} closed trades analyzed).
            </p>
            {Object.keys(attribution.agent_attribution).length === 0 ? (
              <div className="text-center text-muted-foreground py-12 text-sm">
                No attribution data available. Let closed trades accumulate.
              </div>
            ) : (
              <>
                <div className="h-48 mb-6">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={Object.entries(attribution.agent_attribution).map(([name, data]: [string, any]) => ({
                        name: name.replace(' AI', '').replace(' Analyst', '').replace('News & Sentiment', 'Sentiment').replace('Macro Economic', 'Macro'),
                        attribution: data.total_attribution,
                        fill: data.total_attribution >= 0 ? '#00C853' : '#FF3D00'
                      }))}
                      margin={{ top: 10, right: 0, left: -20, bottom: 0 }}
                    >
                      <XAxis dataKey="name" tick={{ fill: '#888', fontSize: 11 }} />
                      <YAxis tick={{ fill: '#888', fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{ background: '#111', border: '1px solid #333', borderRadius: '8px' }}
                        labelStyle={{ color: '#fff' }}
                      />
                      <Bar dataKey="attribution" radius={[6, 6, 0, 0]}>
                        {Object.entries(attribution.agent_attribution).map(([, data]: [string, any], index) => (
                          <Cell key={`cell-${index}`} fill={data.total_attribution >= 0 ? '#00C853' : '#FF3D00'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="space-y-3">
                  {Object.entries(attribution.agent_attribution).map(([name, data]: [string, any]) => (
                    <div key={name} className="flex items-center justify-between">
                      <div>
                        <span className="text-sm font-medium text-muted-foreground">{name}</span>
                        <span className="text-xs text-muted-foreground/60 ml-2">({data.num_trades} trades)</span>
                      </div>
                      <span className={`text-sm font-bold font-mono ${data.total_attribution >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
                        {data.total_attribution >= 0 ? '+' : ''}{data.total_attribution.toFixed(2)}%
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </motion.div>

          {/* Feature-PnL Correlations */}
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="bg-card border border-border rounded-3xl p-6">
            <h2 className="font-display font-bold text-xl mb-1 flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-theme_blue" /> Feature-PnL Correlations
            </h2>
            <p className="text-sm text-muted-foreground mb-6">
              Pearson correlation between technical/macro features at entry and trade profit/loss.
            </p>
            {Object.keys(attribution.feature_correlation).length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 gap-4 text-muted-foreground">
                <AlertTriangle className="w-12 h-12 opacity-30 text-theme_yellow" />
                <p className="text-sm text-center">At least 2 closed trades with entry feature data are required to compute correlations.</p>
                <p className="text-xs opacity-60">Currently waiting for more trade cycles to run.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {Object.entries(attribution.feature_correlation).map(([feat, corr]: [string, any]) => {
                  const val = corr as number;
                  const isPositive = val >= 0;
                  const absVal = Math.abs(val);
                  
                  let strength = "Negligible";
                  let colorClass = "text-muted-foreground";
                  let bgClass = "bg-muted/10 border-border/30";
                  let Icon = Zap;
                  
                  if (absVal >= 0.7) {
                    strength = "Strong";
                    colorClass = isPositive ? "text-theme_green" : "text-theme_red";
                    bgClass = isPositive ? "bg-theme_green/10 border-theme_green/30" : "bg-theme_red/10 border-theme_red/30";
                    Icon = isPositive ? TrendingUp : TrendingDown;
                  } else if (absVal >= 0.3) {
                    strength = "Moderate";
                    colorClass = isPositive ? "text-theme_green/80" : "text-theme_red/80";
                    bgClass = isPositive ? "bg-theme_green/5 border-theme_green/20" : "bg-theme_red/5 border-theme_red/20";
                    Icon = isPositive ? TrendingUp : TrendingDown;
                  } else if (absVal > 0) {
                    strength = "Weak";
                    colorClass = isPositive ? "text-theme_green/60" : "text-theme_red/60";
                    bgClass = isPositive ? "bg-theme_green/5 border-theme_green/10" : "bg-theme_red/5 border-theme_red/10";
                  }
                  
                  const readableName = feat
                    .replace(/_/g, ' ')
                    .replace(/\b\w/g, c => c.toUpperCase())
                    .replace('Rsi 14', 'RSI (14)')
                    .replace('Macd Hist', 'MACD Histogram')
                    .replace('Atr 14', 'ATR (14)')
                    .replace('Vwap', 'VWAP')
                    .replace('Vix Level', 'VIX Volatility Index')
                    .replace('Dxy Value', 'DXY US Dollar Index')
                    .replace('Real Yield 10y Trend', '10Y Real Yield Trend');

                  return (
                    <div key={feat} className={`p-4 rounded-2xl border ${bgClass} flex items-center justify-between`}>
                      <div className="flex items-center gap-3">
                        <Icon className={`w-5 h-5 shrink-0 ${colorClass}`} />
                        <div>
                          <p className="font-bold text-sm">{readableName}</p>
                          <p className="text-xs text-muted-foreground">
                            {strength} {isPositive ? "Positive" : "Negative"} relationship with trade PnL
                          </p>
                        </div>
                      </div>
                      <div className="text-right">
                        <span className={`text-sm font-mono font-bold ${colorClass}`}>
                          {val >= 0 ? '+' : ''}{val.toFixed(3)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </motion.div>
        </div>
      )}

      {/* AI Trade Journal */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="bg-card border border-border rounded-3xl p-6">
        <h2 className="font-display font-bold text-xl mb-1 flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-theme_green" /> AI Trade Journal
        </h2>
        <p className="text-sm text-muted-foreground mb-6">Every trade the AI Committee executed — with full Explainable AI reasoning.</p>
        {journal.length === 0 ? (
          <div className="text-center text-muted-foreground py-12 text-sm">
            No trades in journal yet. Start the engine and let the AI Committee execute its first trade.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground uppercase tracking-wider">
                  <th className="pb-3 pr-4 font-medium">Time</th>
                  <th className="pb-3 pr-4 font-medium">Symbol</th>
                  <th className="pb-3 pr-4 font-medium">Action</th>
                  <th className="pb-3 pr-4 font-medium">Price</th>
                  <th className="pb-3 pr-4 font-medium">Confidence</th>
                  <th className="pb-3 pr-4 font-medium">Attribution</th>
                  <th className="pb-3 font-medium">AI Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {[...journal].filter((e: any) => e.type === 'TRADE').reverse().slice(0, 20).map((entry: any, i: number) => (
                  <tr key={i} className="hover:bg-muted/20 transition-colors">
                    <td className="py-3 pr-4 font-mono text-xs text-muted-foreground">
                      {new Date(entry.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </td>
                    <td className="py-3 pr-4 font-bold">{entry.symbol}</td>
                    <td className="py-3 pr-4">
                      <span className={`text-xs font-bold px-2 py-1 rounded-md ${entry.action === 'BUY' ? 'bg-theme_green/20 text-theme_green' : 'bg-theme_red/20 text-theme_red'}`}>
                        {entry.action}
                      </span>
                    </td>
                    <td className="py-3 pr-4 font-mono font-medium">${entry.execution_price.toFixed(2)}</td>
                    <td className="py-3 pr-4 font-bold text-theme_blue">{(entry.ai_confidence * 100).toFixed(1)}%</td>
                    <td className="py-3 pr-4 flex gap-1 flex-wrap min-w-[150px] max-w-[200px]">
                      {entry.committee_breakdown?.filter((b:any) => b.contribution != null && b.contribution !== 0).map((b: any, j: number) => (
                        <span key={j} title={`${b.agent}: ${b.contribution > 0 ? '+' : ''}${b.contribution.toFixed(2)}`} className={`text-[10px] px-1 py-0.5 rounded font-mono ${b.contribution > 0 ? 'bg-theme_green/20 text-theme_green' : 'bg-theme_red/20 text-theme_red'}`}>
                          {b.agent.substring(0, 3)}: {b.contribution > 0 ? '+' : ''}{b.contribution.toFixed(2)}
                        </span>
                      ))}
                    </td>
                    <td className="py-3 text-sm text-muted-foreground max-w-xs truncate" title={entry.ai_reason}>{entry.ai_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </motion.div>

      {/* Daily Insights */}
      {report && report.insights && report.insights.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="bg-card border border-border rounded-3xl p-6">
          <h2 className="font-display font-bold text-xl mb-4 flex items-center gap-2">
            <Brain className="w-5 h-5 text-purple-400" /> Self-Diagnosis Insights
          </h2>
          <div className="space-y-3">
            {report.insights.map((insight: string, i: number) => (
              <div key={i} className="flex items-start gap-3 p-4 bg-background border border-border rounded-2xl">
                <span className="text-lg">{insight.charAt(0)}</span>
                <p className="text-sm text-muted-foreground">{insight.slice(2)}</p>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {/* Strategy Library */}
      {strategies && (
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }} className="bg-card border border-border rounded-3xl p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="font-display font-bold text-xl flex items-center gap-2">
              <Layers className="w-5 h-5 text-theme_blue" /> Dynamic Strategy Library
            </h2>
            <div className="flex items-center gap-3">
              {strategies.active_regime && (
                <span className="text-xs bg-theme_blue/20 text-theme_blue border border-theme_blue/30 px-3 py-1 rounded-full font-medium">
                  Regime: {strategies.active_regime}
                </span>
              )}
              <span className="text-xs bg-background border border-border px-3 py-1 rounded-full text-muted-foreground">
                {strategies.total} strategies
              </span>
            </div>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {Object.entries(strategies.by_regime).map(([regime, strats]: [string, any]) =>
              (strats as any[]).map((s: any) => {
                const isActive = strategies.active_strategy?.id === s.id;
                return (
                  <div key={s.id} className={`p-4 rounded-2xl border transition-all ${isActive ? 'border-theme_blue/50 bg-theme_blue/5 shadow-theme_blue/10 shadow-lg' : 'border-border bg-background'}`}>
                    <div className="flex items-start justify-between mb-2">
                      <p className={`text-sm font-bold ${isActive ? 'text-theme_blue' : 'text-foreground'}`}>{s.name}</p>
                      {isActive && <span className="text-xs bg-theme_blue text-white px-2 py-0.5 rounded-full font-bold">ACTIVE</span>}
                    </div>
                    <div className="flex gap-2 flex-wrap">
                      <span className="text-xs bg-muted text-muted-foreground px-2 py-0.5 rounded-md">{s.timeframe}</span>
                      <span className="text-xs bg-muted text-muted-foreground px-2 py-0.5 rounded-md">{regime}</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </motion.div>
      )}

      {/* Autonomous Strategy Builder */}
      {builderStatus && (
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }} className="bg-card border border-border rounded-3xl p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="font-display font-bold text-xl flex items-center gap-2">
              <Cpu className="w-5 h-5 text-purple-400" /> Autonomous Strategy Builder
            </h2>
            <span className="text-xs text-muted-foreground">{builderStatus.total_generated} generated · {builderStatus.discarded_count} discarded</span>
          </div>
          <div className="grid lg:grid-cols-2 gap-6">
            {/* Pipeline */}
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium mb-3">In Pipeline</p>
              <div className="space-y-2">
                {builderStatus.pipeline.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">Pipeline empty. Starting engine will generate candidates.</p>
                ) : builderStatus.pipeline.map((s: any) => (
                  <div key={s.id} className="flex items-center gap-3 p-3 bg-background border border-border rounded-xl">
                    <Clock className="w-4 h-4 text-theme_yellow shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{s.name}</p>
                      <p className="text-xs text-muted-foreground">{s.stage} · SR: {s.sharpe_ratio} · WR: {s.win_rate}%</p>
                    </div>
                    <div className="w-24 bg-muted rounded-full h-1.5 overflow-hidden">
                      <div className="h-1.5 bg-theme_yellow rounded-full" style={{ width: `${((['Discovering','Backtesting','Walk-Forward','Paper Trading','Evaluating'].indexOf(s.stage)+1)/5)*100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
            {/* Deployed */}
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium mb-3">Recently Deployed</p>
              <div className="space-y-2">
                {builderStatus.deployed.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">No strategies deployed yet. Builder is running…</p>
                ) : builderStatus.deployed.map((s: any) => (
                  <div key={s.id} className="flex items-center gap-3 p-3 bg-theme_green/5 border border-theme_green/30 rounded-xl">
                    <CheckCircle2 className="w-4 h-4 text-theme_green shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{s.name}</p>
                      <p className="text-xs text-theme_green">SR: {s.sharpe_ratio} · WR: {s.win_rate}%</p>
                    </div>
                    <span className="text-xs font-bold text-theme_green bg-theme_green/20 px-2 py-0.5 rounded-md">LIVE</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </div>

  );
};
