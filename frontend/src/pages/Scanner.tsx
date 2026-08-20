import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, TrendingUp, TrendingDown, DollarSign, Globe, Percent, Lock, Cpu, RefreshCw } from 'lucide-react';
import { API_BASE } from '../config';

export const Scanner = () => {
  const [data, setData] = useState<any>(null);
  const [usOpportunities, setUsOpportunities] = useState<any[]>([]);
  const [indianOpportunities, setIndianOpportunities] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'US' | 'INDIA'>('US');
  const [, setLoading] = useState(true);

  const fetchAll = async () => {
    try {
      const [macroRes, usOppRes, indOppRes] = await Promise.all([
        fetch(`${API_BASE}/analytics/macro`),
        fetch(`${API_BASE}/opportunities`),
        fetch(`${API_BASE}/indian/opportunities`),
      ]);

      if (macroRes.ok) setData(await macroRes.json());
      if (usOppRes.ok) {
        const u = await usOppRes.json();
        setUsOpportunities(u.opportunities || []);
      }
      if (indOppRes.ok) {
        const i = await indOppRes.json();
        setIndianOpportunities(i.opportunities || []);
      }
    } catch (e) {
      // Backend offline
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, []);

  const fallbackData = {
    dxy: { price: 104.50, change: -0.2 },
    vix: { price: 14.20, change: 1.5 },
    tips10y: { price: 1.95, change: -0.05 },
    gold_cot: { positioning: "BULLISH", net_longs: 145000 },
    nq_cot: { positioning: "BEARISH", net_longs: -45000 },
    london_fix: false,
    rollover_week: false
  };

  const activeData = data || fallbackData;
  const oppList = activeTab === 'US' ? usOpportunities : indianOpportunities;

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-20">
      
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl md:text-5xl font-bold tracking-tight mb-2 flex items-center gap-3">
            <Globe className="w-10 h-10 text-theme_blue" />
            Macro Dashboard
          </h1>
          <p className="text-muted-foreground text-lg">Real-time macro conditions & live Multi-Agent scanner feed.</p>
        </div>
        <div className="flex items-center gap-3 self-start sm:self-auto">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-theme_green/10 border border-theme_green/30 rounded-xl text-xs font-bold text-theme_green">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-theme_green opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-theme_green"></span>
            </span>
            LIVE SCANNING ACTIVE
          </div>
          <button onClick={fetchAll} className="flex items-center justify-center p-2.5 bg-card border border-border rounded-xl hover:bg-border/50 transition-colors">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Grid of 4 Macro Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* DXY */}
        <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} className="bg-card border border-border rounded-3xl p-6 relative overflow-hidden">
          <div className="absolute top-0 right-0 p-4 opacity-5">
            <DollarSign className="w-24 h-24" />
          </div>
          <div className="flex justify-between items-start mb-4 relative z-10">
            <h3 className="font-display font-bold text-muted-foreground text-sm uppercase tracking-wider">US Dollar Index (DXY)</h3>
            <div className={`p-2 rounded-xl ${activeData.dxy.change >= 0 ? 'bg-theme_green/10 text-theme_green' : 'bg-theme_red/10 text-theme_red'}`}>
              {activeData.dxy.change >= 0 ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
            </div>
          </div>
          <div className="relative z-10">
            <div className="text-4xl font-display font-bold mb-1">{activeData.dxy.price.toFixed(2)}</div>
            <div className={`text-sm font-medium ${activeData.dxy.change >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
              {activeData.dxy.change > 0 ? '+' : ''}{activeData.dxy.change.toFixed(2)}%
            </div>
          </div>
        </motion.div>

        {/* VIX */}
        <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }} className="bg-card border border-border rounded-3xl p-6 relative overflow-hidden">
          <div className="absolute top-0 right-0 p-4 opacity-5">
            <Activity className="w-24 h-24" />
          </div>
          <div className="flex justify-between items-start mb-4 relative z-10">
            <h3 className="font-display font-bold text-muted-foreground text-sm uppercase tracking-wider">CBOE Volatility (VIX)</h3>
            <div className={`p-2 rounded-xl ${activeData.vix.change >= 0 ? 'bg-theme_red/10 text-theme_red' : 'bg-theme_green/10 text-theme_green'}`}>
              {activeData.vix.change >= 0 ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
            </div>
          </div>
          <div className="relative z-10">
            <div className="text-4xl font-display font-bold mb-1">{activeData.vix.price.toFixed(2)}</div>
            <div className={`text-sm font-medium ${activeData.vix.change >= 0 ? 'text-theme_red' : 'text-theme_green'}`}>
              {activeData.vix.change > 0 ? '+' : ''}{activeData.vix.change.toFixed(2)}%
            </div>
          </div>
        </motion.div>

        {/* Real Yields */}
        <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="bg-card border border-border rounded-3xl p-6 relative overflow-hidden">
          <div className="absolute top-0 right-0 p-4 opacity-5">
            <Percent className="w-24 h-24" />
          </div>
          <div className="flex justify-between items-start mb-4 relative z-10">
            <h3 className="font-display font-bold text-muted-foreground text-sm uppercase tracking-wider">10Y TIPS Yield</h3>
            <div className={`p-2 rounded-xl ${activeData.tips10y.change >= 0 ? 'bg-theme_red/10 text-theme_red' : 'bg-theme_green/10 text-theme_green'}`}>
              {activeData.tips10y.change >= 0 ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
            </div>
          </div>
          <div className="relative z-10">
            <div className="text-4xl font-display font-bold mb-1">{activeData.tips10y.price.toFixed(2)}%</div>
            <div className={`text-sm font-medium ${activeData.tips10y.change >= 0 ? 'text-theme_red' : 'text-theme_green'}`}>
              {activeData.tips10y.change > 0 ? '+' : ''}{activeData.tips10y.change.toFixed(1)} bps (5d)
            </div>
          </div>
        </motion.div>

        {/* Global Events */}
        <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }} className="bg-card border border-border rounded-3xl p-6 relative overflow-hidden">
          <div className="absolute top-0 right-0 p-4 opacity-5">
            <Lock className="w-24 h-24" />
          </div>
          <div className="flex justify-between items-start mb-4 relative z-10">
            <h3 className="font-display font-bold text-muted-foreground text-sm uppercase tracking-wider">Liquidity Windows</h3>
            <div className="p-2 rounded-xl bg-theme_blue/10 text-theme_blue">
              <Lock className="w-5 h-5" />
            </div>
          </div>
          <div className="relative z-10 space-y-2 mt-4">
            <div className="flex justify-between items-center text-sm font-medium">
              <span className="text-muted-foreground">London Fix Window</span>
              <span className={`px-2 py-0.5 rounded text-xs font-bold ${activeData.london_fix ? "bg-theme_yellow/20 text-theme_yellow" : "bg-theme_green/20 text-theme_green"}`}>
                {activeData.london_fix ? "ACTIVE" : "CLEAR"}
              </span>
            </div>
            <div className="flex justify-between items-center text-sm font-medium">
              <span className="text-muted-foreground">Rollover Week (NQ)</span>
              <span className={`px-2 py-0.5 rounded text-xs font-bold ${activeData.rollover_week ? "bg-theme_red/20 text-theme_red" : "bg-theme_green/20 text-theme_green"}`}>
                {activeData.rollover_week ? "ACTIVE" : "CLEAR"}
              </span>
            </div>
          </div>
        </motion.div>
      </div>

      {/* COT Positioning Section */}
      <h2 className="font-display text-2xl font-bold tracking-tight mt-12 mb-6">CFTC Commitment of Traders (COT)</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} className="bg-card border border-border rounded-3xl p-8">
           <div className="flex justify-between items-center mb-6">
             <h3 className="text-xl font-display font-bold">Gold (MGC=F) Positioning</h3>
             <span className={`px-3 py-1 rounded-full text-xs font-bold ${activeData.gold_cot.positioning.includes('BULL') ? 'bg-theme_green/20 text-theme_green' : 'bg-theme_red/20 text-theme_red'}`}>
               {activeData.gold_cot.positioning}
             </span>
           </div>
           <div className="flex flex-col gap-2">
             <span className="text-muted-foreground text-sm">Managed Money Net Position</span>
             <span className="text-3xl font-display font-bold">
                {activeData.gold_cot.net_longs > 0 ? '+' : ''}{activeData.gold_cot.net_longs.toLocaleString()} contracts
             </span>
           </div>
        </motion.div>
        
        <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="bg-card border border-border rounded-3xl p-8">
           <div className="flex justify-between items-center mb-6">
             <h3 className="text-xl font-display font-bold">Nasdaq 100 (MNQ=F) Positioning</h3>
             <span className={`px-3 py-1 rounded-full text-xs font-bold ${activeData.nq_cot.positioning.includes('BULL') ? 'bg-theme_green/20 text-theme_green' : 'bg-theme_red/20 text-theme_red'}`}>
               {activeData.nq_cot.positioning}
             </span>
           </div>
           <div className="flex flex-col gap-2">
             <span className="text-muted-foreground text-sm">Leveraged Funds Net Position</span>
             <span className="text-3xl font-display font-bold">
                {activeData.nq_cot.net_longs > 0 ? '+' : ''}{activeData.nq_cot.net_longs.toLocaleString()} contracts
             </span>
           </div>
        </motion.div>
      </div>

      {/* Live Scanner Opportunities Feed */}
      <div className="flex items-center justify-between mt-12 mb-6">
        <h2 className="font-display text-2xl font-bold tracking-tight">Live Scanner Opportunity Feed</h2>
        <div className="flex bg-muted p-1 rounded-xl">
          <button
            onClick={() => setActiveTab('US')}
            className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${activeTab === 'US' ? 'bg-card shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
          >
            🇺🇸 US Futures
          </button>
          <button
            onClick={() => setActiveTab('INDIA')}
            className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${activeTab === 'INDIA' ? 'bg-card shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
          >
            🇮🇳 Indian Stocks
          </button>
        </div>
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -15 }}
          transition={{ duration: 0.15 }}
        >
          {oppList.length === 0 ? (
            <div className="bg-card border border-border rounded-3xl p-12 text-center text-muted-foreground flex flex-col items-center justify-center gap-4">
              <Cpu className="w-12 h-12 opacity-30 animate-pulse" />
              <div>
                <p className="font-bold">Scanning market instruments...</p>
                <p className="text-sm opacity-60 mt-1">Opportunities appear here as soon as the agents generate high-confidence signals.</p>
              </div>
            </div>
          ) : (
            <div className="grid gap-4">
              {oppList.map((opp, idx) => (
                <div key={idx} className="bg-card border border-border rounded-2xl p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 hover:border-theme_blue/30 transition-colors">
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-xl bg-background border border-border flex items-center justify-center font-bold text-sm text-theme_blue">
                      {opp.symbol}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-lg">{opp.symbol}</span>
                        <span className="text-muted-foreground text-sm font-mono">
                          {activeTab === 'INDIA' ? '₹' : '$'}
                          {opp.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </span>
                      </div>
                      <p className="text-sm text-muted-foreground mt-0.5 line-clamp-1" title={opp.reason}>{opp.reason}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-6 self-end md:self-auto">
                    <div className="text-right hidden sm:block">
                      <span className="text-xs text-muted-foreground">Consensus Confidence</span>
                      <div className="flex items-center gap-2 mt-1">
                        <div className="w-24 bg-background rounded-full h-1.5 overflow-hidden border border-border">
                          <div className="h-1.5 rounded-full bg-theme_blue" style={{ width: `${opp.confidence}%` }} />
                        </div>
                        <span className="text-sm font-bold font-mono">{opp.confidence}%</span>
                      </div>
                    </div>
                    <div>
                      <span className={`px-4 py-2 rounded-xl text-xs font-bold tracking-wider inline-block text-center min-w-[80px] ${
                        opp.signal === 'BUY' ? 'bg-theme_green/20 text-theme_green' :
                        opp.signal === 'SELL' ? 'bg-theme_red/20 text-theme_red' :
                        'bg-theme_yellow/20 text-theme_yellow'
                      }`}>
                        {opp.signal}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
};
