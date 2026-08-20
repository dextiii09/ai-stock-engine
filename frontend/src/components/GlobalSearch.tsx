import { useState, useEffect, useRef } from 'react';
import { Search, TrendingUp, TrendingDown, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';

const MOCK_TICKERS = [
  { symbol: 'AAPL', name: 'Apple Inc.', price: 178.42, change: 1.2 },
  { symbol: 'MSFT', name: 'Microsoft Corp.', price: 334.21, change: -0.4 },
  { symbol: 'TSLA', name: 'Tesla Inc.', price: 214.50, change: 4.2 },
  { symbol: 'NVDA', name: 'NVIDIA Corp.', price: 462.10, change: 2.1 },
  { symbol: 'RELIANCE', name: 'Reliance Industries', price: 2845.00, change: 0.8 },
  { symbol: 'HDFCBANK', name: 'HDFC Bank Ltd.', price: 1540.20, change: -1.1 },
  { symbol: 'INFY', name: 'Infosys Limited', price: 1420.75, change: 0.5 },
  { symbol: 'TCS', name: 'Tata Consultancy Services', price: 3450.00, change: 1.5 },
];

export const GlobalSearch = () => {
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
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

  const results = MOCK_TICKERS.filter(t => 
    t.symbol.toLowerCase().includes(query.toLowerCase()) || 
    t.name.toLowerCase().includes(query.toLowerCase())
  );

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
                  {['NVDA', 'TSLA', 'RELIANCE'].map(sym => (
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
                {results.map((ticker) => (
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
                      <div>
                        <div className="font-bold text-sm">${ticker.price.toFixed(2)}</div>
                        <div className={`text-xs font-medium flex items-center justify-end gap-0.5 ${ticker.change >= 0 ? 'text-theme_green' : 'text-theme_red'}`}>
                          {ticker.change >= 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                          {Math.abs(ticker.change)}%
                        </div>
                      </div>
                      <ArrowRight className="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-100 group-hover:text-theme_blue transition-all translate-x-[-10px] group-hover:translate-x-0" />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-8 text-center text-muted-foreground text-sm">
                No results found for "{query}".
              </div>
            )}
            
            <div className="p-2 bg-background border-t border-border text-center">
              <span className="text-[10px] text-muted-foreground font-medium">Data delayed by 15 mins. Press Esc to close.</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
