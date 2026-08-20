import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  User, Shield, Key, Bell, CreditCard, Activity, Cpu,
  CheckCircle2, AlertCircle, Save, Play, RefreshCw, Zap, TrendingUp
} from 'lucide-react';
import { API_BASE } from '../config';

const TABS = [
  { id: 'general',       name: 'General',            icon: User },
  { id: 'brokers',       name: 'Broker Connections',  icon: Key },
  { id: 'ai',            name: 'AI Engine',           icon: Cpu },
  { id: 'notifications', name: 'Notifications',       icon: Bell },
  { id: 'billing',       name: 'Billing',             icon: CreditCard },
];

const BROKER_MODES = [
  {
    id:    'paper',
    label: 'Paper Trading',
    desc:  'Simulated orders only. No real money at risk.',
    color: 'text-theme_green',
    bg:    'bg-theme_green/10 border-theme_green/30',
  },
  {
    id:    'zerodha',
    label: 'Zerodha (India)',
    desc:  'Live execution via Kite Connect API. NSE / BSE.',
    color: 'text-theme_blue',
    bg:    'bg-theme_blue/10 border-theme_blue/30',
  },
  {
    id:    'ibkr',
    label: 'Interactive Brokers',
    desc:  'Live execution via ib_insync. US equities and futures.',
    color: 'text-purple-400',
    bg:    'bg-purple-500/10 border-purple-500/30',
  },
];

const Toggle = ({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) => (
  <label className="relative inline-flex items-center cursor-pointer">
    <input
      type="checkbox"
      checked={checked}
      onChange={e => onChange(e.target.checked)}
      className="sr-only peer"
    />
    <div className="w-11 h-6 bg-border peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-theme_blue" />
  </label>
);

export const Settings = () => {
  const [activeTab,       setActiveTab]       = useState('brokers');
  const [isSaving,        setIsSaving]        = useState(false);
  const [upstoxConnected, setUpstoxConnected] = useState(false);

  // Broker mode
  const [brokerMode,   setBrokerMode]   = useState('paper');
  const [brokerMarket] = useState('US');
  const [brokerSaving, setBrokerSaving] = useState(false);
  const [brokerMsg,    setBrokerMsg]    = useState<string | null>(null);

  // Hyperopt
  const [hyperStatus,  setHyperStatus]  = useState<any>(null);
  const [hyperRunning, setHyperRunning] = useState(false);
  const [hyperMsg,     setHyperMsg]     = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/settings/broker`)
      .then(r => r.json())
      .then(d => { setBrokerMode(d.mode || 'paper'); })
      .catch(() => {});

    fetch(`${API_BASE}/hyperopt/status`)
      .then(r => r.json())
      .then(d => setHyperStatus(d))
      .catch(() => {});
  }, []);

  const saveBrokerMode = async (mode: string) => {
    setBrokerMode(mode);
    setBrokerSaving(true);
    setBrokerMsg(null);
    try {
      const r = await fetch(`${API_BASE}/settings/broker`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ mode, market: brokerMarket }),
      });
      const d = await r.json();
      setBrokerMsg(d.message || 'Broker mode saved.');
    } catch {
      setBrokerMsg('Error saving broker mode.');
    } finally {
      setBrokerSaving(false);
    }
  };

  const runHyperopt = async () => {
    setHyperRunning(true);
    setHyperMsg(null);
    try {
      const r = await fetch(`${API_BASE}/hyperopt/run`, { method: 'POST' });
      const d = await r.json();
      setHyperMsg(d.message || 'Optimization started.');
      setTimeout(() => {
        fetch(`${API_BASE}/hyperopt/status`)
          .then(r2 => r2.json())
          .then(d2 => setHyperStatus(d2))
          .catch(() => {});
        setHyperRunning(false);
      }, 3000);
    } catch {
      setHyperMsg('Error starting optimization.');
      setHyperRunning(false);
    }
  };

  const handleSave = () => {
    setIsSaving(true);
    setTimeout(() => setIsSaving(false), 1000);
  };

  const fmtTs = (ts: number | null | undefined) => {
    if (!ts) return 'Never';
    return new Date(ts * 1000).toLocaleString();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-8 pb-20">

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-6">
        <div>
          <h1 className="font-display text-4xl font-bold tracking-tight mb-2">Settings</h1>
          <p className="text-muted-foreground">Manage your account, API keys, and autonomous AI preferences.</p>
        </div>
        <button
          onClick={handleSave}
          className="bg-foreground text-background px-6 py-2.5 rounded-xl text-sm font-bold hover:bg-foreground/90 transition-all shadow-lg flex items-center justify-center gap-2 w-full md:w-auto"
        >
          {isSaving ? <Activity className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          {isSaving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>

      <div className="flex flex-col md:flex-row gap-8">

        {/* Sidebar Nav */}
        <div className="md:w-64 shrink-0">
          <nav className="flex flex-row md:flex-col gap-1 overflow-x-auto pb-2 md:pb-0">
            {TABS.map(tab => {
              const Icon     = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all whitespace-nowrap ${
                    isActive
                      ? 'bg-theme_blue/10 text-theme_blue'
                      : 'text-muted-foreground hover:bg-card hover:text-foreground'
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isActive ? 'text-theme_blue' : 'text-muted-foreground'}`} />
                  {tab.name}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Content Area */}
        <div className="flex-1 bg-card border border-border rounded-3xl p-6 sm:p-10 min-h-[500px]">
          <AnimatePresence mode="wait">

            {/* BROKERS TAB */}
            {activeTab === 'brokers' && (
              <motion.div
                key="brokers"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-8"
              >
                <div>
                  <h2 className="font-display text-2xl font-bold mb-1">Broker Connections</h2>
                  <p className="text-muted-foreground text-sm">
                    Connect your exchange accounts and choose an execution mode.
                  </p>
                </div>

                {/* Execution Mode Selector */}
                <div className="border border-border rounded-2xl p-6 bg-background space-y-4">
                  <div className="flex items-center gap-3 mb-2">
                    <Zap className="w-5 h-5 text-theme_blue" />
                    <h3 className="font-bold text-lg">Execution Mode</h3>
                    {brokerSaving && <Activity className="w-4 h-4 animate-spin text-muted-foreground" />}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Choose how the AI engine sends orders. Switch to a live broker only after setting credentials in your .env file.
                  </p>

                  <div className="grid sm:grid-cols-3 gap-3 mt-2">
                    {BROKER_MODES.map(m => {
                      const active = brokerMode === m.id;
                      return (
                        <button
                          key={m.id}
                          onClick={() => saveBrokerMode(m.id)}
                          className={`rounded-xl border p-4 text-left transition-all ${
                            active ? `${m.bg} border-2` : 'border-border hover:bg-border/30'
                          }`}
                        >
                          <div className={`text-sm font-bold mb-1 flex items-center gap-1.5 ${active ? m.color : 'text-foreground'}`}>
                            {m.label}
                            {active && <CheckCircle2 className="w-3.5 h-3.5" />}
                          </div>
                          <p className="text-xs text-muted-foreground leading-snug">{m.desc}</p>
                        </button>
                      );
                    })}
                  </div>

                  {brokerMsg && (
                    <p className={`text-xs mt-1 ${brokerMsg.startsWith('Error') ? 'text-theme_red' : 'text-theme_green'}`}>
                      {brokerMsg}
                    </p>
                  )}

                  {brokerMode !== 'paper' && (
                    <div className="mt-2 p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-start gap-2">
                      <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                      <p className="text-xs text-amber-300">
                        Live mode is active. Ensure API credentials are set in .env and the server has been restarted.
                      </p>
                    </div>
                  )}
                </div>

                {/* Upstox */}
                <div className="border border-border rounded-2xl p-6 bg-background relative overflow-hidden group">
                  <div className="absolute top-0 right-0 w-32 h-32 bg-purple-500/5 rounded-bl-full -z-10 group-hover:scale-110 transition-transform" />
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                    <div className="flex items-center gap-4">
                      <div className="w-12 h-12 bg-white rounded-xl flex items-center justify-center p-2 shrink-0">
                        <img
                          src="https://upstox.com/app/themes/upstox/assets/images/upstox-logo.svg"
                          alt="Upstox"
                          className="w-full"
                        />
                      </div>
                      <div>
                        <h3 className="font-bold text-lg flex items-center gap-2">
                          Upstox API
                          {upstoxConnected && (
                            <span className="bg-theme_green/10 text-theme_green text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full flex items-center gap-1">
                              <CheckCircle2 className="w-3 h-3" /> Connected
                            </span>
                          )}
                        </h3>
                        <p className="text-sm text-muted-foreground">Required for NSE/BSE execution.</p>
                      </div>
                    </div>
                    {upstoxConnected ? (
                      <button
                        onClick={() => setUpstoxConnected(false)}
                        className="px-4 py-2 bg-theme_red/10 text-theme_red hover:bg-theme_red/20 transition-colors rounded-xl text-sm font-bold border border-theme_red/20"
                      >
                        Disconnect
                      </button>
                    ) : (
                      <button
                        onClick={() => setUpstoxConnected(true)}
                        className="px-6 py-2 bg-foreground text-background hover:bg-foreground/90 transition-colors rounded-xl text-sm font-bold"
                      >
                        Connect Upstox
                      </button>
                    )}
                  </div>

                  {upstoxConnected && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      className="mt-6 pt-6 border-t border-border space-y-4"
                    >
                      <div className="grid sm:grid-cols-2 gap-4">
                        <div>
                          <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block mb-2">API Key</label>
                          <input
                            type="password"
                            value="************************"
                            readOnly
                            className="w-full bg-card border border-border rounded-xl px-4 py-2.5 text-sm font-mono text-muted-foreground"
                          />
                        </div>
                        <div>
                          <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block mb-2">API Secret</label>
                          <input
                            type="password"
                            value="************************"
                            readOnly
                            className="w-full bg-card border border-border rounded-xl px-4 py-2.5 text-sm font-mono text-muted-foreground"
                          />
                        </div>
                      </div>
                    </motion.div>
                  )}
                </div>

                {/* Binance */}
                <div className="border border-border rounded-2xl p-6 bg-background relative overflow-hidden group">
                  <div className="absolute top-0 right-0 w-32 h-32 bg-yellow-500/5 rounded-bl-full -z-10 group-hover:scale-110 transition-transform" />
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                    <div className="flex items-center gap-4">
                      <div className="w-12 h-12 bg-yellow-500 rounded-xl flex items-center justify-center p-2 shrink-0">
                        <svg viewBox="0 0 24 24" fill="black" className="w-6 h-6">
                          <path d="M12 24L0 12l12-12 12 12-12 12zm0-20.25L4.05 12 12 19.95 19.95 12 12 3.75zM12 16.5l-4.5-4.5 4.5-4.5 4.5 4.5-4.5 4.5z" />
                        </svg>
                      </div>
                      <div>
                        <h3 className="font-bold text-lg">Binance</h3>
                        <p className="text-sm text-muted-foreground">Required for Crypto execution.</p>
                      </div>
                    </div>
                    <button className="px-6 py-2 bg-card border border-border hover:bg-border/50 text-foreground transition-colors rounded-xl text-sm font-bold">
                      Connect
                    </button>
                  </div>
                </div>

                <div className="p-4 bg-theme_blue/5 border border-theme_blue/20 rounded-2xl flex items-start gap-3">
                  <Shield className="w-5 h-5 text-theme_blue shrink-0 mt-0.5" />
                  <div>
                    <h4 className="text-sm font-bold text-theme_blue mb-1">Bank-Level Security</h4>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      Your API keys are encrypted at rest using AES-256 and never leave our secure vault. We only request trading permissions, never withdrawal permissions.
                    </p>
                  </div>
                </div>
              </motion.div>
            )}

            {/* AI ENGINE TAB */}
            {activeTab === 'ai' && (
              <motion.div
                key="ai"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-8"
              >
                <div>
                  <h2 className="font-display text-2xl font-bold mb-1">AI Engine Parameters</h2>
                  <p className="text-muted-foreground text-sm">Fine-tune the autonomous trading brain.</p>
                </div>

                {/* Hyperparameter Optimization */}
                <div className="border border-border rounded-2xl p-6 bg-background space-y-5">
                  <div className="flex items-center justify-between flex-wrap gap-3">
                    <div className="flex items-center gap-3">
                      <TrendingUp className="w-5 h-5 text-theme_blue" />
                      <div>
                        <h3 className="font-bold text-base">Hyperparameter Auto-Optimization</h3>
                        <p className="text-xs text-muted-foreground">
                          Bayesian walk-forward search over RSI periods, EMA windows, conviction thresholds, and stop-loss multipliers. Runs monthly automatically.
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={runHyperopt}
                      disabled={hyperRunning}
                      className="flex items-center gap-2 px-5 py-2 bg-theme_blue text-white rounded-xl text-sm font-bold hover:bg-theme_blue/90 disabled:opacity-60 disabled:cursor-not-allowed transition-all"
                    >
                      {hyperRunning
                        ? <><RefreshCw className="w-4 h-4 animate-spin" /> Running...</>
                        : <><Play className="w-4 h-4" /> Run Now</>
                      }
                    </button>
                  </div>

                  {hyperMsg && (
                    <p className={`text-xs ${hyperMsg.startsWith('Error') ? 'text-theme_red' : 'text-theme_green'}`}>
                      {hyperMsg}
                    </p>
                  )}

                  {hyperStatus ? (
                    <>
                      <div className="grid sm:grid-cols-2 gap-3">
                        <div className="bg-card rounded-xl p-4 border border-border">
                          <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Status</p>
                          <p className={`text-sm font-bold capitalize ${
                            hyperStatus.running ? 'text-amber-400' : 'text-theme_green'
                          }`}>
                            {hyperStatus.running ? 'Running' : 'Idle'}
                          </p>
                        </div>
                        <div className="bg-card rounded-xl p-4 border border-border">
                          <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Last Run</p>
                          <p className="text-sm font-bold">{fmtTs(hyperStatus.last_run)}</p>
                        </div>
                        <div className="bg-card rounded-xl p-4 border border-border">
                          <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Best Score</p>
                          <p className="text-sm font-bold">
                            {hyperStatus.best_score != null ? hyperStatus.best_score.toFixed(3) : '--'}
                          </p>
                        </div>
                        <div className="bg-card rounded-xl p-4 border border-border">
                          <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Trials Complete</p>
                          <p className="text-sm font-bold">
                            {hyperStatus.total_trials > 0 ? `${hyperStatus.progress ?? 0} / ${hyperStatus.total_trials}` : '--'}
                          </p>
                        </div>
                      </div>

                      {hyperStatus.last_result && (
                        <div className="bg-card rounded-xl p-4 border border-border">
                          <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Best Parameters</p>
                          <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-1">
                            {Object.entries(hyperStatus.last_result as Record<string, number>).map(([k, v]) => (
                              <div key={k} className="flex justify-between text-xs py-0.5">
                                <span className="text-muted-foreground font-mono">{k}</span>
                                <span className="font-bold font-mono">
                                  {typeof v === 'number' ? v.toFixed(3) : String(v)}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="text-xs text-muted-foreground">No optimization data yet. Click Run Now to start.</p>
                  )}
                </div>

                {/* Risk + Toggles */}
                <div className="space-y-6">
                  <div className="space-y-3">
                    <div className="flex justify-between items-center">
                      <label className="text-sm font-bold">Risk Tolerance Profile</label>
                      <span className="text-xs bg-theme_blue/10 text-theme_blue px-2 py-1 rounded-md font-bold">Moderate (Default)</span>
                    </div>
                    <p className="text-xs text-muted-foreground">Determines position sizing and stop-loss tightness.</p>
                    <input
                      type="range"
                      min="1"
                      max="3"
                      defaultValue="2"
                      className="w-full accent-theme_blue h-2 bg-border rounded-lg appearance-none cursor-pointer"
                    />
                    <div className="flex justify-between text-xs font-medium text-muted-foreground">
                      <span>Conservative</span>
                      <span>Moderate</span>
                      <span>Aggressive</span>
                    </div>
                  </div>

                  <div className="h-px bg-border w-full" />

                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="font-bold text-sm mb-1">Auto-Retrain Models</h4>
                      <p className="text-xs text-muted-foreground">
                        Allow the XGBoost models to automatically retrain on your private trading history every weekend.
                      </p>
                    </div>
                    <Toggle checked={true} onChange={() => {}} />
                  </div>

                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="font-bold text-sm mb-1">Smart Money Filtering</h4>
                      <p className="text-xs text-muted-foreground">
                        Ignore signals if they contradict institutional order blocks (SMC).
                      </p>
                    </div>
                    <Toggle checked={true} onChange={() => {}} />
                  </div>

                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="font-bold text-sm mb-1">Multi-Timeframe Confluence Gate</h4>
                      <p className="text-xs text-muted-foreground">
                        Require daily and hourly trend alignment before executing tick-level signals. Reduces false positives.
                      </p>
                    </div>
                    <Toggle checked={true} onChange={() => {}} />
                  </div>
                </div>
              </motion.div>
            )}

            {/* PLACEHOLDER TABS */}
            {(activeTab === 'general' || activeTab === 'notifications' || activeTab === 'billing') && (
              <motion.div
                key="placeholder"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex flex-col items-center justify-center h-64 text-center"
              >
                <AlertCircle className="w-12 h-12 text-muted-foreground mb-4 opacity-50" />
                <h3 className="font-bold text-lg">Under Construction</h3>
                <p className="text-sm text-muted-foreground">This section is being developed in the next iteration.</p>
              </motion.div>
            )}

          </AnimatePresence>
        </div>
      </div>
    </div>
  );
};
