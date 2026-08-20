import { useState, useEffect } from 'react';
import { useParams, Link, useOutletContext } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowLeft, TrendingUp, Activity, Info, Lock } from 'lucide-react';
import TradingViewWidget from '../components/TradingViewWidget';
import { TradeModal } from '../components/TradeModal';

interface ShellContext {
  isBeginnerMode: boolean;
}

export const SymbolDetail = () => {
  const { ticker } = useParams<{ ticker: string }>();
  const { isBeginnerMode } = useOutletContext<ShellContext>();
  const [loading, setLoading] = useState(true);
  const [isTradeModalOpen, setTradeModalOpen] = useState(false);

  // Mock data simulation
  useEffect(() => {
    const timer = setTimeout(() => setLoading(false), 800);
    return () => clearTimeout(timer);
  }, [ticker]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center h-[60vh]">
        <div className="w-12 h-12 border-4 border-theme_blue/20 border-t-theme_blue rounded-full animate-spin"></div>
      </div>
    );
  }

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
            <span className="px-3 py-1 bg-card border border-border rounded-lg text-sm font-medium text-muted-foreground">NASDAQ</span>
          </div>
          <div className="flex flex-col mt-2">
            <div className="flex items-baseline gap-3">
              <span className="text-3xl font-bold">$189.45</span>
              <span className="text-theme_green font-medium flex items-center">
                <TrendingUp className="w-4 h-4 mr-1" /> +1.24 (0.65%)
              </span>
            </div>
            <span className="text-xs text-muted-foreground mt-1">Market Open • Data delayed by 15 mins</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className={`px-4 py-2 rounded-xl flex items-center gap-2 border ${isBeginnerMode ? 'bg-theme_blue/10 border-theme_blue/20 text-theme_blue' : 'bg-card border-border text-foreground'}`}>
            <Info className="w-4 h-4" />
            <span className="text-sm font-bold">{isBeginnerMode ? 'Beginner Mode Active' : 'Pro Mode Active'}</span>
          </div>
          <button onClick={() => setTradeModalOpen(true)} className="bg-theme_blue text-white px-8 py-3 rounded-xl font-bold hover:bg-theme_blue/90 transition-colors shadow-lg hover:shadow-theme_blue/20">
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
            
            {/* Simple AI Summary */}
            <div className="md:col-span-1 bg-gradient-to-br from-theme_blue/10 to-transparent border border-theme_blue/20 rounded-3xl p-6">
              <h3 className="font-display text-lg font-bold mb-4 flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-theme_blue animate-pulse"></div>
                AI Recommendation
              </h3>
              <div className="text-4xl font-display font-bold text-theme_green mb-2">BUY</div>
              <p className="text-sm text-foreground/80 leading-relaxed mb-4">
                The AI models indicate a strong upward trend for <strong>{ticker}</strong> over the next 7 days, driven by positive earnings sentiment and high institutional buying.
              </p>
              <div className="bg-background rounded-xl p-3 flex justify-between items-center text-sm border border-border">
                <span className="text-muted-foreground">Confidence Score</span>
                <span className="font-bold text-theme_blue">88%</span>
              </div>
            </div>

            {/* Simple Chart */}
            <div className="md:col-span-2 bg-card border border-border rounded-3xl p-6">
               <div className="flex justify-between items-center mb-4">
                 <h3 className="font-display font-bold">Price History (1 Month)</h3>
               </div>
               <div className="h-[300px] rounded-xl overflow-hidden pointer-events-none">
                 {/* Re-use TradingView widget but in a basic line mode (mocking simple UI here) */}
                 <TradingViewWidget symbol={ticker || 'AAPL'} />
               </div>
            </div>
            
          </div>
          
          <div className="bg-card border border-border rounded-3xl p-6">
            <h3 className="font-display font-bold mb-4">What you need to know</h3>
            <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-4 bg-background border border-border rounded-2xl">
                <div className="text-xs text-muted-foreground mb-1">Company Size (Market Cap)</div>
                <div className="font-bold text-lg">Massive</div>
              </div>
              <div className="p-4 bg-background border border-border rounded-2xl">
                <div className="text-xs text-muted-foreground mb-1">Risk Level</div>
                <div className="font-bold text-lg text-theme_green">Low Risk</div>
              </div>
              <div className="p-4 bg-background border border-border rounded-2xl">
                <div className="text-xs text-muted-foreground mb-1">Dividend Yield</div>
                <div className="font-bold text-lg">0.53% (Pays cash)</div>
              </div>
              <div className="p-4 bg-background border border-border rounded-2xl">
                <div className="text-xs text-muted-foreground mb-1">News Sentiment</div>
                <div className="font-bold text-lg text-theme_green flex items-center gap-1"><TrendingUp className="w-4 h-4" /> Positive</div>
              </div>
            </div>
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
              <div className="p-4 border-b border-border flex justify-between items-center bg-background/50">
                <div className="flex gap-2 text-xs font-medium">
                  <button className="px-3 py-1.5 bg-card border border-border rounded-md hover:bg-theme_blue hover:text-white hover:border-theme_blue transition-colors">1m</button>
                  <button className="px-3 py-1.5 bg-card border border-border rounded-md hover:bg-theme_blue hover:text-white hover:border-theme_blue transition-colors">5m</button>
                  <button className="px-3 py-1.5 bg-card border border-border rounded-md hover:bg-theme_blue hover:text-white hover:border-theme_blue transition-colors">15m</button>
                  <button className="px-3 py-1.5 bg-theme_blue text-white border-theme_blue rounded-md">1H</button>
                  <button className="px-3 py-1.5 bg-card border border-border rounded-md hover:bg-theme_blue hover:text-white hover:border-theme_blue transition-colors">4H</button>
                  <button className="px-3 py-1.5 bg-card border border-border rounded-md hover:bg-theme_blue hover:text-white hover:border-theme_blue transition-colors">D</button>
                </div>
                <div className="flex gap-2">
                  <button className="px-3 py-1.5 text-xs font-medium bg-card border border-border rounded-md flex items-center gap-1"><Activity className="w-3 h-3" /> Indicators</button>
                </div>
              </div>
              <div className="flex-1 w-full">
                <TradingViewWidget symbol={ticker || 'AAPL'} />
              </div>
            </div>

            {/* Smart Money Concepts & Order Book */}
            <div className="xl:col-span-1 space-y-6">
              
              <div className="bg-card border border-border rounded-3xl p-5">
                <h3 className="font-display font-bold text-sm uppercase tracking-wider text-muted-foreground mb-4">SMC Analysis</h3>
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-medium">Market Structure</span>
                    <span className="text-sm font-bold text-theme_green">Bullish CHoCH</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-medium">Order Block (Bullish)</span>
                    <span className="text-sm font-bold text-foreground">$184.50 - $185.10</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-medium">Fair Value Gap</span>
                    <span className="text-sm font-bold text-foreground">$186.20 - $187.00</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-medium">Liquidity Sweep</span>
                    <span className="text-sm font-bold text-theme_blue">Confirmed (Sell-side)</span>
                  </div>
                </div>
              </div>

              <div className="bg-card border border-border rounded-3xl p-5">
                <h3 className="font-display font-bold text-sm uppercase tracking-wider text-muted-foreground mb-4">Technical Indicators</h3>
                <div className="space-y-4">
                  <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="font-medium">RSI (14)</span>
                      <span className="font-bold text-theme_yellow">58.4 (Neutral)</span>
                    </div>
                    <div className="w-full bg-background rounded-full h-1.5"><div className="bg-theme_yellow h-1.5 rounded-full" style={{ width: '58.4%' }}></div></div>
                  </div>
                  <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="font-medium">MACD (12, 26)</span>
                      <span className="font-bold text-theme_green">Bullish Cross</span>
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="font-medium">Volume Profile</span>
                      <span className="font-bold text-foreground">POC @ $185.30</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-card border border-border rounded-3xl p-5">
                <h3 className="font-display font-bold text-sm uppercase tracking-wider text-muted-foreground mb-4 flex items-center justify-between">
                  AI Prediction Engine <Lock className="w-3 h-3 text-theme_blue" />
                </h3>
                <div className="p-3 bg-theme_blue/5 border border-theme_blue/20 rounded-xl space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Next 4H Target</span>
                    <span className="font-bold text-theme_green">$191.20</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Stop Loss Idea</span>
                    <span className="font-bold text-theme_red">$183.50</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Win Prob (XGBoost)</span>
                    <span className="font-bold text-theme_blue">76.4%</span>
                  </div>
                </div>
              </div>

            </div>

          </div>
        </motion.div>
      )}

      <TradeModal 
        isOpen={isTradeModalOpen} 
        onClose={() => setTradeModalOpen(false)} 
        symbol={ticker || 'AAPL'} 
        price={189.45} 
      />
    </div>
  );
};
