import { useState, useEffect, useRef } from 'react';
import { Search, TrendingUp, TrendingDown, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { API_BASE } from '../config';

// IV&V finding 2026-08-21 (audit Finding #9): the symbol/name pairs below
// are real, static reference data (a searchable ticker universe — like a
// phone book) and are fine to keep hardcoded. What was NOT fine, and has
// been removed: fixed price/change numbers baked into this list, which
// never updated and were shown as if live. Prices/changes are now fetched
// from the real `/data/live/{symbol}` endpoint per result, on demand.
const TICKER_UNIVERSE = [
  { symbol: 'AAPL', name: 'Apple Inc.' },
  { symbol: 'MSFT', name: 'Microsoft Corp.' },
  { symbol: 'TSLA', name: 'Tesla Inc.' },
  { symbol: 'NVDA', name: 'NVIDIA Corp.' },
  { symbol: 'RELIANCE.NS', name: 'Reliance Industries' },
  { symbol: 'HDFCBANK.NS', name: 'HDFC Bank Ltd.' },
  { symbol: 'INFY.NS', name: 'Infosys Limited' },
  { symbol: 'TCS.NS', name: 'Tata Consultancy Services' },
];

interface LiveQuote {
  price: number;
  daily_change_pct: number;
}

const quoteCache = new Map<string, LiveQuote | 'unavailable'>();

export const GlobalSearch = () => {
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [, forceRerender] = useState(0);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const results = TICKER_UNIVERSE.filter(t =>
    t.symbol.toLowerCase().includes(query.toLowerCase()) ||
    t.name.toLowerCase().includes(query.toLowerCase())
  );

  // Fetch real quotes (debounced) for whichever results are currently
  // visible — never for the full universe, and never fabricated.
  useEffect(() => {
    if (!isOpen || results.length === 0) return;
    const timer = setTimeout(() => {
      results.forEach(({ symbol }) => {
        if (quoteCache.has(symbol)) return;
        fetch(`${API_BASE}/data/live/${encodeURIComponent(symbol)}`)
          .then(res => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
          .then(data => {
            if (data?.error) throw new Error(data.error);
            quoteCache.set(symbol, { price: data.price, daily_change_pct: data.daily_change_pct });
          })
          .catch(() => quoteCache.set(symbol, 'unavailable'))
          .finally(() => forceRerender(n => n + 1));
      });
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, query]);

  const handleSelect = (symbol: string) => {
    navigate(`/symbol/${symbol}`);
    setIsOpen(false);
    setQuery('');
  };

  return (
    <div ref={wrapperRef} className="relative flex-1 max-w-md">
      <div 
        className={`flex items-center px-4 py-2 text-sm transition-colors border ${
          isOpen ? 'bg-card border-theme_blue shadow-[0_0_15px_rgba(59,130,246,0.15)] rounded-t-2xl' : 'bg-card border-border rounded-full hover:border-theme_blue/50 cursor-text'
        }`}
        onClick={() => setIsOpen(true)}
      >
        <Search className={`w-4 h-4 mr-3 transition-colors ${isOpen ? 'text-theme_blue' : 'text-muted-foreground'}`} />
        <input 
          type="text"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setIsOpen(true); }}
          placeholder="Search symbols (e.g., AAPL)..."
          className="flex-1 bg-transparent border-none outline-none placeholder:text-muted-foreground text-foreground"
          onFocus={() => setIsOpen(true)}
        />
        {!isOpen && (
           <kbd className="hidden sm:inline-flex items-center gap-1 font-mono text-[10px] bg-background border border-border px-1.5 py-0.5 rounded text-muted-foreground">
             <span className="text-xs">/</span>
           </kbd>
        )}
      </div>

      <AnimatePresence>
        {isOpen && (
          <motion.div 
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.15 }}
            className="absolute top-full left-0 right-0 bg-card border border-t-0 border-theme_blue rounded-b-2xl shadow-2xl overflow-hidden z-50 flex flex-col max-h-[350px]"
          >
            {query.length === 0 ? (
              <div className="p-4">
                <div className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-3">Trending Tickers</div>
                <div className="flex flex-wrap gap-2">
                  {['NVDA', 'TSLA', 'RELIANCE.NS'].map(sym => (
                    <button 
                      key={sym}
                      onClick={() => handleSelect(sym)}
                      className="px-3 py-1.5 bg-background border border-border rounded-lg text-xs font-bold hover:bg-theme_blue/10 hover:text-theme_blue hover:border-theme_blue/30 transition-colors flex items-center gap-1"
                    >
                      {sym} <TrendingUp className="w-3 h-3 text-theme_green" />
                    </button>
                  ))}
                </div>
              </div>
            ) : results.length > 0 ? (
              <div className="overflow-y-auto">
                {results.map((ticker) => {
                  const quote = quoteCache.get(ticker.symbol);
                  return (
                    <div
                      key={ticker.symbol}
                      onClick={() => handleSelect(ticker.symbol)}
                      className="flex items-center justify-between p-3 border-b border-border/50 hover:bg-theme_blue/10 cursor-pointer group transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-background border border-border flex items-center justify-center font-bold text-xs shrink-0 group-hover:border-theme_blue/30 transition-colors">
                          {ticker.symbol.charAt(0)}
                        </div>
                        <div>
                          <div className="font-bold text-sm group-hover:text-theme_blue transition-colors">{ticker.symbol}</div>
                          <div className="text-xs text-muted-foreground">{ticker.name}</div>
                        </div>
                      </div>
                      <div className="text-right flex items-center gap-4">
                        {quote && quote !== 'unavailable' ? (
                          <div>
                            <div className="font-bold text-sm">${quote.price.toFixed(2)}</div>
                            <div className={`text-xs font-medium flex items-center justify-end gap-0.5 ${quote.daily_change_pct >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
                              {quote.daily_change_pct >= 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                              {Math.abs(quote.daily_change_pct).toFixed(2)}%
                            </div>
                          </div>
                        ) : quote === 'unavailable' ? (
                          <div className="text-xs text-muted-foreground">N/A</div>
                        ) : (
                          <div className="text-xs text-muted-foreground animate-pulse">Loading…</div>
                        )}
                        <ArrowRight className="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-100 group-hover:text-theme_blue transition-all translate-x-[-10px] group-hover:translate-x-0" />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="p-8 text-center text-muted-foreground text-sm">
                No results found for "{query}".
              </div>
            )}
            
            <div className="p-2 bg-background border-t border-border text-center">
              <span className="text-[10px] text-muted-foreground font-medium">Press Esc to close.</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
