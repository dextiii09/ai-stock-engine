// ============================================================================
// SANDBOX TRADER - ISOLATION VERIFICATION:
// ----------------------------------------------------------------------------
// 1. All balance, holdings, and transaction state are managed completely
//    client-side in the browser via `localStorage` (SANDBOX_BALANCE_KEY, etc.).
// 2. Buys/Sells do NOT hit any stateful backend routes. The backend is only
//    queried for read-only live prices (/api/v1/data/live/{symbol}).
// 3. This page has zero side-effects on the live trading engine's database,
//    portfolio_state.json, or reinforcement learning engine weights (rl_state.json).
// ============================================================================

import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Zap, TrendingUp, TrendingDown, DollarSign, ShoppingCart, ArrowUpRight,
  ArrowDownRight, Activity, RefreshCw, Trophy, Flame, AlertTriangle,
  BarChart3, Clock, ChevronUp, ChevronDown
} from 'lucide-react';

import { API_BASE } from '../config';
const SANDBOX_BALANCE_KEY = 'sandbox_balance';
const SANDBOX_HOLDINGS_KEY = 'sandbox_holdings';
const SANDBOX_TRADES_KEY = 'sandbox_trades';

const INITIAL_BALANCE = 250000;

const SYMBOLS = ['MNQ=F', 'MGC=F'];
const SYMBOL_META: Record<string, { name: string; color: string; emoji: string; contractSize: number }> = {
  'MNQ=F': { name: 'Micro Nasdaq', color: '#3B82F6', emoji: '📈', contractSize: 2 },
  'MGC=F': { name: 'Micro Gold', color: '#F59E0B', emoji: '🥇', contractSize: 10 },
};

interface Trade {
  id: string;
  symbol: string;
  action: 'BUY' | 'SELL';
  shares: number;
  price: number;
  total: number;
  pnl?: number;
  timestamp: string;
}

interface Holding {
  symbol: string;
  shares: number;
  avgPrice: number;
  value: number;
}

export const SandboxTrader = () => {
  const [balance, setBalance] = useState<number>(() => {
    const saved = localStorage.getItem(SANDBOX_BALANCE_KEY);
    return saved ? Number(saved) : INITIAL_BALANCE;
  });
  const [holdings, setHoldings] = useState<Record<string, Holding>>(() => {
    const saved = localStorage.getItem(SANDBOX_HOLDINGS_KEY);
    return saved ? JSON.parse(saved) : {};
  });
  const [trades, setTrades] = useState<Trade[]>(() => {
    const saved = localStorage.getItem(SANDBOX_TRADES_KEY);
    return saved ? JSON.parse(saved) : [];
  });

  const [prices, setPrices] = useState<Record<string, number>>({});
  const [, setPrevPrices] = useState<Record<string, number>>({});
  const [, setPriceChanges] = useState<Record<string, number>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [quantities, setQuantities] = useState<Record<string, number>>({ 'MNQ=F': 1, 'MGC=F': 1 });
  const [flashPrices, setFlashPrices] = useState<Record<string, 'up' | 'down' | null>>({});
  const [latestAction, setLatestAction] = useState<{ symbol: string; action: string; pnl?: number } | null>(null);
  const [showConfetti, setShowConfetti] = useState(false);
  const confettiRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Persist state
  useEffect(() => {
    localStorage.setItem(SANDBOX_BALANCE_KEY, balance.toString());
    localStorage.setItem(SANDBOX_HOLDINGS_KEY, JSON.stringify(holdings));
    localStorage.setItem(SANDBOX_TRADES_KEY, JSON.stringify(trades));
  }, [balance, holdings, trades]);

  // Fetch live prices
  const fetchPrices = async () => {
    const newPrices: Record<string, number> = {};
    await Promise.all(
      SYMBOLS.map(async (sym) => {
        try {
          const res = await fetch(`${API_BASE}/data/live/${sym}`);
          if (res.ok) {
            const d = await res.json();
            newPrices[sym] = d.price ?? d.close ?? 0;
          }
        } catch { /* noop */ }
      })
    );
    setPrices(prev => {
      setPrevPrices(prev);
      const changes: Record<string, 'up' | 'down' | null> = {};
      SYMBOLS.forEach(sym => {
        if (prev[sym] && newPrices[sym]) {
          if (newPrices[sym] > prev[sym]) changes[sym] = 'up';
          else if (newPrices[sym] < prev[sym]) changes[sym] = 'down';
          else changes[sym] = null;
        }
      });
      setFlashPrices(changes);
      setTimeout(() => setFlashPrices({}), 1200);
      return newPrices;
    });
    // compute daily % change
    setPriceChanges(prev => {
      const updated = { ...prev };
      SYMBOLS.forEach(sym => {
        if (newPrices[sym] && prices[sym]) {
          const pct = ((newPrices[sym] - prices[sym]) / prices[sym]) * 100;
          updated[sym] = (updated[sym] ?? 0) + pct;
        }
      });
      return updated;
    });
    setIsLoading(false);
  };

  useEffect(() => {
    fetchPrices();
    const interval = setInterval(fetchPrices, 5000);
    return () => clearInterval(interval);
  }, []);

  const totalPortfolioValue = Object.values(holdings).reduce((sum, h) => {
    const livePrice = prices[h.symbol] ?? h.avgPrice;
    return sum + h.shares * livePrice;
  }, 0);

  const totalPnL = balance + totalPortfolioValue - INITIAL_BALANCE;
  const totalPnLPct = (totalPnL / INITIAL_BALANCE) * 100;

  const executeBuy = (symbol: string) => {
    const price = prices[symbol];
    if (!price) return;
    const qty = quantities[symbol] ?? 1;
    const total = price * qty;
    if (total > balance) {
      setLatestAction({ symbol, action: 'INSUFFICIENT_FUNDS' });
      setTimeout(() => setLatestAction(null), 3000);
      return;
    }

    const newBalance = balance - total;
    const existing = holdings[symbol];
    const newHolding: Holding = {
      symbol,
      shares: (existing?.shares ?? 0) + qty,
      avgPrice: existing
        ? (existing.avgPrice * existing.shares + price * qty) / (existing.shares + qty)
        : price,
      value: ((existing?.shares ?? 0) + qty) * price,
    };

    const trade: Trade = {
      id: Math.random().toString(36).slice(2),
      symbol,
      action: 'BUY',
      shares: qty,
      price,
      total,
      timestamp: new Date().toLocaleTimeString(),
    };

    setBalance(newBalance);
    setHoldings(prev => ({ ...prev, [symbol]: newHolding }));
    setTrades(prev => [trade, ...prev].slice(0, 50));
    setLatestAction({ symbol, action: 'BUY' });
    setTimeout(() => setLatestAction(null), 3000);
  };

  const executeSell = (symbol: string) => {
    const price = prices[symbol];
    const holding = holdings[symbol];
    if (!price || !holding || holding.shares <= 0) {
      setLatestAction({ symbol, action: 'NO_POSITION' });
      setTimeout(() => setLatestAction(null), 3000);
      return;
    }

    const qty = Math.min(quantities[symbol] ?? 1, holding.shares);
    const revenue = price * qty;
    const costBasis = holding.avgPrice * qty;
    const pnl = revenue - costBasis;
    const newBalance = balance + revenue;

    const updatedShares = holding.shares - qty;
    const newHoldings = { ...holdings };
    if (updatedShares <= 0) {
      delete newHoldings[symbol];
    } else {
      newHoldings[symbol] = { ...holding, shares: updatedShares, value: updatedShares * price };
    }

    const trade: Trade = {
      id: Math.random().toString(36).slice(2),
      symbol,
      action: 'SELL',
      shares: qty,
      price,
      total: revenue,
      pnl,
      timestamp: new Date().toLocaleTimeString(),
    };

    setBalance(newBalance);
    setHoldings(newHoldings);
    setTrades(prev => [trade, ...prev].slice(0, 50));
    setLatestAction({ symbol, action: 'SELL', pnl });

    if (pnl > 0) {
      setShowConfetti(true);
      if (confettiRef.current) clearTimeout(confettiRef.current);
      confettiRef.current = setTimeout(() => setShowConfetti(false), 3000);
    }
    setTimeout(() => setLatestAction(null), 3500);
  };

  const resetSandbox = () => {
    setBalance(INITIAL_BALANCE);
    setHoldings({});
    setTrades([]);
    setPriceChanges({});
    setLatestAction(null);
  };

  const winCount = trades.filter(t => t.action === 'SELL' && (t.pnl ?? 0) > 0).length;
  const lossCount = trades.filter(t => t.action === 'SELL' && (t.pnl ?? 0) < 0).length;
  const totalRealizedPnL = trades
    .filter(t => t.action === 'SELL')
    .reduce((s, t) => s + (t.pnl ?? 0), 0);

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12">
      {/* Confetti Effect */}
      <AnimatePresence>
        {showConfetti && (
          <div className="fixed inset-0 pointer-events-none z-50 overflow-hidden">
            {Array.from({ length: 30 }).map((_, i) => (
              <motion.div
                key={i}
                initial={{ y: -20, x: Math.random() * window.innerWidth, opacity: 1, scale: 1 }}
                animate={{ y: window.innerHeight + 50, rotate: Math.random() * 720, opacity: 0 }}
                transition={{ duration: 2 + Math.random() * 1.5, ease: 'easeIn', delay: Math.random() * 0.5 }}
                className="absolute w-3 h-3 rounded-sm"
                style={{ backgroundColor: ['#3B82F6', '#F59E0B', '#10B981', '#8B5CF6', '#EF4444'][i % 5] }}
              />
            ))}
          </div>
        )}
      </AnimatePresence>

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <h1 className="font-display text-4xl md:text-5xl font-bold tracking-tight flex items-center gap-3">
              <Zap className="w-10 h-10 text-amber-400" />
              Sandbox Trader
            </h1>
            <span className="bg-amber-500/20 border border-amber-500/40 text-amber-400 text-xs font-bold px-3 py-1 rounded-full animate-pulse">
              FAKE MONEY
            </span>
          </div>
          <p className="text-muted-foreground text-lg">
            Practice trading with ${INITIAL_BALANCE.toLocaleString()} virtual cash. Real live prices. Zero risk.
          </p>
        </div>
        <button
          onClick={resetSandbox}
          className="flex items-center gap-2 px-4 py-2 rounded-xl border border-border text-muted-foreground hover:text-foreground hover:border-theme_blue/50 transition-all text-sm font-bold"
        >
          <RefreshCw className="w-4 h-4" /> Reset Account
        </button>
      </div>

      {/* Action Toast */}
      <AnimatePresence>
        {latestAction && (
          <motion.div
            initial={{ opacity: 0, y: -20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.95 }}
            className={`fixed top-6 right-6 z-50 px-6 py-4 rounded-2xl shadow-2xl border font-bold text-sm flex items-center gap-3 ${
              latestAction.action === 'BUY'
                ? 'bg-theme_green/20 border-theme_green/40 text-theme_green'
                : latestAction.action === 'SELL'
                ? (latestAction.pnl ?? 0) >= 0
                  ? 'bg-theme_green/20 border-theme_green/40 text-theme_green'
                  : 'bg-theme_red/20 border-theme_red/40 text-theme_red'
                : 'bg-yellow-500/20 border-yellow-500/40 text-yellow-400'
            }`}
          >
            {latestAction.action === 'BUY' && <><ShoppingCart className="w-5 h-5" /> BUY executed on {latestAction.symbol}!</>}
            {latestAction.action === 'SELL' && latestAction.pnl !== undefined && (
              <>
                {(latestAction.pnl ?? 0) >= 0 ? <Trophy className="w-5 h-5" /> : <Flame className="w-5 h-5" />}
                SELL on {latestAction.symbol} — {(latestAction.pnl ?? 0) >= 0 ? '🎉 Profit' : '📉 Loss'}: ${Math.abs(latestAction.pnl ?? 0).toFixed(2)}
              </>
            )}
            {latestAction.action === 'INSUFFICIENT_FUNDS' && <><AlertTriangle className="w-5 h-5" /> Not enough cash!</>}
            {latestAction.action === 'NO_POSITION' && <><AlertTriangle className="w-5 h-5" /> No open position to sell!</>}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Portfolio Summary Bar */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          {
            label: 'Cash Available', icon: DollarSign, color: 'text-theme_blue',
            value: `$${balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
          },
          {
            label: 'Holdings Value', icon: BarChart3, color: 'text-purple-400',
            value: `$${totalPortfolioValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
          },
          {
            label: 'Total P&L', icon: totalPnL >= 0 ? TrendingUp : TrendingDown,
            color: totalPnL >= 0 ? 'text-theme_green' : 'text-theme_red',
            value: `${totalPnL >= 0 ? '+' : ''}$${totalPnL.toFixed(2)} (${totalPnLPct.toFixed(2)}%)`,
          },
          {
            label: 'Win / Loss', icon: Trophy, color: 'text-amber-400',
            value: `${winCount}W / ${lossCount}L`,
          },
        ].map(({ label, icon: Icon, color, value }) => (
          <motion.div
            key={label}
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
            className="bg-card border border-border rounded-2xl p-5"
          >
            <div className="flex items-center gap-2 mb-2">
              <Icon className={`w-4 h-4 ${color}`} />
              <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">{label}</span>
            </div>
            <div className={`text-xl font-bold font-mono ${color}`}>{value}</div>
          </motion.div>
        ))}
      </div>

      {/* Live Trading Cards */}
      <div className="grid md:grid-cols-2 gap-6">
        {SYMBOLS.map((symbol) => {
          const meta = SYMBOL_META[symbol];
          const price = prices[symbol];
          const holding = holdings[symbol];
          const flash = flashPrices[symbol];
          const liveValue = holding ? holding.shares * (price ?? holding.avgPrice) : 0;
          const unrealizedPnL = holding ? liveValue - holding.shares * holding.avgPrice : 0;
          const qty = quantities[symbol] ?? 1;
          const buyCost = price ? price * qty : 0;

          return (
            <motion.div
              key={symbol}
              initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }}
              className="bg-card border border-border rounded-3xl overflow-hidden"
              style={{ boxShadow: `0 0 40px ${meta.color}10` }}
            >
              {/* Symbol Header */}
              <div className="p-6 border-b border-border" style={{ background: `linear-gradient(135deg, ${meta.color}08, transparent)` }}>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="text-3xl">{meta.emoji}</div>
                    <div>
                      <div className="font-display font-bold text-xl">{symbol}</div>
                      <div className="text-muted-foreground text-sm">{meta.name}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ backgroundColor: meta.color }}></span>
                      <span className="relative inline-flex rounded-full h-2 w-2" style={{ backgroundColor: meta.color }}></span>
                    </span>
                    <span className="text-xs text-muted-foreground font-bold">LIVE</span>
                  </div>
                </div>

                {/* Live Price */}
                <motion.div
                  key={price}
                  animate={flash === 'up' ? { color: '#10B981' } : flash === 'down' ? { color: '#EF4444' } : { color: '#E4E4E7' }}
                  transition={{ duration: 0.3 }}
                  className="font-mono font-bold text-4xl mb-1"
                >
                  {price ? `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : isLoading ? '---' : 'Unavailable'}
                </motion.div>
                <div className={`flex items-center gap-1 text-sm font-bold ${flash === 'up' ? 'text-theme_green' : flash === 'down' ? 'text-theme_red' : 'text-muted-foreground'}`}>
                  {flash === 'up' ? <ChevronUp className="w-4 h-4" /> : flash === 'down' ? <ChevronDown className="w-4 h-4" /> : <Activity className="w-4 h-4" />}
                  Live Yahoo Finance Price
                </div>
              </div>

              {/* Holding Info */}
              {holding && (
                <div className="px-6 py-4 bg-background/40 border-b border-border">
                  <div className="flex justify-between items-center">
                    <div>
                      <div className="text-xs text-muted-foreground font-bold uppercase tracking-wider mb-1">Your Position</div>
                      <div className="font-bold text-lg">{holding.shares} contracts @ ${holding.avgPrice.toFixed(2)}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-xs text-muted-foreground font-bold uppercase tracking-wider mb-1">Unrealized P&L</div>
                      <div className={`font-bold text-lg font-mono ${unrealizedPnL >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
                        {unrealizedPnL >= 0 ? '+' : ''}${unrealizedPnL.toFixed(2)}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Controls */}
              <div className="p-6 space-y-4">
                {/* Quantity Selector */}
                <div>
                  <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">Quantity (Contracts)</label>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => setQuantities(q => ({ ...q, [symbol]: Math.max(1, (q[symbol] ?? 1) - 1) }))}
                      className="w-10 h-10 rounded-xl bg-background border border-border font-bold text-lg hover:border-theme_blue/50 transition-all"
                    >−</button>
                    <input
                      type="number"
                      min={1}
                      value={qty}
                      onChange={e => setQuantities(q => ({ ...q, [symbol]: Math.max(1, parseInt(e.target.value) || 1) }))}
                      className="flex-1 text-center bg-background border border-border rounded-xl py-2 font-bold text-lg focus:outline-none focus:border-theme_blue/50"
                    />
                    <button
                      onClick={() => setQuantities(q => ({ ...q, [symbol]: (q[symbol] ?? 1) + 1 }))}
                      className="w-10 h-10 rounded-xl bg-background border border-border font-bold text-lg hover:border-theme_blue/50 transition-all"
                    >+</button>
                  </div>
                  {price && (
                    <div className="text-xs text-muted-foreground mt-1 text-center">
                      Cost: <span className="font-bold text-foreground">${buyCost.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                    </div>
                  )}
                </div>

                {/* BUY / SELL Buttons */}
                <div className="grid grid-cols-2 gap-3">
                  <motion.button
                    whileTap={{ scale: 0.97 }}
                    onClick={() => executeBuy(symbol)}
                    disabled={!price || buyCost > balance}
                    className="py-4 rounded-2xl font-bold text-lg bg-theme_green/10 border-2 border-theme_green/30 text-theme_green hover:bg-theme_green hover:text-white hover:border-theme_green transition-all flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-theme_green/5 hover:shadow-theme_green/20"
                  >
                    <ArrowUpRight className="w-5 h-5" /> BUY
                  </motion.button>
                  <motion.button
                    whileTap={{ scale: 0.97 }}
                    onClick={() => executeSell(symbol)}
                    disabled={!price || !holding || holding.shares <= 0}
                    className="py-4 rounded-2xl font-bold text-lg bg-theme_red/10 border-2 border-theme_red/30 text-theme_red hover:bg-theme_red hover:text-white hover:border-theme_red transition-all flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-theme_red/5 hover:shadow-theme_red/20"
                  >
                    <ArrowDownRight className="w-5 h-5" /> SELL
                  </motion.button>
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>

      {/* Trade History */}
      <div className="bg-card border border-border rounded-3xl p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-display font-bold text-xl flex items-center gap-2">
            <Clock className="w-5 h-5 text-theme_blue" /> Trade History
          </h3>
          <div className="flex items-center gap-3">
            {totalRealizedPnL !== 0 && (
              <div className={`text-sm font-bold font-mono ${totalRealizedPnL >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
                Realized: {totalRealizedPnL >= 0 ? '+' : ''}${totalRealizedPnL.toFixed(2)}
              </div>
            )}
            <span className="text-xs text-muted-foreground">{trades.length} trades</span>
          </div>
        </div>

        {trades.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground">
            <ShoppingCart className="w-12 h-12 mx-auto mb-4 opacity-20" />
            <p className="text-lg font-medium">No trades yet</p>
            <p className="text-sm mt-1">Hit BUY or SELL above to start trading!</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                <tr>
                  <th className="pb-3 font-bold">Time</th>
                  <th className="pb-3 font-bold">Symbol</th>
                  <th className="pb-3 font-bold">Action</th>
                  <th className="pb-3 font-bold">Qty</th>
                  <th className="pb-3 font-bold">Price</th>
                  <th className="pb-3 font-bold text-right">Total</th>
                  <th className="pb-3 font-bold text-right">P&L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                <AnimatePresence initial={false}>
                  {trades.map((trade) => (
                    <motion.tr
                      key={trade.id}
                      initial={{ opacity: 0, backgroundColor: trade.action === 'BUY' ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)' }}
                      animate={{ opacity: 1, backgroundColor: 'rgba(0,0,0,0)' }}
                      transition={{ duration: 1.5 }}
                      className="hover:bg-background/50 transition-colors"
                    >
                      <td className="py-3 font-mono text-muted-foreground">{trade.timestamp}</td>
                      <td className="py-3">
                        <span className="flex items-center gap-1.5">
                          <span>{SYMBOL_META[trade.symbol]?.emoji}</span>
                          <span className="font-bold">{trade.symbol}</span>
                        </span>
                      </td>
                      <td className="py-3">
                        <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold ${
                          trade.action === 'BUY'
                            ? 'bg-theme_green/15 text-theme_green'
                            : 'bg-theme_red/15 text-theme_red'
                        }`}>
                          {trade.action === 'BUY' ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                          {trade.action}
                        </span>
                      </td>
                      <td className="py-3 font-mono font-bold">{trade.shares}</td>
                      <td className="py-3 font-mono">${trade.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td className="py-3 font-mono text-right font-bold">${trade.total.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td className={`py-3 font-mono text-right font-bold ${
                        trade.pnl === undefined
                          ? 'text-muted-foreground'
                          : trade.pnl >= 0 ? 'text-theme_green' : 'text-theme_red'
                      }`}>
                        {trade.pnl !== undefined
                          ? `${trade.pnl >= 0 ? '+' : ''}$${trade.pnl.toFixed(2)}`
                          : '—'}
                      </td>
                    </motion.tr>
                  ))}
                </AnimatePresence>
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Footer note */}
      <div className="text-center text-xs text-muted-foreground py-4">
        🧪 Sandbox mode — all trades use virtual money. Prices are real live data from Yahoo Finance.
        The real AI engine continues running independently.
      </div>
    </div>
  );
};
