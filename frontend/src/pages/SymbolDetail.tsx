import { useState, useEffect, useCallback } from 'react';
import { useParams, Link, useOutletContext } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowLeft, TrendingUp, TrendingDown, Info, AlertTriangle } from 'lucide-react';
import TradingViewWidget from '../components/TradingViewWidget';
import { TradeModal } from '../components/TradeModal';
import { API_BASE } from '../config';

interface ShellContext {
  isBeginnerMode: boolean;
}

interface LiveTick {
  symbol: string;
  price: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  vwap: number;
  rsi_14: number;
  atr_14: number;
  macd_hist: number;
  institutional_flow: string;
  daily_change_pct: number;
  data_source: string;
  is_stale_data: boolean;
  data_age_seconds: number;
}

// IV&V finding 2026-08-21 (audit Finding #10): this page previously showed
// entirely fabricated numbers — a hardcoded $189.45 price, a hardcoded
// "BUY, 88% confidence" AI recommendation, hardcoded SMC order-block/FVG
// levels, a hardcoded RSI of 58.4 and a "Bullish Cross" MACD, and a
// hardcoded $191.20 price target — none of it computed from the real
// `ticker`. It looked identical for every symbol. Fixed to fetch the real
// `/data/live/{symbol}` endpoint (real Yahoo Finance OHLCV → real RSI-14,
// MACD histogram, VWAP, daily change), and honestly show "Not available"
// for the sections that have no real backing (per-symbol SMC/AI-prediction
// analysis is only ever produced by the live committee for symbols inside
// an active market loop, not for an arbitrary ad-hoc URL lookup) instead of
// inventing plausible-looking numbers.
export const SymbolDetail = () => {
  const { ticker } = useParams<{ ticker: string }>();
  const { isBeginnerMode } = useOutletContext<ShellContext>();
  const [tick, setTick] = useState<LiveTick | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isTradeModalOpen, setTradeModalOpen] = useState(false);

  const fetchTick = useCallback(async () => {
    if (!ticker) return;
    try {
      const res = await fetch(`${API_BASE}/data/live/${encodeURIComponent(ticker.toUpperCase())}`);
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      if (data?.error) throw new Error(data.error);
      setTick(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Market data unavailable for this symbol.');
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  useEffect(() => {
    setLoading(true);
    fetchTick();
    const interval = setInterval(fetchTick, 15000);
    return () => clearInterval(interval);
  }, [fetchTick]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center h-[60vh]">
        <div className="w-12 h-12 border-4 border-theme_blue/20 border-t-theme_blue rounded-full animate-spin"></div>
      </div>
    );
  }

  const isUp = (tick?.daily_change_pct ?? 0) >= 0;

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-20">

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-border pb-6">
        <div>
          <Link to="/watchlist" className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground mb-4 transition-colors">
            <ArrowLeft className="w-4 h-4" /> Back to Watchlist
          </Link>
          <div className="flex items-center gap-4">
            <h1 className="font-display text-4xl md:text-5xl font-bold tracking-tight">{ticker}</h1>
          </div>
          {tick ? (
            <div className="flex flex-col mt-2">
              <div className="flex items-baseline gap-3">
                <span className="text-3xl font-bold">${tick.price.toFixed(2)}</span>
                <span className={`font-medium flex items-center ${isUp ? 'text-theme_green' : 'text-theme_red'}`}>
                  {isUp ? <TrendingUp className="w-4 h-4 mr-1" /> : <TrendingDown className="w-4 h-4 mr-1" />}
                  {isUp ? '+' : ''}{tick.daily_change_pct.toFixed(2)}%
                </span>
              </div>
              <span className={`text-xs mt-1 ${tick.is_stale_data ? 'text-theme_yellow' : 'text-muted-foreground'}`}>
                {tick.is_stale_data
                  ? `⚠ Stale data — ${tick.data_age_seconds.toFixed(0)}s old`
                  : tick.data_source}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 mt-3 text-theme_red text-sm">
              <AlertTriangle className="w-4 h-4" />
              {error || 'Market data unavailable.'}
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          <div className={`px-4 py-2 rounded-xl flex items-center gap-2 border ${isBeginnerMode ? 'bg-theme_blue/10 border-theme_blue/20 text-theme_blue' : 'bg-card border-border text-foreground'}`}>
            <Info className="w-4 h-4" />
            <span className="text-sm font-bold">{isBeginnerMode ? 'Beginner Mode Active' : 'Pro Mode Active'}</span>
          </div>
          <button
            onClick={() => setTradeModalOpen(true)}
            disabled={!tick}
            className="bg-theme_blue text-white px-8 py-3 rounded-xl font-bold hover:bg-theme_blue/90 transition-colors shadow-lg hover:shadow-theme_blue/20 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Trade {ticker}
          </button>
        </div>
      </div>

      {isBeginnerMode ? (
        // ==========================================
        // BEGINNER MODE UI (Simplified, Apple-like)
        // ==========================================
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
          <div className="grid md:grid-cols-3 gap-6">

            <div className="md:col-span-1 bg-card border border-border rounded-3xl p-6">
              <h3 className="font-display text-lg font-bold mb-4">Not Available</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">
                AI trade recommendations are generated live by the trading committee for symbols
                inside an active market loop. Ad-hoc symbol lookups like this one don't run the
                committee, so there is no real recommendation to show — showing one anyway would
                be fabricated.
              </p>
            </div>

            {/* Simple Chart */}
            <div className="md:col-span-2 bg-card border border-border rounded-3xl p-6">
               <div className="flex justify-between items-center mb-4">
                 <h3 className="font-display font-bold">Price History (1 Month)</h3>
               </div>
               <div className="h-[300px] rounded-xl overflow-hidden pointer-events-none">
                 <TradingViewWidget symbol={ticker || 'AAPL'} />
               </div>
            </div>

          </div>

          <div className="bg-card border border-border rounded-3xl p-6">
            <h3 className="font-display font-bold mb-4">Live Market Data</h3>
            {tick ? (
              <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-4 bg-background border border-border rounded-2xl">
                  <div className="text-xs text-muted-foreground mb-1">Day's Range</div>
                  <div className="font-bold text-lg">${tick.low.toFixed(2)} – ${tick.high.toFixed(2)}</div>
                </div>
                <div className="p-4 bg-background border border-border rounded-2xl">
                  <div className="text-xs text-muted-foreground mb-1">Volume</div>
                  <div className="font-bold text-lg">{tick.volume.toLocaleString()}</div>
                </div>
                <div className="p-4 bg-background border border-border rounded-2xl">
                  <div className="text-xs text-muted-foreground mb-1">VWAP</div>
                  <div className="font-bold text-lg">${tick.vwap.toFixed(2)}</div>
                </div>
                <div className="p-4 bg-background border border-border rounded-2xl">
                  <div className="text-xs text-muted-foreground mb-1">Institutional Flow</div>
                  <div className={`font-bold text-lg ${tick.institutional_flow === 'BULLISH' ? 'text-theme_green' : tick.institutional_flow === 'BEARISH' ? 'text-theme_red' : ''}`}>
                    {tick.institutional_flow}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">{error || 'No live data available.'}</div>
            )}
          </div>
        </motion.div>

      ) : (
        // ==========================================
        // PRO MODE UI (Bloomberg/TradingView-like)
        // ==========================================
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
          <div className="grid xl:grid-cols-4 gap-6">

            {/* Advanced Chart */}
            <div className="xl:col-span-3 bg-card border border-border rounded-3xl overflow-hidden h-[600px] flex flex-col">
              <div className="flex-1 w-full">
                <TradingViewWidget symbol={ticker || 'AAPL'} />
              </div>
            </div>

            {/* Real technical indicators + honest gaps */}
            <div className="xl:col-span-1 space-y-6">

              <div className="bg-card border border-border rounded-3xl p-5">
                <h3 className="font-display font-bold text-sm uppercase tracking-wider text-muted-foreground mb-4">Technical Indicators</h3>
                {tick ? (
                  <div className="space-y-4">
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="font-medium">RSI (14)</span>
                        <span className={`font-bold ${tick.rsi_14 >= 70 ? 'text-theme_red' : tick.rsi_14 <= 30 ? 'text-theme_green' : 'text-theme_yellow'}`}>
                          {tick.rsi_14.toFixed(1)} {tick.rsi_14 >= 70 ? '(Overbought)' : tick.rsi_14 <= 30 ? '(Oversold)' : '(Neutral)'}
                        </span>
                      </div>
                      <div className="w-full bg-background rounded-full h-1.5">
                        <div className="bg-theme_yellow h-1.5 rounded-full" style={{ width: `${Math.min(100, Math.max(0, tick.rsi_14))}%` }}></div>
                      </div>
                    </div>
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="font-medium">MACD Histogram</span>
                        <span className={`font-bold ${tick.macd_hist >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
                          {tick.macd_hist >= 0 ? 'Bullish' : 'Bearish'} ({tick.macd_hist.toFixed(4)})
                        </span>
                      </div>
                    </div>
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="font-medium">ATR (14)</span>
                        <span className="font-bold text-foreground">${tick.atr_14.toFixed(4)}</span>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">{error || 'No live data available.'}</div>
                )}
              </div>

              <div className="bg-card border border-border rounded-3xl p-5">
                <h3 className="font-display font-bold text-sm uppercase tracking-wider text-muted-foreground mb-4">Smart Money Concepts</h3>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Not available for ad-hoc symbol lookups. Order-block, FVG, and liquidity-sweep
                  analysis is only computed for symbols inside an active market loop's SMC engine.
                </p>
              </div>

              <div className="bg-card border border-border rounded-3xl p-5">
                <h3 className="font-display font-bold text-sm uppercase tracking-wider text-muted-foreground mb-4">AI Prediction Engine</h3>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Not available for ad-hoc symbol lookups. Price targets and win-probability
                  estimates are only produced by the live trading committee for symbols inside an
                  active market loop — showing a number here would be fabricated.
                </p>
              </div>

            </div>

          </div>
        </motion.div>
      )}

      <TradeModal
        isOpen={isTradeModalOpen}
        onClose={() => setTradeModalOpen(false)}
        symbol={ticker || 'AAPL'}
        price={tick?.price ?? 0}
      />
    </div>
  );
};
