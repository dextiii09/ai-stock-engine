import { useState, useEffect } from 'react';
import { ArrowLeftRight, AlertCircle, RefreshCw } from 'lucide-react';
import { AreaChart, Area, ResponsiveContainer } from 'recharts';
import { API_BASE } from '../config';

// Sine wave spark chart — illustrates the correlation direction visually
const buildSparkData = (correlation: number) =>
  Array.from({ length: 30 }, (_, i) => ({
    i,
    a: Math.sin(i * 0.4) * 50,
    b: Math.sin(i * 0.4 + (correlation < 0 ? Math.PI : 0)) * 40,
  }));

export const Watchlist = () => {
  const [correlationData, setCorrelationData] = useState({
    gold_nq: -0.85,
    gold_dxy: -0.92,
    nq_dxy: -0.61,
  });
  const [loading, setLoading] = useState(true);
  const [isFallback, setIsFallback] = useState(false);
  const [gateStatus, setGateStatus] = useState<any>(null);
  const [sampleDays, setSampleDays] = useState(0);

  const fetchData = async () => {
    try {
      const [corrRes, gatesRes] = await Promise.all([
        fetch(`${API_BASE}/analytics/correlation`),
        fetch(`${API_BASE}/analytics/gates`),
      ]);
      if (corrRes.ok) {
        const d = await corrRes.json();
        setCorrelationData({ gold_nq: d.gold_nq, gold_dxy: d.gold_dxy, nq_dxy: d.nq_dxy });
        setIsFallback(!!d.fallback);
        setSampleDays(d.sample_days || 0);
      }
      if (gatesRes.ok) setGateStatus(await gatesRes.json());
    } catch { /* backend offline */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60_000); // refresh every minute
    return () => clearInterval(interval);
  }, []);

  const getCorrelationColor = (val: number) => {
    if (val < -0.7) return 'text-theme_green'; // Strong inverse is good for hedging
    if (val > 0.7) return 'text-theme_red'; // Strong positive means same risk
    return 'text-theme_yellow'; // Choppy
  };

  const getCorrelationBg = (val: number) => {
    if (val < -0.7) return 'bg-theme_green/10';
    if (val > 0.7) return 'bg-theme_red/10';
    return 'bg-theme_yellow/10';
  };

  return (
    <div className="max-w-6xl mx-auto space-y-8 pb-12">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-tight mb-2">Correlation Monitor</h1>
          <p className="text-muted-foreground">
            {loading ? 'Loading live data…' : isFallback ? 'Live data unavailable — showing estimates.' : `Live 30-day rolling Pearson correlations · ${sampleDays} trading days`}
          </p>
        </div>
        <button onClick={fetchData} className="flex items-center gap-2 px-4 py-2 bg-card border border-border rounded-xl text-sm font-medium hover:bg-border/50 transition-colors">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* GC vs NQ */}
        {/* GC vs NQ */}
        {[
          { keyA: 'GC', keyB: 'NQ', colorA: 'text-theme_yellow', bgA: 'bg-theme_yellow/20', colorB: 'text-theme_blue', bgB: 'bg-theme_blue/20', strokeA: '#f59e0b', strokeB: '#3b82f6', title: 'Gold vs Nasdaq', corrKey: 'gold_nq' as const,
            description: (v: number) => v < -0.7 ? 'Strong inverse correlation. Ideal for Master AI hedging.' : v > 0.4 ? 'Positive correlation! AI will reduce simultaneous exposure.' : 'Neutral — correlation breaking down. AI monitoring.' },
          { keyA: 'GC', keyB: 'DXY', colorA: 'text-theme_yellow', bgA: 'bg-theme_yellow/20', colorB: 'text-theme_green', bgB: 'bg-theme_green/20', strokeA: '#f59e0b', strokeB: '#10b981', title: 'Gold vs Dollar', corrKey: 'gold_dxy' as const,
            description: (v: number) => v < -0.7 ? 'Standard macro regime. DXY driving Gold flow.' : 'Macro divergence detected. Fundamental AI confidence reduced.' },
          { keyA: 'NQ', keyB: 'DXY', colorA: 'text-theme_blue', bgA: 'bg-theme_blue/20', colorB: 'text-theme_green', bgB: 'bg-theme_green/20', strokeA: '#3b82f6', strokeB: '#10b981', title: 'Nasdaq vs Dollar', corrKey: 'nq_dxy' as const,
            description: (v: number) => v < -0.5 ? 'Risk-on regime. Dollar weakness supporting equity rally.' : 'Unusual correlation. Dollar and Nasdaq moving together — caution.' },
        ].map((pair, idx) => {
          const corrVal = correlationData[pair.corrKey];
          const sparkData = buildSparkData(corrVal);
          return (
          <div key={idx} className="bg-card border border-border rounded-3xl p-6">
             <div className="flex justify-between items-center mb-6">
               <div className="flex items-center gap-3">
                 <div className="flex -space-x-2">
                   <div className={`w-10 h-10 rounded-full ${pair.bgA} flex items-center justify-center ${pair.colorA} font-bold text-xs border-2 border-card z-10`}>{pair.keyA}</div>
                   <div className={`w-10 h-10 rounded-full ${pair.bgB} flex items-center justify-center ${pair.colorB} font-bold text-xs border-2 border-card`}>{pair.keyB}</div>
                 </div>
                 <ArrowLeftRight className="w-5 h-5 text-muted-foreground" />
               </div>
               <div className={`px-4 py-2 rounded-xl font-bold font-display text-xl ${getCorrelationBg(corrVal)} ${getCorrelationColor(corrVal)}`}>
                 {corrVal.toFixed(3)}
               </div>
             </div>
             <div className="space-y-2 mb-6">
               <h4 className="font-bold text-lg">{pair.title}</h4>
               <p className="text-sm text-muted-foreground">{pair.description(corrVal)}</p>
             </div>
             <div className="h-28 -mx-2">
               <ResponsiveContainer width="100%" height="100%">
                 <AreaChart data={sparkData}>
                   <defs>
                     <linearGradient id={`grad_a_${idx}`} x1="0" y1="0" x2="0" y2="1">
                       <stop offset="5%" stopColor={pair.strokeA} stopOpacity={0.3}/>
                       <stop offset="95%" stopColor={pair.strokeA} stopOpacity={0}/>
                     </linearGradient>
                     <linearGradient id={`grad_b_${idx}`} x1="0" y1="0" x2="0" y2="1">
                       <stop offset="5%" stopColor={pair.strokeB} stopOpacity={0.2}/>
                       <stop offset="95%" stopColor={pair.strokeB} stopOpacity={0}/>
                     </linearGradient>
                   </defs>
                   <Area type="monotone" dataKey="a" stroke={pair.strokeA} fillOpacity={1} fill={`url(#grad_a_${idx})`} dot={false} />
                   <Area type="monotone" dataKey="b" stroke={pair.strokeB} fillOpacity={1} fill={`url(#grad_b_${idx})`} dot={false} />
                 </AreaChart>
               </ResponsiveContainer>
             </div>
          </div>
          );
        })}
      </div>

      {/* Live Master AI Gate Status */}
      <div className="bg-card border border-border rounded-3xl p-8 mt-8">
        <h3 className="font-display text-2xl font-bold mb-6 flex items-center gap-2">
          <AlertCircle className="w-6 h-6 text-theme_blue" />
          Master AI Gate Status
        </h3>
        <div className="grid sm:grid-cols-2 gap-4">
          {gateStatus ? Object.entries(gateStatus).map(([key, gate]: [string, any]) => (
            <div key={key} className={`bg-background rounded-2xl p-5 border ${gate.status === 'PASSED' ? 'border-theme_green/30' : gate.status === 'BLOCKED' ? 'border-theme_red/30' : 'border-border'}`}>
              <div className="flex items-center gap-3 mb-2">
                <div className={`w-2.5 h-2.5 rounded-full ${gate.status === 'PASSED' ? 'bg-theme_green animate-pulse' : gate.status === 'BLOCKED' ? 'bg-theme_red' : 'bg-muted-foreground'}`} />
                <span className="font-bold text-sm capitalize">{key.replace(/_/g, ' ')}</span>
                <span className={`ml-auto text-xs font-bold px-2 py-0.5 rounded ${gate.status === 'PASSED' ? 'bg-theme_green/10 text-theme_green' : gate.status === 'BLOCKED' ? 'bg-theme_red/10 text-theme_red' : 'bg-muted/20 text-muted-foreground'}`}>{gate.status}</span>
              </div>
              <p className="text-xs text-muted-foreground">{gate.details}</p>
            </div>
          )) : (
            <div className="bg-background rounded-2xl p-5 border border-border sm:col-span-2">
              <div className="flex items-center gap-3 mb-2">
                <div className={`w-2.5 h-2.5 rounded-full ${correlationData.gold_nq < -0.4 ? 'bg-theme_green animate-pulse' : 'bg-theme_red'}`} />
                <span className="font-bold text-sm">Cross-Asset Hedging Gate: {correlationData.gold_nq < -0.4 ? 'OPEN' : 'CLOSED'}</span>
              </div>
              <p className="text-xs text-muted-foreground">
                {correlationData.gold_nq < -0.4
                  ? 'Gold and Nasdaq inversely correlated. Master AI permitted to hold concurrent hedged positions.'
                  : 'Gold and Nasdaq positively correlated. Master AI will veto new directional exposure.'}
              </p>
            </div>
          )}
        </div>
      </div>

    </div>
  );
};
