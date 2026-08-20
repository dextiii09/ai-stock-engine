import { Globe } from 'lucide-react';
import { MarketTabs, ALL_MARKET_TABS, useMarket } from '../components/MarketTabs';
import { Dashboard } from './Dashboard';

export const Markets = () => {
  const [market] = useMarket('US');

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12">

      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-tight flex items-center gap-3">
            <Globe className="w-9 h-9 text-theme_blue" />
            Markets
          </h1>
          <p className="text-muted-foreground mt-1">
            Live Command Center — switch tabs to explore each market.
          </p>
        </div>
        <MarketTabs tabs={ALL_MARKET_TABS} />
      </div>

      {/* All tabs render the full Dashboard Command Center for their market */}
      <Dashboard market={market as any} />
    </div>
  );
};
