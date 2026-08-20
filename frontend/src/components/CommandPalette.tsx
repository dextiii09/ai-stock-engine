import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, LayoutDashboard, LineChart, PieChart, History, Bot, Settings, ChevronRight, Terminal, Zap, FileText } from 'lucide-react';

interface Props {
  isOpen: boolean;
  setIsOpen: (v: boolean) => void;
}

interface PaletteItem {
  id: string;
  name: string;
  icon: React.ComponentType<{ className?: string }>;
  path?: string;
  action?: () => void;
}

export const CommandPalette: React.FC<Props> = ({ isOpen, setIsOpen }) => {
  const [search, setSearch] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Handle Cmd+K / Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsOpen(!isOpen);
      }
      if (e.key === 'Escape') setIsOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, setIsOpen]);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 100);
      setSearch('');
      setSelectedIndex(0);
    }
  }, [isOpen]);

  const navigationItems: PaletteItem[] = [
    { id: 'nav-1', name: 'Go to Dashboard', icon: LayoutDashboard, path: '/' },
    { id: 'nav-2', name: 'Go to Portfolio', icon: PieChart, path: '/portfolio' },
    { id: 'nav-3', name: 'Go to Scanner', icon: LineChart, path: '/scanner' },
    { id: 'nav-4', name: 'Go to Auto Trader', icon: Bot, path: '/autotrader' },
    { id: 'nav-5', name: 'Go to Backtesting', icon: History, path: '/backtesting' },
    { id: 'nav-6', name: 'Go to Settings', icon: Settings, path: '/settings' },
  ];

  const actionItems: PaletteItem[] = [
    { id: 'act-1', name: 'Generate Tax Report (PDF)', icon: FileText, action: () => alert('Generating PDF...') },
    { id: 'act-2', name: 'Run Global Scanner', icon: Zap, action: () => navigate('/scanner') },
    { id: 'act-3', name: 'Stop All Autonomous Trading', icon: Terminal, action: () => alert('Sending kill signal...') },
  ];

  const allItems = [
    { heading: 'Navigation', items: navigationItems.filter(i => i.name.toLowerCase().includes(search.toLowerCase())) },
    { heading: 'Quick Actions', items: actionItems.filter(i => i.name.toLowerCase().includes(search.toLowerCase())) }
  ].filter(group => group.items.length > 0);

  const flatItems = allItems.flatMap(group => group.items);

  useEffect(() => {
    setSelectedIndex(0);
  }, [search]);

  // Handle keyboard navigation inside the palette
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => (prev < flatItems.length - 1 ? prev + 1 : prev));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => (prev > 0 ? prev - 1 : prev));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (flatItems[selectedIndex]) {
        executeItem(flatItems[selectedIndex]);
      }
    }
  };

  const executeItem = (item: PaletteItem) => {
    if (item.path) {
      navigate(item.path);
    } else if (item.action) {
      item.action();
    }
    setIsOpen(false);
  };

  // Scroll into view logic
  useEffect(() => {
    if (listRef.current) {
      const activeEl = listRef.current.querySelector('[data-selected="true"]') as HTMLElement;
      if (activeEl) {
        activeEl.scrollIntoView({ block: 'nearest' });
      }
    }
  }, [selectedIndex]);

  return (
    <AnimatePresence>
      {isOpen && (
        <div 
          onClick={(e) => { if (e.target === e.currentTarget) setIsOpen(false); }}
          className="fixed inset-0 z-[200] bg-background/80 backdrop-blur-sm flex items-start justify-center pt-[15vh] px-4"
        >
          <motion.div 
            initial={{ opacity: 0, scale: 0.95, y: -20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -20 }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="w-full max-w-2xl bg-card border border-border shadow-2xl rounded-2xl overflow-hidden flex flex-col relative"
          >
            {/* Input Area */}
            <div className="p-4 border-b border-border flex items-center gap-3">
              <Search className="w-5 h-5 text-muted-foreground" />
              <input 
                ref={inputRef}
                type="text" 
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type a command or search..."
                className="flex-1 bg-transparent border-none outline-none text-lg placeholder:text-muted-foreground"
              />
              <kbd className="hidden sm:inline-flex items-center gap-1 font-mono text-[10px] bg-background border border-border px-1.5 py-0.5 rounded text-muted-foreground">
                ESC
              </kbd>
            </div>

            {/* Results Area */}
            <div ref={listRef} className="max-h-[400px] overflow-y-auto p-2">
              {flatItems.length === 0 ? (
                <div className="p-8 text-center text-muted-foreground">
                  <p>No results found for "{search}"</p>
                </div>
              ) : (
                allItems.map((group) => (
                  <div key={group.heading} className="mb-4 last:mb-0">
                    <div className="px-3 py-2 text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                      {group.heading}
                    </div>
                    {group.items.map((item) => {
                      const globalIndex = flatItems.findIndex(i => i.id === item.id);
                      const isSelected = globalIndex === selectedIndex;
                      const Icon = item.icon;
                      
                      return (
                        <div
                          key={item.id}
                          data-selected={isSelected}
                          onMouseEnter={() => setSelectedIndex(globalIndex)}
                          onClick={() => executeItem(item)}
                          className={`flex items-center justify-between px-3 py-3 rounded-xl cursor-pointer transition-colors ${
                            isSelected ? 'bg-theme_blue/10 text-theme_blue' : 'hover:bg-border/50 text-foreground'
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            <Icon className={`w-4 h-4 ${isSelected ? 'text-theme_blue' : 'text-muted-foreground'}`} />
                            <span className="font-medium text-sm">{item.name}</span>
                          </div>
                          {isSelected && <ChevronRight className="w-4 h-4 text-theme_blue" />}
                        </div>
                      );
                    })}
                  </div>
                ))
              )}
            </div>

            {/* Footer */}
            <div className="p-3 bg-background border-t border-border flex items-center justify-between text-xs text-muted-foreground">
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1"><kbd className="bg-card border border-border px-1.5 rounded">↑</kbd><kbd className="bg-card border border-border px-1.5 rounded">↓</kbd> to navigate</span>
                <span className="flex items-center gap-1"><kbd className="bg-card border border-border px-1.5 rounded">↵</kbd> to select</span>
              </div>
              <div>
                AI Stock Platform
              </div>
            </div>
            
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};
