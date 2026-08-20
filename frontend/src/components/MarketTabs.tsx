import React from 'react';
import { useSearchParams } from 'react-router-dom';

export type MarketKey = 'US' | 'INDIA' | 'STOCKS' | 'CRYPTO' | 'FOREX';

export interface MarketTab {
  key: MarketKey;
  label: string;
  emoji: string;
  accentColor: string;
}

export const TAB_US:     MarketTab = { key: 'US',     label: 'US',     emoji: '🌐', accentColor: 'blue' };
export const TAB_INDIA:  MarketTab = { key: 'INDIA',  label: 'Indian', emoji: '🌏', accentColor: 'orange' };
export const TAB_STOCKS: MarketTab = { key: 'STOCKS', label: 'Stocks', emoji: '📈', accentColor: 'sky' };
export const TAB_CRYPTO: MarketTab = { key: 'CRYPTO', label: 'Crypto', emoji: '₿',  accentColor: 'violet' };
export const TAB_FOREX:  MarketTab = { key: 'FOREX',  label: 'Forex',  emoji: '💱', accentColor: 'amber' };

export const ALL_MARKET_TABS:  MarketTab[] = [TAB_US, TAB_INDIA, TAB_STOCKS, TAB_CRYPTO, TAB_FOREX];
export const US_INDIA_TABS:    MarketTab[] = [TAB_US, TAB_INDIA];

const VALID_KEYS: MarketKey[] = ['US', 'INDIA', 'STOCKS', 'CRYPTO', 'FOREX'];

/** Hook to read/write the ?market= URL query param */
export function useMarket(defaultMarket: MarketKey = 'US'): [MarketKey, (m: MarketKey) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = (searchParams.get('market') ?? '').toUpperCase() as MarketKey;
  const market: MarketKey = VALID_KEYS.includes(raw) ? raw : defaultMarket;
  const setMarket = (m: MarketKey) => setSearchParams({ market: m }, { replace: true });
  return [market, setMarket];
}

/** Derive the correct API base URL for a given market */
export function getApiBase(market: MarketKey, baseUrl: string): string {
  switch (market) {
    case 'INDIA':  return `${baseUrl}/indian`;
    case 'STOCKS': return `${baseUrl}/stocks`;
    case 'CRYPTO': return `${baseUrl}/crypto`;
    case 'FOREX':  return `${baseUrl}/forex`;
    default:       return baseUrl;
  }
}

interface MarketTabsProps {
  tabs: MarketTab[];
  className?: string;
}

export const MarketTabs: React.FC<MarketTabsProps> = ({ tabs, className = '' }) => {
  const [market, setMarket] = useMarket(tabs[0]?.key ?? 'US');

  // Accent color map for active state ring
  const accentMap: Record<string, string> = {
    blue:   'bg-theme_blue border-theme_blue text-white shadow-theme_blue/20',
    orange: 'bg-orange-500 border-orange-500 text-white shadow-orange-500/20',
    sky:    'bg-sky-500 border-sky-500 text-white shadow-sky-500/20',
    violet: 'bg-violet-500 border-violet-500 text-white shadow-violet-500/20',
    amber:  'bg-amber-500 border-amber-500 text-white shadow-amber-500/20',
  };

  return (
    <div className={`flex flex-wrap gap-2 ${className}`}>
      {tabs.map(tab => {
        const isActive = market === tab.key;
        const activeClass = accentMap[tab.accentColor] ?? accentMap.blue;
        return (
          <button
            key={tab.key}
            onClick={() => setMarket(tab.key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl font-bold text-sm transition-all duration-200 border shadow-lg ${
              isActive
                ? `${activeClass}`
                : 'text-muted-foreground border-border hover:bg-card hover:text-foreground bg-background shadow-none'
            }`}
          >
            <span className="text-base leading-none">{tab.emoji}</span>
            <span>{tab.label}</span>
          </button>
        );
      })}
    </div>
  );
};
