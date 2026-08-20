import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Shell } from './components/layout/Shell';
import { Markets } from './pages/Markets';
import { Portfolio } from './pages/Portfolio';
import { Watchlist } from './pages/Watchlist';
import { Scanner } from './pages/Scanner';
import { AutoTrader } from './pages/AutoTrader';
import { Settings } from './pages/Settings';
import { Backtesting } from './pages/Backtesting';
import { News } from './pages/News';
import { SymbolDetail } from './pages/SymbolDetail';
import { Analytics } from './pages/Analytics';
import { MoneyTracker } from './pages/MoneyTracker';
import { SandboxTrader } from './pages/SandboxTrader';
import { BugFinder } from './pages/BugFinder';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Shell />}>
          {/* Redirect root to /markets */}
          <Route index element={<Navigate to="/markets" replace />} />

          {/* Feature pages — market selected via ?market=US|INDIA|STOCKS|CRYPTO|FOREX */}
          <Route path="markets"        element={<Markets />} />
          <Route path="portfolio"      element={<Portfolio />} />
          <Route path="autotrader"     element={<AutoTrader />} />
          <Route path="money-tracker"  element={<MoneyTracker />} />
          <Route path="analytics"      element={<Analytics />} />
          <Route path="backtesting"    element={<Backtesting />} />

          {/* Research & Tools */}
          <Route path="watchlist"      element={<Watchlist />} />
          <Route path="scanner"        element={<Scanner />} />
          <Route path="news"           element={<News />} />
          <Route path="sandbox"        element={<SandboxTrader />} />
          <Route path="bug-finder"     element={<BugFinder />} />
          <Route path="settings"       element={<Settings />} />
          <Route path="symbol/:ticker" element={<SymbolDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
