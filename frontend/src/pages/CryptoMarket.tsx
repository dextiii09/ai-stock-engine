import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity, RefreshCw, Crosshair, Brain,
  TrendingUp, Zap, Globe, Layers, ArrowRight
} from 'lucide-react';
import { API_BASE } from '../config';

const SYMBOLS = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD'];

export const CryptoMarket = () => {
  const navigate = useNavigate();
  const [regime, setRegime] = useState<any>(null);
  const [portfolioData, setPortfolioData] = useState<any>(null);
  const [opportunities, setOpportunities] = useState<any[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState('BTC-USD');
  const [livePrice, setLivePrice] = useState<any>(null);
  const [openPositions, setOpenPositions] = useState(0);

  useEffect(() => {
    const fetch_ = async () => {
      try {
        const res = await fetch(`${API_BASE}/crypto/data/live/${encodeURIComponent(selectedSymbol)}`);
        if (res.ok) setLivePrice(await res.json());
      } catch { /* offline */ }
    };
    fetch_();
    const id = setInterval(fetch_, 5000);
    return () => clearInterval(id);
  }, [selectedSymbol]);

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [regimeRes, portfolioRes, holdingsRes, oppRes] = await Promise.all([
          fetch(`${API_BASE}/crypto/data/regime`),
          fetch(`${API_BASE}/crypto/portfolio/money-tracker`),
          fetch(`${API_BASE}/crypto/portfolio/holdings`),
          fetch(`${API_BASE}/crypto/opportunities`),
        ]);
        if (regimeRes.ok) setRegime(await regimeRes.json());
        if (portfolioRes.ok) setPortfolioData(await portfolioRes.json());
        if (holdingsRes.ok) { const h = await holdingsRes.json(); setOpenPositions((h.holdings || []).length); }
        if (oppRes.ok) { const d = await oppRes.json(); if (d.opportunities) setOpportunities(d.opportunities); }
      } catch { /* backend offline */ }
    };
    fetchAll();
    const id = setInterval(fetchAll, 8000);
    return () => clearInterval(id);
  }, []);

  const balance    = portfolioData?.summary?.current_balance ?? 0;
  const profitLoss = portfolioData?.summary?.total_pnl ?? 0;
  const activeHoldings = portfolioData?.active_holdings ?? [];

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12">

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 bg-card border border-border p-6 rounded-3xl relative overflow-hidden">
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-orange-500 via-amber-400 to-yellow-500" />
        <div className="absolute top-0 right-0 w-64 h-64 bg-orange-500/5 rounded-bl-[100px] -z-10" />
        <div>
          <h1 className="font-display text-4xl font-bold tracking-tight mb-2 flex items-center gap-3">
            <Globe className="w-10 h-10 text-orange-500" /> Crypto Market
          </h1>
          <p className="text-muted-foreground text-sm max-w-xl">
            Live crypto market data — prices, signals &amp; AI regime. Auto-trade runs on the AutoTrader page.
          </p>
        </div>
        <button
          onClick={() => navigate('/autotrader')}
          className="flex items-center gap-2 px-6 py-3 bg-orange-500 text-white rounded-2xl font-bold text-sm hover:bg-orange-600 hover:scale-105 transition-all shadow-lg shadow-orange-500/20 whitespace-nowrap"
        >
          Open AutoTrader <ArrowRight className="w-4 h-4" />
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <div className="bg-card border border-border rounded-3xl p-5 flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-orange-500/10 text-orange-500 flex items-center justify-center shrink-0">
            <Crosshair className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-0.5">Open Positions</p>
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

        <div className="bg-card border border-border rounded-3xl p-5 flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-amber-500/10 text-amber-400 flex items-center justify-center shrink-0">
            <TrendingUp className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-0.5">Capital</p>
            <p className="text-lg font-bold">${balance.toLocaleString('en-US', { maximumFractionDigits: 0 })}</p>
            <p className={`text-xs font-bold ${profitLoss >= 0 ? 'text-orange-500' : 'text-red-500'}`}>
              {profitLoss >= 0 ? '+' : ''}${profitLoss.toLocaleString('en-US', { maximumFractionDigits: 2 })} PnL
            </p>
          </div>
        </div>
      </div>

      {/* Main layout */}
      <div className="grid xl:grid-cols-3 gap-8">

        <div className="xl:col-span-2 space-y-6">

          {/* Live Price Monitor */}
          <div className="bg-card border border-border p-6 rounded-3xl space-y-4">
            <div className="flex items-center justify-between border-b border-border/50 pb-4">
              <h3 className="font-display font-bold text-lg flex items-center gap-2">
                <Activity className="w-5 h-5 text-orange-500 animate-pulse" /> Live Price Monitor
              </h3>
              <div className="flex bg-background border border-border rounded-xl p-1 text-xs flex-wrap gap-1">
                {SYMBOLS.map(sym => (
                  <button
                    key={sym}
                    onClick={() => setSelectedSymbol(sym)}
                    className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                      selectedSymbol === sym ? 'bg-orange-500/10 text-orange-500' : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {sym.replace('-USD', '')}
                  </button>
                ))}
              </div>
            </div>
            {livePrice ? (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 p-4 bg-background/50 border border-border/50 rounded-2xl">
                <div>
                  <span className="text-[10px] text-muted-foreground font-bold uppercase">Price</span>
                  <p className="font-display text-lg font-bold">${livePrice.price?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground font-bold uppercase">RSI-14</span>
                  <p className="font-display text-lg font-bold">{livePrice.rsi_14?.toFixed(1) ?? 'N/A'}</p>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground font-bold uppercase">MACD Hist</span>
                  <p className="font-display text-lg font-bold">{livePrice.macd_hist?.toFixed(4) ?? 'N/A'}</p>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground font-bold uppercase">24h Change</span>
                  <p className={`font-display text-lg font-bold ${
                    (livePrice.daily_change_pct ?? 0) >= 0 ? 'text-orange-500' : 'text-red-500'
                  }`}>
                    {livePrice.daily_change_pct != null ? `${livePrice.daily_change_pct > 0 ? '+' : ''}${livePrice.daily_change_pct.toFixed(2)}%` : 'N/A'}
                  </p>
                </div>
              </div>
            ) : (
              <div className="h-20 flex items-center justify-center text-muted-foreground text-sm font-medium">
                <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Connecting to Yahoo Finance feed...
              </div>
            )}
          </div>

          {/* Active Holdings */}
          <div className="bg-card border border-border rounded-3xl p-6">
            <h3 className="font-display font-bold text-xl mb-4 flex items-center gap-2">
              <Layers className="w-5 h-5 text-orange-500" /> Active Holdings
            </h3>
            {activeHoldings.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-border/50 text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                      <th className="pb-3">Symbol</th>
                      <th className="pb-3">Units</th>
                      <th className="pb-3">Entry</th>
                      <th className="pb-3">Current</th>
                      <th className="pb-3 text-right">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeHoldings.map((h: any) => (
                      <tr key={h.symbol} className="border-b border-border/30 last:border-none text-sm">
                        <td className="py-4 font-bold">{h.symbol}</td>
                        <td className="py-4 text-muted-foreground">{h.shares}</td>
                        <td className="py-4">${h.entry_price?.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                        <td className="py-4">${h.current_price?.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                        <td className="py-4 text-right font-bold text-orange-500">${h.value?.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-8 border border-dashed border-border rounded-2xl text-center text-muted-foreground text-sm">
                No active positions. Start the bot on the AutoTrader page to begin trading.
              </div>
            )}
          </div>
        </div>

        {/* Right sidebar */}
        <div className="xl:col-span-1 space-y-6">

          {/* Signals */}
          <div className="bg-card border border-border rounded-3xl p-6">
            <h3 className="font-display font-bold text-lg mb-5 flex items-center gap-2">
              <Crosshair className="w-5 h-5 text-orange-500" /> Crypto Signals
            </h3>
            <div className="space-y-3">
              {opportunities.length === 0 ? (
                <p className="text-xs text-muted-foreground italic">Scanning crypto universe...</p>
              ) : (
                opportunities.slice(0, 6).map((opp, idx) => (
                  <div key={idx} className="p-3 bg-background border border-border rounded-xl flex items-center justify-between">
                    <div>
                      <p className="font-bold text-sm">{opp.symbol}</p>
                      <p className="text-xs text-muted-foreground">Conf: {opp.confidence}%</p>
                    </div>
                    <span className={`px-3 py-1 rounded-lg text-xs font-bold ${
                      opp.signal === 'BUY'  ? 'bg-orange-500/20 text-orange-500' :
                      opp.signal === 'SELL' ? 'bg-red-500/20 text-red-500' :
                                              'bg-amber-500/20 text-amber-500'
                    }`}>{opp.signal}</span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* AI Coach */}
          <div className="bg-[#0c0c0e] border border-border rounded-3xl p-6 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-32 h-32 bg-orange-500/5 rounded-bl-[100px] -z-10" />
            <h3 className="font-display font-bold text-lg mb-3 flex items-center gap-2 text-orange-400">
              <Brain className="w-5 h-5" /> AI Coach Insight
            </h3>
            {opportunities.length > 0 ? (
              <div className="space-y-3 relative z-10">
                <p className="text-sm font-semibold">{opportunities[0].symbol} Decision:</p>
                <div className="bg-black/40 p-3 rounded-lg border border-[#27272A]">
                  <p className="text-xs text-muted-foreground italic">Reason:</p>
                  <p className="text-sm">{opportunities[0].reason}</p>
                </div>
                <div className="bg-orange-500/10 p-3 rounded-lg border border-orange-500/20">
                  <p className="text-xs text-orange-400 italic font-bold">Recommendation:</p>
                  <p className="text-sm text-orange-400">{opportunities[0].recommendation}</p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">Waiting for first scan to complete...</p>
            )}
          </div>

          {regime?.active_strategy && (
            <div className="bg-card border border-border rounded-3xl p-6">
              <h3 className="font-display font-bold text-lg mb-3 flex items-center gap-2">
                <Zap className="w-5 h-5 text-orange-500" /> Active Strategy
              </h3>
              <p className="text-sm font-bold text-orange-500 mb-1">{regime.active_strategy.name}</p>
              <p className="text-xs text-muted-foreground">{regime.active_strategy.description ?? 'RL-selected for current regime.'}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
