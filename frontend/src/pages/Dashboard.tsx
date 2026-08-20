import { useState, useMemo, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useOutletContext, useNavigate } from 'react-router-dom';
import { TrendingUp, Activity, BarChart3, Clock, ArrowRight, Zap, Target, Bot, CheckCircle, XCircle, HelpCircle, Sparkles } from 'lucide-react';
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip } from 'recharts';
import TradingViewWidget from '../components/TradingViewWidget';
import { API_BASE } from '../config';

export const Dashboard = ({ market = 'US' }: { market?: 'US' | 'INDIA' | 'STOCKS' | 'CRYPTO' | 'FOREX' }) => {
  const { isBeginnerMode } = useOutletContext<{ isBeginnerMode: boolean }>();
  const navigate = useNavigate();
  const [timeframe, setTimeframe] = useState('1D');
  const [marketSymbol, setMarketSymbol] = useState(
    market === 'INDIA'  ? 'BSE:SENSEX'         :
    market === 'STOCKS' ? 'NASDAQ:AAPL'         :
    market === 'CRYPTO' ? 'BITSTAMP:BTCUSD'     :
    market === 'FOREX'  ? 'FX:EURUSD'           :
    'TVC:GOLD'
  );
  
  const [balance, setBalance] = useState(1.0);
  const [historyData, setHistoryData] = useState<any[]>([]);
  const [activeTrades, setActiveTrades] = useState(0);
  const [, setLiveHoldings] = useState<any[]>([]);
  const [botLogs, setBotLogs] = useState<any[]>([]);
  const [rlStats, setRlStats] = useState<any>(null);
  const [globalSentiment, setGlobalSentiment] = useState<{ label: string; score: number }>({ label: 'Neutral', score: 0.0 });
  const [gates, setGates] = useState<any>(null);

  // Reset chart symbol and data when market tab changes
  useEffect(() => {
    setMarketSymbol(
      market === 'INDIA'  ? 'BSE:SENSEX'     :
      market === 'STOCKS' ? 'NASDAQ:AAPL'    :
      market === 'CRYPTO' ? 'BITSTAMP:BTCUSD':
      market === 'FOREX'  ? 'FX:EURUSD'      :
      'TVC:GOLD'
    );
    setBalance(1.0);
    setHistoryData([]);
    setActiveTrades(0);
    setLiveHoldings([]);
    setBotLogs([]);
    setRlStats(null);
    setGlobalSentiment({ label: 'Neutral', score: 0.0 });
    setGates(null);
  }, [market]);

  useEffect(() => {
    const fetchPortfolio = async () => {
      try {
        const activeApiBase =
          market === 'INDIA'  ? `${API_BASE}/indian`  :
          market === 'STOCKS' ? `${API_BASE}/stocks`   :
          market === 'CRYPTO' ? `${API_BASE}/crypto`   :
          market === 'FOREX'  ? `${API_BASE}/forex`    :
          API_BASE;
        const [holdRes, histRes, statusRes, logsRes, rlRes, newsRes, gatesRes] = await Promise.all([
          fetch(`${activeApiBase}/portfolio/holdings`),
          fetch(`${activeApiBase}/portfolio/history?timeframe=${timeframe}`),
          fetch(`${activeApiBase}/bot/status`),
          fetch(`${activeApiBase}/bot/logs`),
          fetch(`${activeApiBase}/analytics/rl-stats`),
          fetch(`${API_BASE}/news/global`),
          fetch(`${activeApiBase}/analytics/gates`)
        ]);
        if (holdRes.ok) {
          const data = await holdRes.json();
          if (typeof data.balance === 'number') setBalance(data.balance);
          if (Array.isArray(data.holdings)) setLiveHoldings(data.holdings);
        }
        if (histRes.ok) {
          const data = await histRes.json();
          setHistoryData(data.history || []);
        }
        if (statusRes.ok) {
          const data = await statusRes.json();
          if (typeof data.active_trades === 'number') setActiveTrades(data.active_trades);
        }
        if (logsRes.ok) {
          const data = await logsRes.json();
          setBotLogs(data.logs || []);
        }
        if (rlRes.ok) {
          const data = await rlRes.json();
          setRlStats(data);
        }
        if (gatesRes.ok) {
          const data = await gatesRes.json();
          setGates(data);
        }
        if (newsRes.ok) {
          const data = await newsRes.json();
          const articles = data.articles || [];
          if (articles.length > 0) {
            const avgScore = articles.reduce((sum: number, art: any) => sum + (art.sentiment_score || 0), 0) / articles.length;
            let label = 'Neutral';
            if (avgScore >= 0.05) label = 'Bullish';
            else if (avgScore <= -0.05) label = 'Bearish';
            setGlobalSentiment({ label, score: avgScore });
          }
        }
      } catch {
        // Silent fail if backend offline
      }
    };
    fetchPortfolio();
    const interval = setInterval(fetchPortfolio, 5000);
    return () => clearInterval(interval);
  }, [timeframe, market]);

  const { chartData, liveBalance, livePercent } = useMemo(() => {
    if (!historyData || historyData.length === 0) {
      return { chartData: [], liveBalance: balance.toFixed(2), livePercent: 0 };
    }
    const first = historyData[0].value;
    const last = historyData[historyData.length - 1].value;
    const pct = first > 0 ? ((last - first) / first) * 100 : 0;

    return { 
      chartData: historyData, 
      liveBalance: last.toFixed(2), 
      livePercent: pct 
    };
  }, [historyData, balance]);

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12">
      
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h1 className="font-display text-4xl md:text-5xl font-bold tracking-tight mb-2">
            {market === 'INDIA'  ? '🌏 Indian Command Center'     :
             market === 'STOCKS' ? '📈 Tech Stocks Command Center' :
             market === 'CRYPTO' ? '₿ Crypto Command Center'      :
             market === 'FOREX'  ? '💱 Forex Command Center'      :
             '🌐 US Command Center'}
          </h1>
          <p className="text-muted-foreground text-lg">Your autonomous portfolio, visualized.</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="px-4 py-2 bg-theme_green/10 border border-theme_green/20 rounded-xl flex items-center gap-2 text-sm font-bold text-theme_green">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-theme_green opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-theme_green"></span>
            </span>
            AI Engine Online
          </div>
        </div>
      </div>

      <div className="grid xl:grid-cols-3 gap-6">
        
        {/* Main Chart Card */}
        <motion.div 
          initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} 
          className="xl:col-span-2 bg-card border border-border rounded-3xl p-6 sm:p-8 flex flex-col min-h-[400px] relative overflow-hidden"
        >
          <div className="absolute top-0 right-0 w-64 h-64 bg-theme_blue/5 rounded-bl-full -z-10 blur-3xl"></div>
          
          <div className="flex justify-between items-start mb-8">
            <div className="flex items-center gap-4">
              <div className={`p-4 rounded-2xl ${market === 'INDIA' ? 'bg-orange-500/10 text-orange-500' : 'bg-theme_blue/10 text-theme_blue'}`}>
                <Activity className="w-8 h-8" />
              </div>
              <div>
                <p className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-1">Portfolio Capital</p>
                <div className="flex items-end gap-3">
                  <h2 className="text-4xl font-display font-bold text-foreground">
                    {market === 'INDIA' ? '₹' : '$'}{parseFloat(liveBalance ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </h2>
                  <span className={`${livePercent >= 0 ? 'text-theme_green bg-theme_green/10' : 'text-theme_red bg-theme_red/10'} font-bold text-lg flex items-center px-2 py-0.5 rounded-lg`}>
                    <TrendingUp className="w-4 h-4 mr-1" /> {livePercent >= 0 ? '+' : ''}{livePercent.toFixed(2)}%
                  </span>
                </div>
              </div>
            </div>
            <div className="hidden sm:flex bg-background border border-border rounded-xl p-1">
              {['1D', '1W', '1M', 'YTD', '1Y'].map((t) => (
                <button 
                  key={t} 
                  onClick={() => setTimeframe(t)}
                  className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-all ${timeframe === t ? 'bg-card text-foreground shadow-sm border border-border' : 'text-muted-foreground hover:text-foreground'}`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 w-full h-[250px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#3B82F6" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="name" hide />
                <YAxis hide domain={['auto', 'auto']} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#09090B', border: '1px solid #27272A', borderRadius: '12px' }}
                  itemStyle={{ color: '#E4E4E7' }}
                  formatter={(value: any) => [`$${Number(value).toLocaleString()}`, 'Portfolio']}
                  labelStyle={{ display: 'none' }}
                />
                <Area type="monotone" dataKey="value" stroke="#3B82F6" fill="url(#colorValue)" strokeWidth={4} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </motion.div>

        {/* Right Column (Metrics & Dial) */}
        <div className="xl:col-span-1 space-y-6">
          
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="bg-card border border-border rounded-3xl p-6 h-[200px] flex flex-col justify-between">
            <div className="flex justify-between items-start">
              <div>
                <p className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-1">Global Sentiment</p>
                <h3 className={`text-2xl font-display font-bold ${
                  globalSentiment.label === 'Bullish' ? 'text-theme_green' : 
                  globalSentiment.label === 'Bearish' ? 'text-theme_red' : 'text-theme_yellow'
                }`}>
                  {globalSentiment.label} ({globalSentiment.score >= 0 ? '+' : ''}{globalSentiment.score.toFixed(2)})
                </h3>
              </div>
              <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                globalSentiment.label === 'Bullish' ? 'bg-theme_green/10 text-theme_green' : 
                globalSentiment.label === 'Bearish' ? 'bg-theme_red/10 text-theme_red' : 'bg-theme_yellow/10 text-theme_yellow'
              }`}>
                <BarChart3 className="w-5 h-5" />
              </div>
            </div>
            <div>
              <div className="flex justify-between text-xs font-medium text-muted-foreground mb-2">
                <span>Losses</span>
                <span>Wins</span>
              </div>
              <div className="w-full bg-background rounded-full h-3 border border-border relative overflow-hidden">
                <div 
                  className="absolute top-0 left-0 h-full bg-gradient-to-r from-theme_red to-theme_green rounded-full transition-all"
                  style={{ width: `${rlStats?.win_rate_pct || 0}%` }}
                ></div>
                <div 
                  className="absolute top-0 -ml-1 w-2 h-full bg-foreground rounded-full shadow-lg transition-all"
                  style={{ left: `${rlStats?.win_rate_pct || 0}%` }}
                ></div>
              </div>
              <p className="text-center text-xs font-medium text-muted-foreground mt-3">
                Real Win Rate: {rlStats?.win_rate_pct || 0}% ({rlStats?.total_closed_trades || 0} trades)
              </p>
            </div>
          </motion.div>

          <motion.div 
            initial={{ opacity: 0, y: 20 }} 
            animate={{ opacity: 1, y: 0 }} 
            transition={{ delay: 0.2 }} 
            onClick={() => navigate(market === 'INDIA' ? '/indian-market' : market === 'STOCKS' ? '/stocks-market' : market === 'CRYPTO' ? '/crypto-market' : market === 'FOREX' ? '/forex-market' : '/autotrader')}
            className="bg-card border border-border rounded-3xl p-6 h-[175px] flex flex-col justify-center relative overflow-hidden group cursor-pointer"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-theme_blue/5 to-purple-500/5 group-hover:opacity-100 opacity-50 transition-opacity"></div>
            <div className="relative z-10 flex items-center justify-between">
              <div>
                <div className="w-10 h-10 rounded-full bg-theme_blue/20 flex items-center justify-center mb-3 text-theme_blue">
                  <Bot className="w-5 h-5" />
                </div>
                <p className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-1">Active AI Trades</p>
                <h3 className="text-3xl font-display font-bold">{activeTrades}</h3>
              </div>
              <ArrowRight className="w-6 h-6 text-muted-foreground group-hover:text-theme_blue group-hover:translate-x-2 transition-all" />
            </div>
          </motion.div>

          {/* Live Risk Gates Tracker */}
          <motion.div 
            initial={{ opacity: 0, y: 20 }} 
            animate={{ opacity: 1, y: 0 }} 
            transition={{ delay: 0.15 }} 
            className="bg-card border border-border rounded-3xl p-6 flex flex-col justify-between"
          >
            <div>
              <p className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-4 flex items-center gap-2">
                <Target className="w-4 h-4 text-theme_blue animate-pulse" /> Live Risk Gates
              </p>
              <div className="space-y-3">
                {Object.entries(gates || {
                  event_blackout: { status: 'NOT_EVALUATED', details: 'Waiting for scan...' },
                  mtf_alignment: { status: 'NOT_EVALUATED', details: 'Waiting for scan...' },
                  correlation_gate: { status: 'NOT_EVALUATED', details: 'Waiting for scan...' },
                  monte_carlo_ev: { status: 'NOT_EVALUATED', details: 'Waiting for scan...' }
                }).map(([key, gate]: [string, any]) => {
                  const label = key.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase());
                  
                  let icon = <HelpCircle className="w-4 h-4 text-muted-foreground" />;
                  let bgClass = "bg-muted/10 border-border/50 text-muted-foreground";
                  if (gate.status === 'PASSED') {
                    icon = <CheckCircle className="w-4 h-4 text-emerald-500" />;
                    bgClass = "bg-emerald-500/10 border-emerald-500/20 text-emerald-500";
                  } else if (gate.status === 'BLOCKED') {
                    icon = <XCircle className="w-4 h-4 text-red-500 animate-bounce" />;
                    bgClass = "bg-red-500/10 border-red-500/20 text-red-500 font-bold";
                  }
                  
                  return (
                    <div key={key} className={`p-3 border rounded-2xl flex items-start gap-3 transition-all hover:bg-opacity-20 ${bgClass}`}>
                      <div className="mt-0.5 shrink-0">
                        {icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex justify-between items-center">
                          <span className="font-bold text-xs uppercase tracking-wider">{label}</span>
                          <span className="text-[9px] font-bold uppercase tracking-widest">{gate.status.replace('_', ' ')}</span>
                        </div>
                        <p className="text-[11px] font-medium opacity-80 mt-1 leading-normal break-words">
                          {gate.details}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </motion.div>

        </div>
      </div>

      {/* Market Overview Row */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }} className="bg-card border border-border rounded-3xl p-6 h-[600px] flex flex-col">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
          <h3 className="font-display font-bold text-xl flex items-center gap-2"><BarChart3 className="w-5 h-5 text-theme_blue" /> Market Overview</h3>
          
          <div className="flex overflow-x-auto bg-background border border-border rounded-lg p-1 text-xs no-scrollbar">
            {(market === 'INDIA'  ? [{ label: 'BSE Sensex', sym: 'BSE:SENSEX' }, { label: 'Reliance', sym: 'BSE:RELIANCE' }] :
              market === 'STOCKS' ? [{ label: 'AAPL', sym: 'NASDAQ:AAPL' }, { label: 'NVDA', sym: 'NASDAQ:NVDA' }, { label: 'MSFT', sym: 'NASDAQ:MSFT' }] :
              market === 'CRYPTO' ? [{ label: 'BTC/USD', sym: 'BITSTAMP:BTCUSD' }, { label: 'ETH/USD', sym: 'BITSTAMP:ETHUSD' }, { label: 'SOL/USD', sym: 'COINBASE:SOLUSD' }] :
              market === 'FOREX'  ? [{ label: 'EUR/USD', sym: 'FX:EURUSD' }, { label: 'GBP/USD', sym: 'FX:GBPUSD' }, { label: 'USD/JPY', sym: 'FX:USDJPY' }] :
              [{ label: 'Gold', sym: 'TVC:GOLD' }, { label: 'Nasdaq QQQ', sym: 'NASDAQ:QQQ' }, { label: 'S&P 500', sym: 'SP:SPX' }]
            ).map((m) => (
              <button 
                key={m.label} 
                onClick={() => setMarketSymbol(m.sym)}
                className={`px-4 py-2 whitespace-nowrap font-bold rounded-lg transition-all ${marketSymbol === m.sym ? 'bg-card text-foreground shadow-sm border border-border' : 'text-muted-foreground hover:text-foreground'}`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 w-full rounded-2xl overflow-hidden relative">
          <div className="absolute inset-0">
            <TradingViewWidget symbol={marketSymbol} isBeginnerMode={isBeginnerMode} />
          </div>
        </div>
      </motion.div>

      {/* Bottom Row */}
      <div className="grid lg:grid-cols-2 gap-6">
        
        {/* Recent Activity */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="bg-card border border-border rounded-3xl p-6 sm:p-8">
          <div className="flex items-center justify-between mb-6">
            <h3 className="font-display font-bold text-xl flex items-center gap-2"><Activity className="w-5 h-5 text-theme_blue" /> Engine Activity</h3>
            <button onClick={() => navigate(market === 'INDIA' ? '/indian-market' : market === 'STOCKS' ? '/stocks-market' : market === 'CRYPTO' ? '/crypto-market' : market === 'FOREX' ? '/forex-market' : '/autotrader')} className="text-sm font-medium text-theme_blue hover:underline">View all</button>
          </div>
          
          <div className="space-y-4">
            {botLogs.slice(-3).reverse().map((log: any, idx: number) => (
              <div key={idx} className="flex items-center justify-between p-4 bg-background border border-border rounded-2xl group hover:border-theme_blue/30 transition-colors">
                <div className="flex items-center gap-4">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${log.level === 'warning' ? 'bg-theme_yellow/10 text-theme_yellow' : 'bg-theme_blue/10 text-theme_blue'}`}>
                    <Zap className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="font-bold text-sm truncate max-w-[250px]">{log.message}</h4>
                    <p className="text-xs text-muted-foreground uppercase">{log.level}</p>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-muted-foreground flex items-center justify-end gap-1"><Clock className="w-3 h-3" /> {log.timestamp}</div>
                </div>
              </div>
            ))}
            {botLogs.length === 0 && (
              <div className="text-center text-sm text-muted-foreground p-4">No recent activity</div>
            )}
          </div>
        </motion.div>

        {/* Explainable AI Voting Contributions */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }} className="bg-card border border-border rounded-3xl p-6 sm:p-8 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-6">
              <h3 className="font-display font-bold text-xl flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-purple-500 animate-pulse" /> Explainable AI
              </h3>
              <span className="text-[10px] font-bold uppercase tracking-widest bg-purple-500/10 text-purple-400 px-2.5 py-0.5 rounded-full">
                Live Voting Contribution
              </span>
            </div>
            
            {(() => {
              const latestDecisionLog = [...botLogs].reverse().find((l: any) => l.decision?.committee_breakdown);
              const breakdown = latestDecisionLog?.decision?.committee_breakdown || [];
              
              if (breakdown.length > 0) {
                return (
                  <div className="space-y-4">
                    <p className="text-xs text-muted-foreground mb-4">
                      Relative voting impact of each committee member on the latest decision ({latestDecisionLog.decision.signal} signal with {(latestDecisionLog.decision.confidence * 100).toFixed(0)}% confidence):
                    </p>
                    <div className="space-y-4">
                      {breakdown.map((agent: any, idx: number) => {
                        const contribution = Number(agent.contribution || 0);
                        const weight = Number(agent.weight || 1.0);
                        const maxVal = 1.5;
                        const percent = Math.min(100, Math.max(0, (Math.abs(contribution) / maxVal) * 100));
                        const isPositive = contribution >= 0;
                        
                        return (
                          <div key={idx} className="space-y-1">
                            <div className="flex justify-between text-xs font-bold">
                              <span className="text-muted-foreground">{agent.agent}</span>
                              <span className={contribution === 0 ? 'text-muted-foreground' : isPositive ? 'text-emerald-500' : 'text-red-500'}>
                                {contribution > 0 ? '+' : ''}{contribution.toFixed(2)} (w: {weight.toFixed(1)})
                              </span>
                            </div>
                            <div className="w-full bg-background rounded-full h-2 border border-border relative overflow-hidden flex">
                              {isPositive ? (
                                <>
                                  <div className="w-1/2"></div>
                                  <div 
                                    className="h-full bg-emerald-500 rounded-r-full transition-all"
                                    style={{ width: `${percent / 2}%` }}
                                  />
                                </>
                              ) : (
                                <>
                                  <div className="w-1/2 flex justify-end">
                                    <div 
                                      className="h-full bg-red-500 rounded-l-full transition-all"
                                      style={{ width: `${percent / 2}%` }}
                                    />
                                  </div>
                                  <div className="w-1/2"></div>
                                </>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              }
              
              return (
                <div className="text-center py-12 space-y-3">
                  <div className="w-12 h-12 mx-auto bg-muted rounded-full flex items-center justify-center text-muted-foreground">
                    <Activity className="w-6 h-6 animate-pulse" />
                  </div>
                  <p className="text-sm text-muted-foreground font-medium">
                    Waiting for next decision tick to stream live voting details...
                  </p>
                </div>
              );
            })()}
          </div>
        </motion.div>

      </div>
    </div>
  );
};
