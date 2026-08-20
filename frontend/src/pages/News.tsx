import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Newspaper, TrendingUp, TrendingDown, Minus, Search, ExternalLink, Loader2 } from 'lucide-react';
import { API_BASE } from '../config';

interface Article {
  title: string;
  url: string;
  source: string;
  sentiment_score: number;
  sentiment_label: 'positive' | 'negative' | 'neutral';
  published_at: number;
}

export const News = () => {
  const [mode, setMode] = useState<'global' | 'ticker'>('global');
  const [ticker, setTicker] = useState('AAPL');
  const [searchInput, setSearchInput] = useState('');
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchNews = async (currentMode: 'global' | 'ticker', currentTicker: string, isSilent = false) => {
    if (!isSilent) setLoading(true);
    if (!isSilent) setError('');
    try {
      const endpoint = currentMode === 'global' 
        ? `${API_BASE}/news/global` 
        : `${API_BASE}/news/${currentTicker}?limit=10`;
        
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error('Failed to fetch news');
      const data = await res.json();
      setArticles(data.articles || []);
    } catch (e: any) {
      if (!isSilent) setError('Could not fetch news. Ensure the backend is running on port 8080.');
      if (!isSilent) {
        setArticles([
          { title: `AI Upgrade for ${currentMode === 'global' ? 'Market' : currentTicker} signals bullish momentum`, url: '#', source: 'Bloomberg', sentiment_score: 0.8, sentiment_label: 'positive', published_at: Date.now() / 1000 - 3600 },
          { title: `${currentMode === 'global' ? 'Global' : currentTicker} Q3 Earnings expectations lowered`, url: '#', source: 'Reuters', sentiment_score: -0.4, sentiment_label: 'negative', published_at: Date.now() / 1000 - 7200 },
          { title: `Market holding steady ahead of announcements`, url: '#', source: 'WSJ', sentiment_score: 0.0, sentiment_label: 'neutral', published_at: Date.now() / 1000 - 86400 }
        ]);
      }
    } finally {
      if (!isSilent) setLoading(false);
    }
  };

  useEffect(() => {
    fetchNews(mode, ticker);
    
    // Real-time polling every 30 seconds
    const interval = setInterval(() => {
      fetchNews(mode, ticker, true);
    }, 30000);
    
    return () => clearInterval(interval);
  }, [mode, ticker]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchInput.trim()) {
      setTicker(searchInput.toUpperCase().trim());
      setMode('ticker');
      setSearchInput('');
    }
  };

  const getSentimentColor = (label: string) => {
    if (label === 'positive') return 'bg-theme_green/10 text-theme_green border-theme_green/20';
    if (label === 'negative') return 'bg-theme_red/10 text-theme_red border-theme_red/20';
    return 'bg-theme_yellow/10 text-theme_yellow border-theme_yellow/20';
  };

  const getSentimentIcon = (label: string) => {
    if (label === 'positive') return <TrendingUp className="w-3 h-3" />;
    if (label === 'negative') return <TrendingDown className="w-3 h-3" />;
    return <Minus className="w-3 h-3" />;
  };

  const formatTime = (timestamp: number) => {
    const diff = Math.floor((Date.now() / 1000) - timestamp);
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8 pb-12">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-tight mb-2 flex items-center gap-3">
            <Newspaper className="w-10 h-10 text-theme_blue" /> AI News Hub
          </h1>
          <p className="text-muted-foreground">Real-time financial news with instant VADER sentiment analysis.</p>
        </div>
        
        <form onSubmit={handleSearch} className="relative w-full md:w-64">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input 
            type="text" 
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search symbol (e.g. TSLA)" 
            className="w-full bg-card border border-border rounded-full py-2.5 pl-10 pr-4 focus:outline-none focus:border-theme_blue/50 text-sm"
          />
        </form>
      </div>

      <div className="bg-card border border-border rounded-3xl p-6 md:p-8 min-h-[500px]">
        <div className="flex items-center justify-between mb-8 border-b border-border pb-4">
          <h2 className="font-display text-2xl font-bold flex items-center gap-4">
            Feed for {mode === 'global' ? <span className="text-theme_blue">Global Markets</span> : <span className="text-theme_blue">{ticker}</span>}
            
            <div className="flex bg-background border border-border rounded-lg p-1 text-xs ml-4">
              <button 
                onClick={() => setMode('global')}
                className={`px-3 py-1.5 rounded-md transition-colors ${mode === 'global' ? 'bg-theme_blue text-white shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
              >
                Global
              </button>
              <button 
                onClick={() => setMode('ticker')}
                className={`px-3 py-1.5 rounded-md transition-colors ${mode === 'ticker' ? 'bg-theme_blue text-white shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
              >
                Ticker
              </button>
            </div>
          </h2>
          {loading && <Loader2 className="w-5 h-5 text-theme_blue animate-spin" />}
        </div>

        {error && (
          <div className="mb-6 p-4 bg-theme_yellow/10 border border-theme_yellow/20 rounded-xl text-theme_yellow text-sm">
            {error} (Using fallback demo data)
          </div>
        )}

        <div className="space-y-4">
          <AnimatePresence mode="popLayout">
            {articles.map((article, idx) => (
              <motion.div 
                key={`${article.url}-${idx}`}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.1 }}
                className="group p-5 rounded-2xl border border-border/50 hover:border-theme_blue/30 bg-background/50 hover:bg-card transition-all"
              >
                <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <span className="text-xs font-medium text-muted-foreground bg-border/50 px-2 py-0.5 rounded-md">
                        {article.source}
                      </span>
                      <span className="text-xs text-muted-foreground flex items-center gap-1">
                        {formatTime(article.published_at)}
                      </span>
                    </div>
                    <a href={article.url} target="_blank" rel="noopener noreferrer" className="font-display font-bold text-lg leading-tight group-hover:text-theme_blue transition-colors flex items-start gap-2">
                      {article.title}
                      <ExternalLink className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity mt-1 shrink-0" />
                    </a>
                  </div>
                  
                  <div className="flex shrink-0">
                    <div className={`flex flex-col items-center justify-center px-4 py-3 rounded-xl border min-w-[100px] ${getSentimentColor(article.sentiment_label)}`}>
                      <span className="text-[10px] uppercase tracking-wider mb-1 opacity-80">Sentiment</span>
                      <div className="flex items-center gap-1.5 font-bold">
                        {getSentimentIcon(article.sentiment_label)}
                        {article.sentiment_score.toFixed(2)}
                      </div>
                    </div>
                  </div>
                </div>
              </motion.div>
            ))}
            
            {!loading && articles.length === 0 && (
              <div className="text-center py-20 text-muted-foreground">
                No recent news found for {ticker}.
              </div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
