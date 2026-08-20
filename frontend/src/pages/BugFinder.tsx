import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bug, RefreshCw, Trash2, AlertTriangle, AlertCircle,
  Info, CheckCircle, Zap, Clock, ShieldAlert, Activity,
  Database, Cpu, X, ChevronDown, ChevronUp, Search
} from 'lucide-react';

import { API_BASE } from '../config';

const BASE = API_BASE;

// ─── types ──────────────────────────────────────────────────────────────────

interface Finding {
  id: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';
  category: 'SYNTAX' | 'LOGIC' | 'DATA' | 'RUNTIME' | 'RL';
  file: string;
  location: string;
  description: string;
  suggestion: string;
  timestamp: string;
}

interface Summary {
  total: number;
  counts: Record<string, number>;
  last_scan: string | null;
  last_runtime_check: string | null;
  scan_count: number;
}

// ─── constants ───────────────────────────────────────────────────────────────

const SEVERITY_CONFIG: Record<string, {
  label: string; color: string; bg: string; border: string; Icon: React.ElementType;
}> = {
  CRITICAL: { label: 'Critical', color: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/30',    Icon: AlertCircle   },
  HIGH:     { label: 'High',     color: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/30', Icon: AlertTriangle  },
  MEDIUM:   { label: 'Medium',   color: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', Icon: AlertTriangle  },
  LOW:      { label: 'Low',      color: 'text-blue-400',   bg: 'bg-blue-500/10',   border: 'border-blue-500/30',   Icon: Info          },
  INFO:     { label: 'Info',     color: 'text-gray-400',   bg: 'bg-gray-500/10',   border: 'border-gray-500/30',   Icon: Info          },
};

const CATEGORY_CONFIG: Record<string, { label: string; Icon: React.ElementType }> = {
  SYNTAX:  { label: 'Syntax',  Icon: Bug        },
  LOGIC:   { label: 'Logic',   Icon: Cpu        },
  DATA:    { label: 'Data',    Icon: Database   },
  RUNTIME: { label: 'Runtime', Icon: Activity   },
  RL:      { label: 'RL',      Icon: Zap        },
};

// ─── helpers ─────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return 'never';
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60)   return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

// ─── sub-components ──────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  const cfg = SEVERITY_CONFIG[severity] ?? SEVERITY_CONFIG.INFO;
  const { Icon } = cfg;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${cfg.color} ${cfg.bg} ${cfg.border}`}>
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  );
}

function CategoryBadge({ category }: { category: string }) {
  const cfg = CATEGORY_CONFIG[category] ?? { label: category, Icon: Bug };
  const { Icon } = cfg;
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border border-border bg-card text-muted-foreground">
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  );
}

function FindingCard({
  finding,
  onDismiss,
}: {
  finding: Finding;
  onDismiss: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className={`rounded-2xl border p-4 ${SEVERITY_CONFIG[finding.severity]?.border ?? 'border-border'} bg-card`}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          {/* header row */}
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <SeverityBadge severity={finding.severity} />
            <CategoryBadge category={finding.category} />
            <span className="text-[10px] text-muted-foreground ml-auto flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {timeAgo(finding.timestamp)}
            </span>
          </div>

          {/* file + location */}
          <p className="text-[11px] font-mono text-muted-foreground mb-1 truncate">
            <span className="text-foreground/70">{finding.file}</span>
            {finding.location && (
              <span className="text-muted-foreground"> → {finding.location}</span>
            )}
          </p>

          {/* description */}
          <p className="text-sm text-foreground leading-relaxed">
            {finding.description}
          </p>

          {/* suggestion (collapsible) */}
          {finding.suggestion && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="mt-2 flex items-center gap-1 text-xs text-theme_blue hover:underline"
            >
              {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {expanded ? 'Hide fix' : 'Show fix'}
            </button>
          )}
          {expanded && finding.suggestion && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              className="mt-2 p-3 rounded-xl bg-background border border-border text-xs text-muted-foreground leading-relaxed"
            >
              <span className="text-theme_green font-bold">Fix: </span>
              {finding.suggestion}
            </motion.div>
          )}
        </div>

        {/* dismiss */}
        <button
          onClick={() => onDismiss(finding.id)}
          className="shrink-0 p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-border/50 transition-colors"
          title="Dismiss this finding"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </motion.div>
  );
}

// ─── main page ───────────────────────────────────────────────────────────────

export const BugFinder: React.FC = () => {
  const [findings, setFindings]     = useState<Finding[]>([]);
  const [summary, setSummary]       = useState<Summary | null>(null);
  const [loading, setLoading]       = useState(true);
  const [scanning, setScanning]     = useState(false);
  const [filter, setFilter]         = useState<string>('ALL');
  const [catFilter, setCatFilter]   = useState<string>('ALL');
  const [search, setSearch]         = useState('');
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchData = useCallback(async () => {
    try {
      const [fRes, sRes] = await Promise.all([
        fetch(`${BASE}/ai-bugs`),
        fetch(`${BASE}/ai-bugs/summary`),
      ]);
      if (fRes.ok) {
        const d = await fRes.json();
        setFindings(d.findings ?? []);
      }
      if (sRes.ok) {
        setSummary(await sRes.json());
      }
      setLastRefresh(new Date());
    } catch {
      /* server may be starting */
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load + auto-refresh every 30s
  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const triggerScan = async () => {
    setScanning(true);
    try {
      await fetch(`${BASE}/ai-bugs/scan`, { method: 'POST' });
      // Give scanner a moment to run, then refresh
      await new Promise(r => setTimeout(r, 2500));
      await fetchData();
    } finally {
      setScanning(false);
    }
  };

  const dismiss = async (id: string) => {
    setFindings(prev => prev.filter(f => f.id !== id));
    await fetch(`${BASE}/ai-bugs/${id}`, { method: 'DELETE' });
  };

  const dismissAll = async () => {
    setFindings([]);
    await fetch(`${BASE}/ai-bugs`, { method: 'DELETE' });
    await fetchData();
  };

  // Filter + search
  const visible = findings.filter(f => {
    if (filter !== 'ALL' && f.severity !== filter) return false;
    if (catFilter !== 'ALL' && f.category !== catFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        f.description.toLowerCase().includes(q) ||
        f.file.toLowerCase().includes(q) ||
        f.location.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const allClear = !loading && findings.length === 0;

  return (
    <div className="space-y-6 max-w-5xl mx-auto">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Bug className="w-6 h-6 text-theme_blue" />
            AI Bug Finder
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Live scanner — watches all backend files and monitors runtime health.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {findings.length > 0 && (
            <button
              onClick={dismissAll}
              className="flex items-center gap-2 px-3 py-2 rounded-xl border border-border text-sm text-muted-foreground hover:text-foreground hover:bg-border/50 transition-colors"
            >
              <Trash2 className="w-4 h-4" />
              Clear all
            </button>
          )}
          <button
            onClick={triggerScan}
            disabled={scanning}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-theme_blue text-white text-sm font-bold hover:bg-theme_blue/80 disabled:opacity-50 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${scanning ? 'animate-spin' : ''}`} />
            {scanning ? 'Scanning…' : 'Scan Now'}
          </button>
        </div>
      </div>

      {/* ── Summary cards ───────────────────────────────────────────────── */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'] as const).map(sev => {
            const cfg   = SEVERITY_CONFIG[sev];
            const count = summary.counts[sev] ?? 0;
            const { Icon } = cfg;
            return (
              <button
                key={sev}
                onClick={() => setFilter(filter === sev ? 'ALL' : sev)}
                className={`rounded-2xl border p-4 text-left transition-all ${
                  filter === sev
                    ? `${cfg.bg} ${cfg.border} ring-2 ring-offset-1 ring-offset-background ring-current`
                    : 'bg-card border-border hover:bg-card/80'
                }`}
              >
                <div className={`flex items-center gap-1.5 mb-1 ${cfg.color}`}>
                  <Icon className="w-4 h-4" />
                  <span className="text-xs font-bold">{cfg.label}</span>
                </div>
                <p className={`text-2xl font-display font-bold ${cfg.color}`}>{count}</p>
              </button>
            );
          })}
        </div>
      )}

      {/* ── Scan metadata ───────────────────────────────────────────────── */}
      {summary && (
        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground bg-card border border-border rounded-2xl px-4 py-3">
          <span className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            Last static scan: <strong className="text-foreground">{timeAgo(summary.last_scan)}</strong>
          </span>
          <span className="flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5" />
            Last runtime check: <strong className="text-foreground">{timeAgo(summary.last_runtime_check)}</strong>
          </span>
          <span className="flex items-center gap-1.5">
            <RefreshCw className="w-3.5 h-3.5" />
            Total scans: <strong className="text-foreground">{summary.scan_count}</strong>
          </span>
          <span className="flex items-center gap-1.5 ml-auto">
            <Clock className="w-3.5 h-3.5" />
            UI refresh: <strong className="text-foreground">{timeAgo(lastRefresh.toISOString())}</strong>
            <span className="text-muted-foreground/50">(auto every 30s)</span>
          </span>
        </div>
      )}

      {/* ── Filters ─────────────────────────────────────────────────────── */}
      {!allClear && (
        <div className="flex flex-wrap items-center gap-3">
          {/* Category filter pills */}
          <div className="flex gap-2 flex-wrap">
            {(['ALL', 'SYNTAX', 'LOGIC', 'DATA', 'RUNTIME', 'RL'] as const).map(cat => (
              <button
                key={cat}
                onClick={() => setCatFilter(catFilter === cat ? 'ALL' : cat)}
                className={`px-3 py-1 rounded-full text-xs font-bold border transition-colors ${
                  catFilter === cat
                    ? 'bg-theme_blue text-white border-theme_blue'
                    : 'border-border text-muted-foreground hover:bg-border/50'
                }`}
              >
                {cat === 'ALL' ? 'All categories' : (CATEGORY_CONFIG[cat]?.label ?? cat)}
              </button>
            ))}
          </div>

          {/* Search */}
          <div className="relative ml-auto">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search findings…"
              className="pl-8 pr-3 py-1.5 rounded-xl border border-border bg-card text-sm placeholder-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-theme_blue w-48"
            />
          </div>
        </div>
      )}

      {/* ── Findings list ───────────────────────────────────────────────── */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 gap-4 text-muted-foreground">
          <RefreshCw className="w-8 h-8 animate-spin text-theme_blue" />
          <p className="text-sm">Running initial scan…</p>
        </div>
      ) : allClear ? (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex flex-col items-center justify-center py-24 gap-4"
        >
          <div className="w-20 h-20 rounded-full bg-theme_green/10 border border-theme_green/20 flex items-center justify-center">
            <CheckCircle className="w-10 h-10 text-theme_green" />
          </div>
          <h2 className="text-xl font-bold text-foreground">No bugs detected</h2>
          <p className="text-sm text-muted-foreground text-center max-w-sm">
            All backend files passed syntax, logic, and runtime checks. Scanner runs continuously — any new issue will appear here instantly.
          </p>
        </motion.div>
      ) : visible.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
          <ShieldAlert className="w-8 h-8" />
          <p className="text-sm">No findings match your current filters.</p>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Showing {visible.length} of {findings.length} finding{findings.length !== 1 ? 's' : ''}
          </p>
          <AnimatePresence mode="popLayout">
            {visible.map(f => (
              <FindingCard key={f.id} finding={f} onDismiss={dismiss} />
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
};
