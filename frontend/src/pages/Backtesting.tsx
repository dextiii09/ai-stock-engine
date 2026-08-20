import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  History, Play, Activity, AlertCircle, BarChart3,
  Target, Sparkles, Square, TrendingUp, TrendingDown,
  Shuffle, Zap
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine
} from 'recharts';

import { MarketTabs, ALL_MARKET_TABS, useMarket } from '../components/MarketTabs';
import { API_BASE } from '../config';

const API_BASE_US     = API_BASE;
const API_BASE_INDIA  = `${API_BASE}/indian`;
const API_BASE_STOCKS = `${API_BASE}/stocks`;
const API_BASE_CRYPTO = `${API_BASE}/crypto`;
const API_BASE_FOREX  = `${API_BASE}/forex`;

const ALL_STRATEGIES = [
  'AI Committee',
  'RSI Mean Reversion',
  'MACD Crossover',
  'Bollinger Breakout',
  'EMA Trend Follow',
  'Supertrend',
  'VWAP Reversion',
  'ADX Trend Strength',
];

// ─── Monthly Heatmap ────────────────────────────────────────────────────────

const MonthlyHeatmap = ({ monthly }: { monthly: Record<string, number>; currency?: string }) => {
  if (!monthly || Object.keys(monthly).length === 0) return null;
  const entries = Object.entries(monthly).sort(([a], [b]) => a.localeCompare(b));
  return (
    <div className="bg-card border border-border rounded-3xl p-6">
      <h3 className="font-display font-bold text-lg mb-4 flex items-center gap-2">
        <BarChart3 className="w-5 h-5 text-theme_blue" /> Monthly Returns
      </h3>
      <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 gap-2">
        {entries.map(([month, ret]) => (
          <div
            key={month}
            title={`${month}: ${ret > 0 ? '+' : ''}${ret}%`}
            className={`rounded-lg p-2 text-center text-xs font-bold transition-all hover:scale-105 cursor-default ${
              ret > 3   ? 'bg-emerald-500/30 text-emerald-400' :
              ret > 1   ? 'bg-emerald-500/15 text-emerald-400' :
              ret > 0   ? 'bg-emerald-500/10 text-emerald-500' :
              ret > -1  ? 'bg-red-500/10 text-red-400'  :
              ret > -3  ? 'bg-red-500/20 text-red-400'  :
                          'bg-red-500/30 text-red-500'
            }`}
          >
            <div className="text-[10px] text-muted-foreground mb-0.5">{month.slice(2)}</div>
            {ret > 0 ? '+' : ''}{ret.toFixed(1)}%
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── Monte Carlo Card ────────────────────────────────────────────────────────

const MonteCarloCard = ({ mc, currency }: { mc: any; currency: string }) => {
  if (!mc) return null;
  const sym = currency === 'INR' ? '₹' : '$';
  const fmt = (v: number) => `${sym}${v.toLocaleString()}`;
  return (
    <div className="bg-card border border-border rounded-3xl p-6">
      <h3 className="font-display font-bold text-lg mb-1 flex items-center gap-2">
        <Shuffle className="w-5 h-5 text-purple-400" /> Monte Carlo
      </h3>
      <p className="text-xs text-muted-foreground mb-4">200 bootstrapped paths · 95% confidence band</p>
      <div className="space-y-3">
        <div className="flex justify-between items-center bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
          <span className="text-sm font-bold text-red-400">Worst 5%</span>
          <span className="font-mono font-bold text-red-400">{fmt(mc.p5)}</span>
        </div>
        <div className="flex justify-between items-center bg-theme_blue/10 border border-theme_blue/20 rounded-xl px-4 py-3">
          <span className="text-sm font-bold text-theme_blue">Median</span>
          <span className="font-mono font-bold text-theme_blue">{fmt(mc.p50)}</span>
        </div>
        <div className="flex justify-between items-center bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-4 py-3">
          <span className="text-sm font-bold text-emerald-400">Best 5%</span>
          <span className="font-mono font-bold text-emerald-400">{fmt(mc.p95)}</span>
        </div>
        <div className="flex justify-between items-center bg-background border border-border rounded-xl px-4 py-3">
          <span className="text-sm font-bold text-muted-foreground">Expected</span>
          <span className="font-mono font-bold">{fmt(mc.expected_final)}</span>
        </div>
      </div>
    </div>
  );
};

// ─── Benchmark Card ──────────────────────────────────────────────────────────

const BenchmarkCard = ({ benchmark, strategyReturn, strategySharpe }: {
  benchmark: any; strategyReturn: number; strategySharpe: number;
}) => {
  if (!benchmark || benchmark.error) return null;
  const alpha = strategyReturn - benchmark.return_pct;
  return (
    <div className="bg-card border border-border rounded-3xl p-6">
      <h3 className="font-display font-bold text-lg mb-1 flex items-center gap-2">
        <TrendingUp className="w-5 h-5 text-theme_yellow" /> vs Benchmark
      </h3>
      <p className="text-xs text-muted-foreground mb-4">Buy-and-hold {benchmark.symbol}</p>
      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-sm text-muted-foreground">Strategy Return</span>
          <span className={`font-bold ${strategyReturn >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
            {strategyReturn > 0 ? '+' : ''}{strategyReturn.toFixed(2)}%
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-sm text-muted-foreground">{benchmark.symbol} Return</span>
          <span className={`font-bold ${benchmark.return_pct >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
            {benchmark.return_pct > 0 ? '+' : ''}{benchmark.return_pct.toFixed(2)}%
          </span>
        </div>
        <div className="flex justify-between items-center border-t border-border pt-3 mt-3">
          <span className="text-sm font-bold">Alpha</span>
          <span className={`font-bold text-lg ${alpha >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
            {alpha >= 0 ? '+' : ''}{alpha.toFixed(2)}%
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-muted-foreground">Strategy Sharpe</span>
          <span className="font-mono text-sm font-bold">{strategySharpe.toFixed(3)}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-muted-foreground">Benchmark Sharpe</span>
          <span className="font-mono text-sm font-bold">{benchmark.sharpe?.toFixed(3) ?? 'N/A'}</span>
        </div>
      </div>
    </div>
  );
};

// ─── Main Component ──────────────────────────────────────────────────────────

export const Backtesting = () => {
  const [market] = useMarket('US');
  const defaultSymbol  =
    market === 'INDIA'  ? 'NIFTYBEES.NS' :
    market === 'STOCKS' ? 'AAPL'         :
    market === 'CRYPTO' ? 'BTC-USD'      :
    market === 'FOREX'  ? 'EURUSD=X'     :
    'MNQ=F';
  const defaultCapital =
    market === 'INDIA'  ? 100_000 :
    market === 'STOCKS' ? 100_000 :
    market === 'CRYPTO' ? 10_000  :
    market === 'FOREX'  ? 50_000  :
    10_000;
  const [symbol,   setSymbol]   = useState(() => localStorage.getItem(`bt_symbol_${market}`)   || defaultSymbol);
  const [strategy, setStrategy] = useState(() => localStorage.getItem(`bt_strategy_${market}`) || 'AI Committee');
  const [period,   setPeriod]   = useState(() => localStorage.getItem(`bt_period_${market}`)   || '1y');
  const [capital,  setCapital]  = useState(() => Number(localStorage.getItem(`bt_capital_${market}`)) || defaultCapital);

  const [isRunning,    setIsRunning]    = useState(false);
  const [isContinuous, setIsContinuous] = useState(() => {
    const s = localStorage.getItem(`bt_continuous_${market}`);
    return s === null ? true : s === 'true';
  });
  const isContinuousRef = useRef(isContinuous);
  const hasAutoStarted  = useRef(false);
  const [rlTrainCount, setRlTrainCount] = useState(() =>
    Number(sessionStorage.getItem(`bt_train_${market}`)) || 0
  );

  const [results, setResults] = useState<any>(() => {
    const s = localStorage.getItem(`bt_results_${market}`);
    return s ? JSON.parse(s) : null;
  });
  const [error, setError] = useState('');

  const currSym = results?.currency === 'INR' || market === 'INDIA' ? '₹' : '$';

  // Persist state
  useEffect(() => {
    localStorage.setItem(`bt_symbol_${market}`,     symbol);
    localStorage.setItem(`bt_strategy_${market}`,   strategy);
    localStorage.setItem(`bt_period_${market}`,     period);
    localStorage.setItem(`bt_capital_${market}`,    capital.toString());
    localStorage.setItem(`bt_continuous_${market}`, isContinuous.toString());
    if (results) localStorage.setItem(`bt_results_${market}`, JSON.stringify(results));
  }, [symbol, strategy, period, capital, isContinuous, results, market]);

  useEffect(() => {
    sessionStorage.setItem(`bt_train_${market}`, rlTrainCount.toString());
  }, [rlTrainCount, market]);

  // Auto-start continuous on mount
  useEffect(() => {
    if (isContinuousRef.current && !hasAutoStarted.current && !isRunning) {
      hasAutoStarted.current = true;
      const t = setTimeout(() => { if (isContinuousRef.current) runAutoMode(); }, 1000);
      return () => clearTimeout(t);
    }
  }, []);

  // Re-trigger after run completes
  useEffect(() => {
    if (!isRunning && isContinuous && hasAutoStarted.current) {
      const t = setTimeout(() => { if (isContinuousRef.current) runAutoMode(); }, 3000);
      return () => clearTimeout(t);
    }
  }, [isRunning, isContinuous]);

  const toggleContinuous = () => {
    isContinuousRef.current = !isContinuousRef.current;
    setIsContinuous(isContinuousRef.current);
    if (isContinuousRef.current && !isRunning) runAutoMode();
  };

  const runAutoMode = () => {
    const syms =
      market === 'INDIA'  ? ['NIFTYBEES.NS', 'BANKBEES.NS', 'GOLDBEES.NS', 'RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFCBANK.NS', 'ICICIBANK.NS'] :
      market === 'STOCKS' ? ['AAPL', 'NVDA', 'MSFT', 'TSLA', 'AMZN', 'META'] :
      market === 'CRYPTO' ? ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD'] :
      market === 'FOREX'  ? ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'AUDUSD=X'] :
      ['MNQ=F', 'MGC=F', 'NQ=F', 'GC=F'];
    // Always use 2y period for regime diversity; always AI Committee so RL actually trains
    const sym = syms[Math.floor(Math.random() * syms.length)];
    const str = 'AI Committee';
    const per = '2y';
    setSymbol(sym); setStrategy(str); setPeriod(per);
    setRlTrainCount(c => c + 1);
    runSimulation(sym, str, per);
  };

  const runSimulation = async (overSym?: string, overStr?: string, overPer?: string) => {
    setIsRunning(true);
    setError('');
    try {
      const base =
        market === 'INDIA'  ? API_BASE_INDIA  :
        market === 'STOCKS' ? API_BASE_STOCKS :
        market === 'CRYPTO' ? API_BASE_CRYPTO :
        market === 'FOREX'  ? API_BASE_FOREX  :
        API_BASE_US;
      const res  = await fetch(`${base}/backtest/run`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol:          (overSym || symbol).toUpperCase(),
          strategy:        overStr  || strategy,
          period:          overPer  || period,
          initial_capital: Number(capital),
        }),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || 'Backtest failed');
      }
      const data = await res.json();
      setResults(data);

      // Push backtest-trained RL state into the live bot (fire-and-forget)
      // Only for AI Committee — other strategies don't train RL
      const usedStrategy = overStr || strategy;
      if (data.rl_state && usedStrategy === 'AI Committee') {
        const mergeUrl =
          market === 'INDIA'  ? `${API_BASE_INDIA}/analytics/rl/merge_backtest`  :
          market === 'STOCKS' ? `${API_BASE_STOCKS}/analytics/rl/merge_backtest` :
          market === 'CRYPTO' ? `${API_BASE_CRYPTO}/analytics/rl/merge_backtest` :
          market === 'FOREX'  ? `${API_BASE_FOREX}/analytics/rl/merge_backtest`  :
          `${API_BASE_US}/analytics/rl/merge_backtest`;
        fetch(mergeUrl, {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rl_state: data.rl_state }),
        }).catch(() => {/* silent — merge is best-effort */});
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setIsRunning(false);
    }
  };

  const MetricCard = ({
    label, value, sub, positive
  }: { label: string; value: string; sub?: string; positive?: boolean }) => (
    <div>
      <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{label}</div>
      <div className={`font-bold text-xl ${
        positive === true ? 'text-theme_green' :
        positive === false ? 'text-theme_red' : ''
      }`}>{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12">

      {/* Header */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <h1 className="font-display text-4xl md:text-5xl font-bold tracking-tight mb-2 flex items-center gap-3">
              <History className="w-10 h-10 text-theme_blue" /> Backtesting
            </h1>
            <p className="text-muted-foreground text-lg">
              Test strategies on real historical OHLCV · Long &amp; Short · Benchmark · Monte Carlo
            </p>
          </div>
          {isContinuous && (
            <div className="flex items-center gap-3 bg-purple-600/10 border border-purple-600/30 rounded-2xl px-5 py-3">
              <span className="relative flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-500 opacity-75" />
                <span className="relative inline-flex rounded-full h-3 w-3 bg-purple-500" />
              </span>
              <div>
                <p className="text-sm font-bold text-purple-400">Auto RL Training Active</p>
                <p className="text-xs text-muted-foreground">{rlTrainCount} sessions this session</p>
              </div>
            </div>
          )}
        </div>
        <MarketTabs tabs={ALL_MARKET_TABS} />
      </div>

      <div className="grid xl:grid-cols-4 gap-8">

        {/* ── Config Panel ── */}
        <div className="xl:col-span-1 space-y-6">
          <div className="bg-card border border-border rounded-3xl p-6 flex flex-col shadow-sm">
            <h3 className="font-display font-bold text-lg mb-6 flex items-center gap-2">
              <Target className="w-5 h-5 text-theme_blue" /> Parameters
            </h3>

            <div className="space-y-5 flex-1">
              {/* Symbol */}
              <div>
                <label className="block text-xs font-bold text-muted-foreground mb-1 uppercase tracking-wider">Symbol</label>
                <input
                  type="text"
                  value={symbol}
                  onChange={e => setSymbol(e.target.value.toUpperCase())}
                  className="w-full bg-background border border-border rounded-xl py-3 px-3 text-sm font-bold focus:outline-none focus:border-theme_blue/50 mb-2"
                  placeholder="e.g. MNQ=F"
                />
                <div className="flex flex-wrap gap-2">
                  {(market === 'INDIA'  ? ['NIFTYBEES.NS', 'BANKBEES.NS', 'GOLDBEES.NS', 'RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFCBANK.NS', 'ICICIBANK.NS'] :
                    market === 'STOCKS' ? ['AAPL', 'NVDA', 'MSFT', 'TSLA', 'AMZN', 'META'] :
                    market === 'CRYPTO' ? ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD'] :
                    market === 'FOREX'  ? ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'AUDUSD=X'] :
                    ['MNQ=F', 'MGC=F', 'NQ=F', 'GC=F']
                  ).map(sym => (
                    <button
                      key={sym}
                      onClick={() => setSymbol(sym)}
                      className={`text-xs px-2 py-1 rounded-md font-bold transition-colors ${
                        symbol === sym
                          ? 'bg-theme_blue text-white'
                          : 'bg-muted text-muted-foreground hover:bg-muted/80'
                      }`}
                    >{sym}</button>
                  ))}
                </div>
              </div>

              {/* Strategy */}
              <div>
                <label className="block text-xs font-bold text-muted-foreground mb-1 uppercase tracking-wider">Strategy</label>
                <select
                  value={strategy}
                  onChange={e => setStrategy(e.target.value)}
                  className="w-full bg-background border border-border rounded-xl py-3 px-3 text-sm focus:outline-none focus:border-theme_blue/50 font-medium"
                >
                  {ALL_STRATEGIES.map(s => <option key={s}>{s}</option>)}
                </select>
                {strategy === 'Supertrend' && (
                  <p className="text-xs text-muted-foreground mt-1.5">ATR-based trend bands — signals on direction flip.</p>
                )}
                {strategy === 'VWAP Reversion' && (
                  <p className="text-xs text-muted-foreground mt-1.5">Buy dips below VWAP; sell rallies above VWAP.</p>
                )}
                {strategy === 'ADX Trend Strength' && (
                  <p className="text-xs text-muted-foreground mt-1.5">Only enters when ADX &gt; 25 confirms DI+/DI− crossover.</p>
                )}
              </div>

              {/* Period */}
              <div>
                <label className="block text-xs font-bold text-muted-foreground mb-1 uppercase tracking-wider">Time Period</label>
                <select
                  value={period}
                  onChange={e => setPeriod(e.target.value)}
                  className="w-full bg-background border border-border rounded-xl py-3 px-3 text-sm focus:outline-none focus:border-theme_blue/50 font-medium"
                >
                  <option value="6mo">6 Months</option>
                  <option value="1y">1 Year</option>
                  <option value="2y">2 Years</option>
                  <option value="5y">5 Years</option>
                  <option value="10y">10 Years</option>
                  <option value="max">Max Available</option>
                </select>
              </div>

              {/* Capital */}
              <div>
                <label className="block text-xs font-bold text-muted-foreground mb-1 uppercase tracking-wider">
                  Initial Capital ({currSym})
                </label>
                <input
                  type="number"
                  value={capital}
                  onChange={e => setCapital(Number(e.target.value))}
                  className="w-full bg-background border border-border rounded-xl py-3 px-3 text-sm font-bold focus:outline-none focus:border-theme_blue/50"
                />
              </div>
            </div>

            <div className="pt-8 flex flex-col gap-3">
              <button
                onClick={() => runSimulation()}
                disabled={isRunning}
                className="w-full bg-theme_blue text-white py-4 rounded-2xl font-bold text-lg hover:bg-theme_blue/90 transition-all active:scale-[0.98] shadow-lg shadow-theme_blue/20 flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {isRunning
                  ? <><Activity className="w-5 h-5 animate-spin" /><span>Simulating…</span></>
                  : <><Play className="w-5 h-5" /><span>Run Simulation</span></>
                }
              </button>
              <button
                onClick={toggleContinuous}
                className={`w-full py-4 rounded-2xl font-bold text-lg transition-all active:scale-[0.98] shadow-lg flex items-center justify-center gap-2 ${
                  isContinuous
                    ? 'bg-theme_red text-white hover:bg-theme_red/90 shadow-theme_red/20'
                    : 'bg-purple-600 text-white hover:bg-purple-700 shadow-purple-600/20'
                }`}
              >
                {isContinuous
                  ? <><Square className="w-5 h-5 fill-current" /><span>Stop Continuous</span></>
                  : <><Sparkles className="w-5 h-5" /><span>Continuous Scan</span></>
                }
              </button>
            </div>
          </div>
        </div>

        {/* ── Right Column ── */}
        <div className="xl:col-span-3 space-y-6">

          {/* Equity Curve */}
          <div className="bg-card border border-border rounded-3xl p-6 flex flex-col relative overflow-hidden min-h-[450px]">
            <h3 className="font-display font-bold text-lg mb-6">Equity Curve</h3>

            <AnimatePresence mode="wait">
              {isRunning && (
                <motion.div
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  className="absolute inset-0 bg-background/80 backdrop-blur-sm z-10 flex flex-col items-center justify-center"
                >
                  <div className="relative w-24 h-24 mb-6">
                    <div className="absolute inset-0 border-4 border-border rounded-full" />
                    <div className="absolute inset-0 border-4 border-theme_blue border-t-transparent rounded-full animate-spin" />
                    <div className="absolute inset-0 flex items-center justify-center">
                      <Activity className="w-8 h-8 text-theme_blue" />
                    </div>
                  </div>
                  <p className="font-mono text-sm text-theme_blue text-center max-w-xs">
                    Fetching Yahoo Finance data · Walk-Forward · Monte Carlo · Benchmark…
                  </p>
                </motion.div>
              )}
            </AnimatePresence>

            {error && (
              <div className="absolute inset-0 bg-background/90 z-10 flex items-center justify-center">
                <div className="text-center p-6 max-w-md bg-red-500/10 border border-red-500/20 rounded-2xl">
                  <AlertCircle className="w-10 h-10 text-red-500 mx-auto mb-4" />
                  <h4 className="text-red-500 font-bold mb-2">Simulation Failed</h4>
                  <p className="text-muted-foreground text-sm">{error}</p>
                </div>
              </div>
            )}

            {!isRunning && !error && results?.equity_curve && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1">
                <ResponsiveContainer width="100%" height="100%" minHeight={300}>
                  <AreaChart data={results.equity_curve}>
                    <defs>
                      <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%"  stopColor="#3B82F6" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#3B82F6" stopOpacity={0}   />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
                    <XAxis dataKey="date" stroke="#666" tick={{ fill: '#666', fontSize: 12 }} tickMargin={10} minTickGap={30} />
                    <YAxis stroke="#666" tick={{ fill: '#666', fontSize: 12 }} domain={['auto', 'auto']} width={75} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#09090B', border: '1px solid #27272A', borderRadius: '12px' }}
                      itemStyle={{ color: '#E4E4E7' }}
                      formatter={(v: any) => [`${currSym}${Number(v).toLocaleString()}`, 'Equity']}
                    />
                    <ReferenceLine y={capital} stroke="#666" strokeDasharray="3 3" />
                    <Area type="monotone" dataKey="equity" stroke="#3B82F6" fill="url(#colorEquity)" strokeWidth={3} />
                  </AreaChart>
                </ResponsiveContainer>
              </motion.div>
            )}

            {!isRunning && !error && !results && (
              <div className="flex-1 flex items-center justify-center text-muted-foreground">
                Configure parameters and run a backtest to see results.
              </div>
            )}

            {/* Core metrics row */}
            {results && (
              <motion.div
                initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                className="grid grid-cols-3 md:grid-cols-6 gap-4 mt-6 pt-6 border-t border-border"
              >
                <MetricCard
                  label="Total Return"
                  value={`${results.total_return_pct > 0 ? '+' : ''}${results.total_return_pct}%`}
                  positive={results.total_return_pct >= 0}
                />
                <MetricCard label="Win Rate"     value={`${results.win_rate_pct}%`} />
                <MetricCard label="Sharpe"        value={String(results.sharpe_ratio)} />
                <MetricCard label="Sortino"       value={String(results.sortino_ratio ?? '—')} />
                <MetricCard label="Max Drawdown"  value={`-${results.max_drawdown_pct}%`} positive={false} />
                <MetricCard label="Calmar"        value={String(results.calmar_ratio)} />
              </motion.div>
            )}
          </div>

          {/* Advanced metrics row */}
          {results && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
              className="grid grid-cols-2 md:grid-cols-4 gap-4"
            >
              {[
                { label: 'VaR 95% (daily)', value: `${results.var_95_pct?.toFixed(3) ?? '—'}%`,   sub: 'Max expected daily loss' },
                { label: 'CVaR 95%',         value: `${results.cvar_95_pct?.toFixed(3) ?? '—'}%`,  sub: 'Avg tail loss beyond VaR' },
                { label: 'Avg Hold',          value: `${results.avg_hold_bars ?? '—'} bars`,         sub: `Max: ${results.max_hold_bars ?? '—'} bars` },
                { label: 'Streaks W/L',       value: `${results.max_win_streak ?? 0}/${results.max_lose_streak ?? 0}`, sub: 'Max consecutive wins/losses' },
              ].map(m => (
                <div key={m.label} className="bg-card border border-border rounded-2xl p-4">
                  <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{m.label}</div>
                  <div className="font-bold text-lg">{m.value}</div>
                  <div className="text-xs text-muted-foreground mt-0.5">{m.sub}</div>
                </div>
              ))}
            </motion.div>
          )}

          {/* Long / Short breakdown */}
          {results && (results.long_trades > 0 || results.short_trades > 0) && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
              className="bg-card border border-border rounded-3xl p-6"
            >
              <h3 className="font-display font-bold text-lg mb-4 flex items-center gap-2">
                <Zap className="w-5 h-5 text-theme_blue" /> Long / Short Breakdown
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4 text-center">
                  <TrendingUp className="w-5 h-5 text-emerald-400 mx-auto mb-1" />
                  <div className="text-2xl font-bold text-emerald-400">{results.long_trades}</div>
                  <div className="text-xs text-muted-foreground">Long trades</div>
                </div>
                <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-center">
                  <TrendingDown className="w-5 h-5 text-red-400 mx-auto mb-1" />
                  <div className="text-2xl font-bold text-red-400">{results.short_trades}</div>
                  <div className="text-xs text-muted-foreground">Short trades</div>
                </div>
                <div className="bg-background border border-border rounded-xl p-4 text-center">
                  <div className="text-2xl font-bold text-theme_green">{results.winning_trades}</div>
                  <div className="text-xs text-muted-foreground">Total winners</div>
                </div>
                <div className="bg-background border border-border rounded-xl p-4 text-center">
                  <div className="text-2xl font-bold text-theme_red">{results.losing_trades}</div>
                  <div className="text-xs text-muted-foreground">Total losers</div>
                </div>
              </div>
            </motion.div>
          )}

          {/* Monthly Heatmap */}
          {results?.monthly_returns && (
            <MonthlyHeatmap monthly={results.monthly_returns} currency={results.currency || 'USD'} />
          )}

          {/* Walk-Forward · Weights · Monte Carlo · Benchmark */}
          {results && (
            <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-6">

              {/* Walk-Forward */}
              <div className="bg-card border border-border rounded-3xl p-6">
                <h3 className="font-display font-bold text-lg mb-1 flex items-center gap-2">
                  <BarChart3 className="w-5 h-5 text-theme_blue" /> Walk-Forward
                </h3>
                <p className="text-xs text-muted-foreground mb-4">60/20/20 Train/Val/Test</p>
                <div className="space-y-3">
                  {[
                    { label: 'Train 60%', key: 'train_60pct',      highlight: false },
                    { label: 'Val 20%',   key: 'validation_20pct', highlight: false },
                    { label: 'Test 20%',  key: 'test_20pct',       highlight: true  },
                  ].map(({ label, key, highlight }) => {
                    const val = results.walk_forward?.[key] ?? 0;
                    return (
                      <div key={key} className={`rounded-xl p-3 flex justify-between items-center ${
                        highlight
                          ? 'bg-theme_blue/10 border border-theme_blue/20'
                          : 'bg-background border border-border'
                      }`}>
                        <span className={`text-sm font-bold ${highlight ? 'text-theme_blue' : 'text-muted-foreground'}`}>{label}</span>
                        <span className={`font-bold ${val >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>{val}%</span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* RL Trained Weights */}
              {results.trained_weights && (
                <div className="bg-card border border-border rounded-3xl p-6">
                  <h3 className="font-display font-bold text-lg mb-1 flex items-center gap-2">
                    <Sparkles className="w-5 h-5 text-theme_blue" /> Trained Weights
                  </h3>
                  <p className="text-xs text-muted-foreground mb-4">RL-adapted agent weights</p>
                  <div className="space-y-2 overflow-y-auto max-h-52">
                    {Object.entries(results.trained_weights).map(([agent, weight]: any) => (
                      <div key={agent} className="bg-background border border-border rounded-xl p-2.5 flex justify-between items-center text-xs">
                        <span className="font-medium text-muted-foreground truncate">{agent}</span>
                        <span className="font-mono font-bold text-theme_blue ml-2">{Number(weight).toFixed(3)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Monte Carlo */}
              {results.monte_carlo && (
                <MonteCarloCard mc={results.monte_carlo} currency={results.currency || 'USD'} />
              )}

              {/* Benchmark */}
              {results.benchmark && !results.benchmark.error && (
                <BenchmarkCard
                  benchmark={results.benchmark}
                  strategyReturn={results.total_return_pct}
                  strategySharpe={results.sharpe_ratio}
                />
              )}
            </div>
          )}

          {/* Trade Log */}
          {results && (
            <div className="bg-card border border-border rounded-3xl p-6 h-[320px] flex flex-col">
              <h3 className="font-display font-bold text-lg mb-4 flex items-center gap-2">
                <History className="w-5 h-5 text-theme_blue" />
                Trade Log ({results.total_trades} total)
              </h3>
              <div className="flex-1 overflow-y-auto no-scrollbar">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-card text-muted-foreground uppercase">
                    <tr>
                      <th className="pb-3 font-bold">Entry</th>
                      <th className="pb-3 font-bold">Exit</th>
                      <th className="pb-3 font-bold">Side</th>
                      <th className="pb-3 font-bold">Entry $</th>
                      <th className="pb-3 font-bold text-right">Bars</th>
                      <th className="pb-3 font-bold text-right">Net PnL</th>
                      <th className="pb-3 font-bold text-right">Return</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {results.trades.map((trade: any, idx: number) => (
                      <tr key={idx} className="hover:bg-background/50 transition-colors">
                        <td className="py-2">{trade.entry_date}</td>
                        <td className="py-2">{trade.exit_date}</td>
                        <td className="py-2">
                          <span className={`font-bold px-2 py-0.5 rounded ${
                            trade.side === 'LONG'
                              ? 'bg-emerald-500/10 text-emerald-400'
                              : 'bg-red-500/10 text-red-400'
                          }`}>{trade.side}</span>
                        </td>
                        <td className="py-2 font-mono">{currSym}{trade.entry_price.toFixed(2)}</td>
                        <td className="py-2 text-right text-muted-foreground">{trade.hold_bars ?? '—'}</td>
                        <td className={`py-2 text-right font-bold ${trade.net_pnl >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
                          {trade.net_pnl >= 0 ? '+' : ''}{currSym}{trade.net_pnl.toFixed(2)}
                        </td>
                        <td className={`py-2 text-right font-bold ${trade.return_pct >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
                          {trade.return_pct >= 0 ? '+' : ''}{trade.return_pct}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {results.trades.length === 0 && (
                  <div className="text-center text-muted-foreground mt-10">No trades executed in this period.</div>
                )}
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
};
