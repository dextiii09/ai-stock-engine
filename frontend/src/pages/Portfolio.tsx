import { useState, useMemo, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { TrendingUp, Download, Plus, Settings2, RefreshCw, AlertCircle, ArrowUpRight } from 'lucide-react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, AreaChart, Area, XAxis, YAxis, CartesianGrid } from 'recharts';
import { DepositModal } from '../components/DepositModal';
import { MarketTabs, ALL_MARKET_TABS, useMarket } from '../components/MarketTabs';
import { API_BASE } from '../config';

export const Portfolio = () => {
  const navigate = useNavigate();
  const [market] = useMarket('US');
  const [isDepositOpen, setDepositOpen] = useState(false);
  const [timeframe, setTimeframe] = useState('1M');
  const [liveHoldings, setLiveHoldings] = useState<any[]>([]);
  const [riskData, setRiskData] = useState<any>(null);
  const [backendOnline, setBackendOnline] = useState(false);
  const [historyData, setHistoryData] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>({
    net_liquidation: 0,
    cash: 0,
    unrealized_pnl: 0,
    realized_pnl: 0,
    gross_profit: 0,
    gross_loss: 0,
    win_rate: 0,
    total_trades: 0,
  });

  const CUR = market === 'INDIA' ? '₹' : '$';
  const LOC = market === 'INDIA' ? 'en-IN' : 'en-US';

  useEffect(() => {
    const activeApiBase =
      market === 'INDIA'  ? `${API_BASE}/indian`  :
      market === 'STOCKS' ? `${API_BASE}/stocks`   :
      market === 'CRYPTO' ? `${API_BASE}/crypto`   :
      market === 'FOREX'  ? `${API_BASE}/forex`    :
      API_BASE;

    // Fast poll — holdings, risk, summary (5s)
    const fetchFast = async () => {
      try {
        const [holdRes, riskRes, moneyRes] = await Promise.all([
          fetch(`${activeApiBase}/portfolio/holdings`),
          fetch(`${activeApiBase}/portfolio/risk`),
          fetch(`${activeApiBase}/portfolio/money-tracker`),
        ]);
        if (holdRes.ok) {
          const data = await holdRes.json();
          setLiveHoldings(Array.isArray(data.holdings) ? data.holdings : []);
          setBackendOnline(true);
        }
        if (riskRes.ok) setRiskData(await riskRes.json());
        if (moneyRes.ok) {
          const moneyData = await moneyRes.json();
          setSummary(moneyData.summary || moneyData);
        }
      } catch {
        setBackendOnline(false);
      }
    };

    // Slow poll — history chart (30s, changes rarely)
    const fetchHistory = async () => {
      try {
        const histRes = await fetch(`${activeApiBase}/portfolio/history?timeframe=${timeframe}`);
        if (histRes.ok) {
          const data = await histRes.json();
          setHistoryData(data.history || []);
        }
      } catch { /* silent */ }
    };

    fetchFast();
    fetchHistory();
    const fastInterval = setInterval(fetchFast, 5000);
    const slowInterval = setInterval(fetchHistory, 30000);
    return () => {
      clearInterval(fastInterval);
      clearInterval(slowInterval);
    };
  }, [timeframe, market]);

  const { chartData } = useMemo(() => {
    if (!historyData || historyData.length === 0) return { chartData: [] };
    return { chartData: historyData };
  }, [historyData]);

  const allocationData = useMemo(() => {
    if (!riskData?.position_exposure_pct || Object.keys(riskData.position_exposure_pct).length === 0) {
      return [{ name: 'Cash', value: 100, color: '#3F3F46' }];
    }
    const colors = ['#3B82F6', '#00C853', '#FFD54F', '#a855f7', '#f97316', '#06b6d4'];
    const entries = Object.entries(riskData.position_exposure_pct);
    const cashPct = riskData.cash_pct ?? 0;
    return [
      ...entries.map(([name, pct], i) => ({ name, value: Number(pct), color: colors[i % colors.length] })),
      ...(cashPct > 0 ? [{ name: 'Cash', value: Math.round(cashPct), color: '#3F3F46' }] : [])
    ];
  }, [riskData]);

  const handleExportCSV = () => {
    if (liveHoldings.length === 0) { alert('No active positions to export.'); return; }
    const headers = ['Symbol', 'Shares', 'Entry Price', 'Current Price', 'Value', 'P&L (%)', 'Stop Loss', 'Take Profit'];
    const rows = liveHoldings.map((h: any) => [h.symbol, h.shares, h.entry_price, h.current_price, h.value, h.change, h.stop_loss, h.take_profit]);
    const csv = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const link = document.createElement('a');
    link.setAttribute('href', encodeURI(csv));
    link.setAttribute('download', `portfolio_${market.toLowerCase()}_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const autoTraderPath = '/autotrader?market=' + market;

  return (
    <div className="max-w-6xl mx-auto space-y-8 pb-20">

      {/* Header */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl md:text-5xl font-bold tracking-tight mb-2 flex items-center gap-3">
              <PieChart className="w-10 h-10 text-theme_blue" /> Portfolio
            </h1>
            <p className="text-muted-foreground">
              {backendOnline
                ? <span className="text-theme_green text-sm font-medium">● Live</span>
                : <span className="text-theme_red text-sm font-medium">● Engine offline — start the backend</span>}
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={handleExportCSV} className="bg-card border border-border text-foreground px-4 py-2 rounded-xl text-sm font-medium hover:bg-border/50 transition-colors flex items-center gap-2">
              <Download className="w-4 h-4" /> Export
            </button>
            <button onClick={() => setDepositOpen(true)} className="bg-theme_blue text-white px-4 py-2 rounded-xl text-sm font-medium hover:bg-theme_blue/90 transition-colors flex items-center gap-2 shadow-lg shadow-theme_blue/20">
              <Plus className="w-4 h-4" /> Deposit
            </button>
          </div>
        </div>
        <MarketTabs tabs={ALL_MARKET_TABS} />
      </div>

      {/* Top Cards */}
      <div className="grid lg:grid-cols-3 gap-6">

        {/* Balance Card */}
        <div className={`lg:col-span-2 bg-card border border-border p-6 rounded-3xl relative overflow-hidden`}>
          <div className={`absolute top-0 right-0 w-64 h-64 ${market === 'INDIA' ? 'bg-orange-500/5' : 'bg-theme_blue/5'} rounded-bl-full -z-10 blur-3xl`} />
          <p className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-2">Net Liquidation Value</p>
          <div className="flex items-baseline gap-3 flex-wrap">
            <h2 className="text-4xl sm:text-5xl font-display font-bold tracking-tight">
              {CUR}{Number(summary.current_balance || 0).toLocaleString(LOC)}
            </h2>
            <span className={`${Number(summary.total_pnl) >= 0 ? 'text-theme_green' : 'text-theme_red'} font-bold flex items-center`}>
              {Number(summary.total_pnl) >= 0 ? '+' : ''}{CUR}{Math.abs(Number(summary.total_pnl || 0)).toLocaleString(LOC)} Total PnL
            </span>
          </div>
        </div>

        {/* Auto-Rebalance Card */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
          onClick={() => navigate(autoTraderPath)}
          className="bg-card border border-border rounded-3xl p-6 flex flex-col justify-between group cursor-pointer hover:border-theme_blue/30 transition-colors">
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="w-10 h-10 rounded-full bg-theme_blue/20 text-theme_blue flex items-center justify-center">
                <RefreshCw className="w-5 h-5 group-hover:animate-spin" />
              </div>
              <span className="text-xs font-bold text-theme_blue bg-theme_blue/10 px-2 py-1 rounded-md">AI ACTIVE</span>
            </div>
            <h3 className="font-bold text-lg mb-1">Auto-Rebalance</h3>
            {riskData ? (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Beta: <span className="font-bold text-foreground">{riskData.portfolio_beta ?? '—'}</span></p>
                <p className="text-xs text-muted-foreground">Cash: <span className="font-bold text-foreground">{riskData.cash_pct?.toFixed(1) ?? '—'}%</span></p>
                <p className={`text-xs font-bold ${riskData.overall_risk_level === 'LOW' ? 'text-theme_green' : riskData.overall_risk_level === 'MEDIUM' ? 'text-theme_yellow' : 'text-theme_red'}`}>
                  Risk: {riskData.overall_risk_level ?? '—'}
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Start engine to activate AI risk monitoring.</p>
            )}
          </div>
          <button className="text-sm font-medium text-theme_blue flex items-center gap-1 mt-4 hover:underline">
            View Engine <ArrowUpRight className="w-4 h-4" />
          </button>
        </motion.div>
      </div>

      {/* Chart + Allocation */}
      <div className="grid lg:grid-cols-3 gap-6">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}
          className="lg:col-span-2 bg-card border border-border rounded-3xl p-6">
          <div className="flex items-center justify-between mb-6">
            <h3 className="font-display text-xl font-bold">Performance</h3>
            <div className="flex bg-background border border-border rounded-lg p-1 text-xs">
              {['1W', '1M', '3M', 'YTD', '1Y'].map(tf => (
                <button key={tf} onClick={() => setTimeframe(tf)}
                  className={`px-3 py-1 rounded-md transition-colors ${timeframe === tf ? 'bg-theme_blue text-white' : 'text-muted-foreground hover:text-foreground'}`}>
                  {tf}
                </button>
              ))}
            </div>
          </div>
          <div className="h-[300px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 11 }} interval={Math.floor(chartData.length / 6)} />
                <YAxis hide domain={['dataMin - 1000', 'dataMax + 1000']} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#09090B', border: '1px solid #27272A', borderRadius: '12px' }}
                  itemStyle={{ color: '#E4E4E7' }}
                  formatter={(v: any) => [`${CUR}${Number(v).toLocaleString(LOC, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 'Value']}
                />
                <Area type="monotone" dataKey="value" stroke="#3B82F6" strokeWidth={3} fill="url(#colorValue)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}
          className="bg-card border border-border rounded-3xl p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-display text-xl font-bold">Allocation</h3>
            <button className="text-muted-foreground hover:text-foreground"><Settings2 className="w-5 h-5" /></button>
          </div>
          <div className="h-[200px] w-full relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={allocationData} cx="50%" cy="50%" innerRadius={55} outerRadius={78} paddingAngle={4} dataKey="value" stroke="none">
                  {allocationData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                </Pie>
                <Tooltip contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a', borderRadius: '12px', border: 'none' }} itemStyle={{ color: '#fff' }} />
              </PieChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none flex-col">
              <span className="text-2xl font-display font-bold">{allocationData.length}</span>
              <span className="text-xs text-muted-foreground uppercase tracking-wider">Sectors</span>
            </div>
          </div>
          <div className="space-y-2 mt-4">
            {allocationData.map(item => (
              <div key={item.name} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-muted-foreground">{item.name}</span>
                </div>
                <span className="font-bold">{item.value}%</span>
              </div>
            ))}
          </div>
        </motion.div>
      </div>

      {/* Risk Alerts */}
      {riskData?.alerts?.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-2">
          {riskData.alerts.map((alert: any, i: number) => (
            <div key={i} className={`flex items-center gap-3 p-4 rounded-2xl border ${alert.level === 'CRITICAL' ? 'border-theme_red/40 bg-theme_red/5' : 'border-theme_yellow/40 bg-theme_yellow/5'}`}>
              <AlertCircle className={`w-5 h-5 shrink-0 ${alert.level === 'CRITICAL' ? 'text-theme_red' : 'text-theme_yellow'}`} />
              <p className="text-sm font-medium">{alert.msg}</p>
              <span className={`ml-auto text-xs font-bold px-2 py-0.5 rounded-md ${alert.level === 'CRITICAL' ? 'bg-theme_red/20 text-theme_red' : 'bg-theme_yellow/20 text-theme_yellow'}`}>{alert.level}</span>
            </div>
          ))}
        </motion.div>
      )}

      {/* Holdings Table */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}
        className="bg-card border border-border rounded-3xl p-6 overflow-hidden">
        <h3 className="font-display text-xl font-bold mb-6">Active Holdings
          <span className="ml-3 text-sm font-normal text-muted-foreground">({liveHoldings.length} positions)</span>
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-muted-foreground uppercase tracking-wider">
              <tr className="border-b border-border">
                <th className="px-4 py-3 font-semibold">Asset</th>
                <th className="px-4 py-3 font-semibold text-right">Shares</th>
                <th className="px-4 py-3 font-semibold text-right">Entry Price</th>
                <th className="px-4 py-3 font-semibold text-right">Current Price</th>
                <th className="px-4 py-3 font-semibold text-right">Total Value</th>
                <th className="px-4 py-3 font-semibold text-right">P&L</th>
                <th className="px-4 py-3 font-semibold text-right">Stop / TP</th>
              </tr>
            </thead>
            <tbody>
              {liveHoldings.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center gap-3 text-muted-foreground">
                      <TrendingUp className="w-12 h-12 opacity-20" />
                      <p className="font-medium">No active positions yet</p>
                      <p className="text-xs">Start the Auto Trader engine to let the AI Committee execute its first trade.</p>
                      <button
                        className="mt-2 bg-theme_blue text-white px-4 py-2 rounded-xl text-sm font-medium hover:bg-theme_blue/90 transition-colors"
                        onClick={() => navigate(autoTraderPath)}>
                        Open Auto Trader
                      </button>
                    </div>
                  </td>
                </tr>
              ) : (
                liveHoldings.map((h: any, idx: number) => {
                  const entryPrice = Number(h.entry_price) || 0;
                  const currentPrice = Number(h.current_price) || 0;
                  const value = Number(h.value) || 0;
                  const change = Number(h.change) || 0;
                  const stopLoss = Number(h.stop_loss) || 0;
                  const takeProfit = Number(h.take_profit) || 0;
                  const pnlAmt = value - (entryPrice * Number(h.shares));
                  const mgScore = h.metagate_score;
                  const isBreakeven = h.breakeven_triggered;
                  return (
                    <motion.tr key={`${h.symbol}-${idx}`}
                      initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: idx * 0.05 }}
                      className="border-b border-border/50 hover:bg-background/50 transition-colors">
                      <td className="px-4 py-4 font-bold font-display text-base">
                        <div>{h.symbol}</div>
                        {mgScore !== undefined && mgScore !== null && (
                          <div className="text-xs font-normal text-muted-foreground">
                            MetaGate: <span className={mgScore >= 0.5 ? 'text-theme_green' : 'text-theme_red'}>{mgScore.toFixed(2)}</span>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-4 text-right text-muted-foreground">{h.shares}</td>
                      <td className="px-4 py-4 text-right text-muted-foreground">{CUR}{entryPrice.toLocaleString(LOC)}</td>
                      <td className="px-4 py-4 text-right font-medium">{CUR}{currentPrice.toLocaleString(LOC)}</td>
                      <td className="px-4 py-4 text-right font-medium">{CUR}{value.toLocaleString(LOC)}</td>
                      <td className={`px-4 py-4 text-right font-bold ${change >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
                        <div>{change >= 0 ? '+' : '-'}{CUR}{Math.abs(pnlAmt).toLocaleString(LOC)}</div>
                        <div className="text-xs opacity-75">{change >= 0 ? '+' : ''}{change.toFixed(2)}%</div>
                      </td>
                      <td className="px-4 py-4 text-right font-mono text-xs">
                        <div className="flex flex-col items-end gap-1">
                          <div>
                            <span className="text-theme_red">{stopLoss > 0 ? `SL: ${CUR}${stopLoss.toFixed(2)}` : '—'}</span>
                            <span className="text-muted-foreground mx-1">/</span>
                            <span className="text-theme_green">{takeProfit > 0 ? `TP: ${CUR}${takeProfit.toFixed(2)}` : '—'}</span>
                          </div>
                          {isBreakeven && (
                            <span className="bg-theme_blue/20 text-theme_blue px-1.5 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider">
                              Breakeven SL
                            </span>
                          )}
                        </div>
                      </td>
                    </motion.tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </motion.div>

      <DepositModal isOpen={isDepositOpen} onClose={() => setDepositOpen(false)} />
    </div>
  );
};
