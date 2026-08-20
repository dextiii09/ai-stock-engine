import { useState, useEffect, useRef } from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import {
  Bell, Settings, User, Activity, PieChart, BarChart2,
  DollarSign, Bot, History, Newspaper, Globe, ListTree,
  Menu, X, Zap, Bug
} from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import { CommandPalette } from '../CommandPalette';
import { OnboardingModal } from '../OnboardingModal';
import { FloatingAssistant } from '../FloatingAssistant';
import { GlobalSearch } from '../GlobalSearch';
import { API_BASE } from '../../config';

// ─── Navigation Config ────────────────────────────────────────────────────────

const FEATURES_NAV = [
  { name: 'Markets',       path: '/markets',       icon: Globe },
  { name: 'Portfolio',     path: '/portfolio',     icon: PieChart },
  { name: 'Auto Trader',   path: '/autotrader',    icon: Bot },
  { name: 'Money Tracker', path: '/money-tracker', icon: DollarSign },
  { name: 'AI Analytics',  path: '/analytics',     icon: BarChart2 },
  { name: 'Backtesting',   path: '/backtesting',   icon: History },
];

const TOOLS_NAV = [
  { name: 'Watchlist',        path: '/watchlist',  icon: ListTree },
  { name: 'Scanner',          path: '/scanner',    icon: Activity },
  { name: 'News & Sentiment', path: '/news',       icon: Newspaper },
  { name: 'Sandbox Trader',   path: '/sandbox',    icon: Zap },
  { name: 'AI Bug Finder',    path: '/bug-finder', icon: Bug },
];

// ─── SSE market segment — derived from ?market= URL param ────────────────────

function getMarketSegment(_pathname: string, search: string): string {
  const raw = new URLSearchParams(search).get('market')?.toUpperCase();
  if (raw === 'INDIA')  return 'INDIA';
  if (raw === 'STOCKS') return 'STOCKS';
  if (raw === 'CRYPTO') return 'CRYPTO';
  if (raw === 'FOREX')  return 'FOREX';
  return 'US';
}

// ─── Shell ────────────────────────────────────────────────────────────────────

export const Shell = () => {
  const [isBeginnerMode, setIsBeginnerMode] = useState(true);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isCommandOpen, setCommandOpen] = useState(false);
  const [isNotificationsOpen, setNotificationsOpen] = useState(false);
  const [isOnboardingOpen, setOnboardingOpen] = useState(
    () => localStorage.getItem('onboardingComplete') !== 'true'
  );
  const [toasts, setToasts] = useState<any[]>([]);
  const lastLogTimeRef = useRef<string | null>(null);
  const lastLogMsgRef  = useRef<string | null>(null);
  const location = useLocation();

  const marketSegment = getMarketSegment(location.pathname, location.search);

  const addToast = (title: string, message: string, type: 'info' | 'success' | 'error' | 'warning') => {
    const id = Math.random().toString(36).substr(2, 9);
    setToasts(prev => [...prev, { id, title, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 6000);
  };

  // SSE — reconnect only when market segment changes
  useEffect(() => {
    lastLogTimeRef.current = null;
    lastLogMsgRef.current  = null;

    const streamUrl =
      marketSegment === 'INDIA'  ? `${API_BASE}/indian/bot/stream` :
      marketSegment === 'STOCKS' ? `${API_BASE}/stocks/bot/stream` :
      marketSegment === 'CRYPTO' ? `${API_BASE}/crypto/bot/stream` :
      marketSegment === 'FOREX'  ? `${API_BASE}/forex/bot/stream`  :
      `${API_BASE}/bot/stream`;

    const es = new EventSource(streamUrl);
    let isFirst = true;

    es.onmessage = (event) => {
      try {
        const log = JSON.parse(event.data);
        if (log.connected) { isFirst = false; return; }
        if (isFirst) { isFirst = false; return; }

        if (log.message?.includes('[BUY]')) {
          addToast('🟢 BUY Order Executed', log.message, 'success');
        } else if (
          log.message?.includes('[SELL]') ||
          log.message?.includes('[SHORT]') ||
          log.message?.includes('[CLOSE]')
        ) {
          addToast('🔴 SELL Order Executed', log.message, 'error');
        }
      } catch { /* malformed frame */ }
    };

    es.onerror = () => { /* EventSource auto-reconnects */ };
    return () => es.close();
  }, [marketSegment]);

  const handleOnboardingClose = () => {
    localStorage.setItem('onboardingComplete', 'true');
    setOnboardingOpen(false);
  };

  // Mobile bottom nav — feature-first
  const mobileNavItems = [
    { name: 'Markets',   path: '/markets',      icon: Globe },
    { name: 'Portfolio', path: '/portfolio',     icon: PieChart },
    { name: 'Trader',    path: '/autotrader',    icon: Bot },
    { name: 'Analytics', path: '/analytics',     icon: BarChart2 },
    { name: 'More',      path: '#',              icon: Menu, isMore: true },
  ];

  // Active path matching — feature paths are exact, tolerate ?market= suffix
  const isPathActive = (path: string) => location.pathname === path;

  const NavLink = ({ item, onClick }: { item: typeof FEATURES_NAV[0]; onClick?: () => void }) => {
    const Icon = item.icon;
    const isActive = isPathActive(item.path);
    return (
      <Link
        to={item.path}
        onClick={onClick}
        className={`flex items-center gap-3 px-4 py-2.5 rounded-2xl transition-all duration-200 group relative overflow-hidden ${
          isActive
            ? 'bg-theme_blue text-white shadow-lg shadow-theme_blue/20'
            : 'text-muted-foreground hover:bg-card hover:text-foreground'
        }`}
      >
        {isActive && (
          <motion.div
            layoutId="activeNavBg"
            className="absolute inset-0 bg-theme_blue -z-10"
            initial={false}
            transition={{ type: 'spring', stiffness: 300, damping: 30 }}
          />
        )}
        <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-white' : 'text-muted-foreground group-hover:text-theme_blue transition-colors'}`} />
        <span className="font-medium text-sm">{item.name}</span>
      </Link>
    );
  };

  const SidebarContent = () => (
    <>
      {/* Logo */}
      <div className="p-6 flex items-center justify-between border-b border-border">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-theme_blue to-purple-600 flex items-center justify-center">
            <Activity className="w-4 h-4 text-white" />
          </div>
          <span className="font-display font-bold text-xl tracking-tight">AI Stock</span>
        </div>
        <button className="lg:hidden text-muted-foreground" onClick={() => setIsMobileMenuOpen(false)}>
          <X className="w-6 h-6" />
        </button>
      </div>

      {/* Scrollable nav */}
      <div className="flex-1 overflow-y-auto py-4 px-4 space-y-1 no-scrollbar">

        {/* Features */}
        <p className="px-4 pt-2 pb-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
          Features
        </p>
        <div className="space-y-0.5">
          {FEATURES_NAV.map(item => (
            <NavLink key={item.path} item={item} onClick={() => setIsMobileMenuOpen(false)} />
          ))}
        </div>

        {/* Tools */}
        <div className="pt-3">
          <p className="px-4 pb-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
            Research & Tools
          </p>
          <div className="space-y-0.5">
            {TOOLS_NAV.map(item => {
              const Icon = item.icon;
              const isActive = isPathActive(item.path);
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={() => setIsMobileMenuOpen(false)}
                  className={`flex items-center gap-3 px-4 py-2.5 rounded-2xl transition-all duration-200 group relative overflow-hidden ${
                    isActive
                      ? 'bg-theme_blue text-white shadow-lg shadow-theme_blue/20'
                      : 'text-muted-foreground hover:bg-card hover:text-foreground'
                  }`}
                >
                  {isActive && (
                    <motion.div
                      layoutId="activeNavBg"
                      className="absolute inset-0 bg-theme_blue -z-10"
                      initial={false}
                      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                    />
                  )}
                  <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-white' : 'text-muted-foreground group-hover:text-theme_blue transition-colors'}`} />
                  <span className="font-medium text-sm">{item.name}</span>
                </Link>
              );
            })}
          </div>
        </div>
      </div>

      {/* Footer — mode toggle + settings */}
      <div className="p-4 border-t border-border mt-auto">
        <div className="bg-card border border-border rounded-xl p-4 mb-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Mode</span>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${isBeginnerMode ? 'bg-theme_green/20 text-theme_green' : 'bg-theme_red/20 text-theme_red'}`}>
              {isBeginnerMode ? 'Beginner' : 'Pro'}
            </span>
          </div>
          <label className="relative inline-flex items-center cursor-pointer w-full">
            <input type="checkbox" className="sr-only peer" checked={!isBeginnerMode} onChange={() => setIsBeginnerMode(!isBeginnerMode)} />
            <div className="w-full h-8 bg-background border border-border peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-[calc(100%-4px)] peer-checked:after:border-white after:content-[''] after:absolute after:top-[4px] after:left-[4px] after:bg-muted-foreground peer-checked:after:bg-theme_red after:border-gray-300 after:border after:rounded-full after:h-6 after:w-[calc(50%-4px)] after:transition-all peer-checked:border-theme_red/50"></div>
            <span className="absolute left-4 text-[10px] font-bold text-muted-foreground peer-checked:text-transparent transition-colors z-10 pointer-events-none">EASY</span>
            <span className="absolute right-4 text-[10px] font-bold text-transparent peer-checked:text-theme_red transition-colors z-10 pointer-events-none">PRO</span>
          </label>
        </div>
        <Link to="/settings" onClick={() => setIsMobileMenuOpen(false)} className="flex items-center gap-3 px-4 py-3 rounded-xl text-muted-foreground hover:bg-border/50 transition-colors font-medium">
          <Settings className="w-5 h-5" />
          Settings
        </Link>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-background text-foreground flex overflow-hidden">

      {/* Desktop Sidebar */}
      <aside className="hidden lg:flex flex-col w-72 border-r border-border bg-card/50 backdrop-blur-xl shrink-0 z-20">
        <SidebarContent />
      </aside>

      {/* Mobile Sidebar */}
      <AnimatePresence>
        {isMobileMenuOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="fixed inset-0 bg-background/80 backdrop-blur-sm z-40 lg:hidden"
              onClick={() => setIsMobileMenuOpen(false)}
            />
            <motion.aside
              initial={{ x: '-100%' }} animate={{ x: 0 }} exit={{ x: '-100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className="fixed inset-y-0 left-0 w-[80%] max-w-sm border-r border-border bg-card z-50 flex flex-col lg:hidden"
            >
              <SidebarContent />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <div className="flex-1 flex flex-col relative h-screen">

        {/* Top Header */}
        <header className="h-20 border-b border-border bg-background/80 backdrop-blur-xl flex items-center justify-between px-4 sm:px-8 shrink-0 z-30 sticky top-0">
          <div className="flex items-center gap-4 w-full">
            <button
              className="lg:hidden p-2 -ml-2 text-muted-foreground rounded-lg hover:bg-border/50"
              onClick={() => setIsMobileMenuOpen(true)}
            >
              <Menu className="w-6 h-6" />
            </button>
            <GlobalSearch />
          </div>

          <div className="flex items-center gap-2 sm:gap-4 ml-4">
            <div className="relative">
              <button
                onClick={() => setNotificationsOpen(!isNotificationsOpen)}
                className="p-2 sm:p-2.5 rounded-full border border-border hover:bg-border/50 transition-colors relative"
              >
                <Bell className="w-5 h-5 text-muted-foreground" />
                <span className="absolute top-1.5 right-1.5 w-2.5 h-2.5 bg-theme_blue rounded-full border-2 border-background animate-pulse" />
              </button>

              <AnimatePresence>
                {isNotificationsOpen && (
                  <motion.div
                    initial={{ opacity: 0, y: 10, scale: 0.95 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 10, scale: 0.95 }}
                    className="absolute right-0 mt-4 w-80 sm:w-96 bg-card border border-border rounded-3xl shadow-2xl overflow-hidden z-50"
                  >
                    <div className="p-4 border-b border-border flex justify-between items-center">
                      <h3 className="font-bold">Notifications</h3>
                      <button className="text-xs text-theme_blue hover:underline">Mark all as read</button>
                    </div>
                    <div className="max-h-[60vh] overflow-y-auto">
                      <div className="p-4 border-b border-border/50 hover:bg-background transition-colors cursor-pointer flex gap-4">
                        <div className="w-10 h-10 rounded-full bg-theme_green/10 text-theme_green flex items-center justify-center shrink-0">
                          <Bot className="w-5 h-5" />
                        </div>
                        <div>
                          <p className="text-sm font-bold">Auto Trader Executed</p>
                          <p className="text-xs text-muted-foreground mt-0.5">Bought 50 shares of AAPL at $178.42 based on RSI divergence.</p>
                          <p className="text-[10px] text-muted-foreground mt-2">2 mins ago</p>
                        </div>
                      </div>
                      <div className="p-4 hover:bg-background transition-colors cursor-pointer flex gap-4 opacity-70">
                        <div className="w-10 h-10 rounded-full bg-theme_yellow/10 text-theme_yellow flex items-center justify-center shrink-0">
                          <Activity className="w-5 h-5" />
                        </div>
                        <div>
                          <p className="text-sm font-bold">Risk Alert</p>
                          <p className="text-xs text-muted-foreground mt-0.5">Portfolio volatility has exceeded your set threshold (Beta {'>'} 1.5).</p>
                          <p className="text-[10px] text-muted-foreground mt-2">1 hour ago</p>
                        </div>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            <Link
              to="/settings"
              className="w-9 h-9 sm:w-10 sm:h-10 rounded-full bg-theme_blue/10 border border-theme_blue/20 flex items-center justify-center text-theme_blue hover:scale-105 transition-transform"
            >
              <User className="w-5 h-5" />
            </Link>
          </div>
        </header>

        {/* Main Content */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-8 overflow-x-hidden pb-28 lg:pb-8">
          <Outlet context={{ isBeginnerMode }} />
        </main>

        {/* Mobile Bottom Nav */}
        <div className="lg:hidden fixed bottom-0 left-0 right-0 z-40 px-4 pb-6 pt-2 pointer-events-none">
          <div className="bg-card/80 backdrop-blur-xl border border-border shadow-2xl rounded-3xl mx-auto max-w-sm flex items-center justify-between p-2 pointer-events-auto">
            {mobileNavItems.map((item) => {
              const isActive = location.pathname === item.path;
              const Icon = item.icon;
              return (
                <Link
                  key={item.name}
                  to={item.path === '#' ? '#' : item.path}
                  onClick={(e) => {
                    if (item.isMore) {
                      e.preventDefault();
                      setIsMobileMenuOpen(true);
                    }
                  }}
                  className="flex flex-col items-center justify-center w-16 h-14 rounded-2xl relative transition-colors"
                >
                  {isActive && (
                    <motion.div
                      layoutId="bottomNavBubble"
                      className="absolute inset-0 bg-theme_blue/10 rounded-2xl -z-10"
                      transition={{ type: 'spring', bounce: 0.2, duration: 0.6 }}
                    />
                  )}
                  <Icon className={`w-5 h-5 mb-1 transition-colors ${isActive ? 'text-theme_blue' : 'text-muted-foreground'}`} />
                  <span className={`text-[10px] font-bold transition-colors ${isActive ? 'text-theme_blue' : 'text-muted-foreground'}`}>
                    {item.name}
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      </div>

      <CommandPalette isOpen={isCommandOpen} setIsOpen={setCommandOpen} />
      <OnboardingModal isOpen={isOnboardingOpen} onClose={handleOnboardingClose} />
      <FloatingAssistant />

      {/* Toast Stack */}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-3 max-w-sm w-full pointer-events-none">
        <AnimatePresence>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, y: 50, scale: 0.9 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8, transition: { duration: 0.2 } }}
              className={`p-4 rounded-2xl border shadow-xl flex gap-3 pointer-events-auto backdrop-blur-md ${
                toast.type === 'success' ? 'bg-theme_green/10 border-theme_green/30 text-foreground' :
                toast.type === 'error'   ? 'bg-theme_red/10 border-theme_red/30 text-foreground' :
                toast.type === 'warning' ? 'bg-theme_yellow/10 border-theme_yellow/30 text-foreground' :
                'bg-card/90 border-border text-foreground'
              }`}
            >
              <div className="flex-1">
                <h4 className="font-bold text-sm">{toast.title}</h4>
                <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{toast.message}</p>
              </div>
              <button
                onClick={() => setToasts(prev => prev.filter(t => t.id !== toast.id))}
                className="text-muted-foreground hover:text-foreground shrink-0 text-xs self-start"
              >
                ✕
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
};
