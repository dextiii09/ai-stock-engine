"""
AI Bug Finder
=============
Continuously monitors the AI Stock Trading Platform for bugs while the system is live.

Checks performed:
  STATIC  — syntax errors, null bytes, truncation artifacts (on every file change)
  LOGIC   — missing fields, wrong formulas, dead agents, misconfigured dates
  DATA    — _filter_features essential-field coverage, symbol beta gaps
  RUNTIME — RL weight NaN/Inf, negative balances, server health, exception logs
"""

import ast
import hashlib
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

# ── paths ──────────────────────────────────────────────────────────────────────
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))   # .../backend/

# ── tunables ───────────────────────────────────────────────────────────────────
_FULL_SCAN_INTERVAL   = 300   # full static re-scan every 5 min
_WATCH_INTERVAL       = 20    # file-mtime poll every 20 s
_RUNTIME_INTERVAL     = 60    # runtime health poll every 60 s
_LOG_TAIL_LINES       = 200   # lines of server.log to inspect

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


# ══════════════════════════════════════════════════════════════════════════════
#  Finding
# ══════════════════════════════════════════════════════════════════════════════

class Finding:
    """A single detected issue."""

    def __init__(self, severity: str, category: str, file: str,
                 location: str, description: str, suggestion: str = "",
                 fid: str = None):
        raw = f"{file}|{location}|{description}"
        # fid ties the finding to the id used by _resolve(); without it a
        # finding stored under an auto-hash can never be resolved.
        self.id          = fid or hashlib.md5(raw.encode()).hexdigest()[:8]
        self.severity    = severity    # CRITICAL / HIGH / MEDIUM / LOW / INFO
        self.category    = category   # SYNTAX / LOGIC / DATA / RUNTIME / RL
        self.file        = file
        self.location    = location
        self.description = description
        self.suggestion  = suggestion
        self.timestamp   = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":          self.id,
            "severity":    self.severity,
            "category":    self.category,
            "file":        self.file,
            "location":    self.location,
            "description": self.description,
            "suggestion":  self.suggestion,
            "timestamp":   self.timestamp,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  AIBugFinder
# ══════════════════════════════════════════════════════════════════════════════

class AIBugFinder:

    def __init__(self, base_url: str = "http://127.0.0.1:8080/api/v1"):
        self.base_url           = base_url
        self._findings: Dict[str, Finding] = {}   # id → Finding (deduped)
        self._lock              = threading.Lock()
        self._file_mtimes: Dict[str, float] = {}
        self._running           = False
        self._thread: Optional[threading.Thread] = None
        self.last_scan_time: Optional[str]    = None
        self.last_runtime_time: Optional[str] = None
        self.scan_count         = 0

    # ── public API ─────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="ai-bug-finder")
        self._thread.start()

    def stop(self):
        self._running = False

    def trigger_scan(self):
        """Fire an immediate full scan (non-blocking)."""
        threading.Thread(target=self._full_static_scan, daemon=True).start()

    def get_findings(self) -> List[Dict]:
        with self._lock:
            items = list(self._findings.values())
        items.sort(key=lambda f: (
            SEVERITY_ORDER.index(f.severity) if f.severity in SEVERITY_ORDER else 99,
            f.timestamp
        ))
        return [f.to_dict() for f in items]

    def get_summary(self) -> Dict:
        with self._lock:
            counts = {s: 0 for s in SEVERITY_ORDER}
            for f in self._findings.values():
                counts[f.severity] = counts.get(f.severity, 0) + 1
        return {
            "total":              sum(counts.values()),
            "counts":             counts,
            "last_scan":          self.last_scan_time,
            "last_runtime_check": self.last_runtime_time,
            "scan_count":         self.scan_count,
        }

    def dismiss(self, finding_id: str):
        with self._lock:
            self._findings.pop(finding_id, None)

    def dismiss_all(self):
        with self._lock:
            self._findings.clear()

    # ── internal store helpers ─────────────────────────────────────────────────

    def _add(self, finding: Finding):
        with self._lock:
            self._findings[finding.id] = finding

    def _resolve(self, finding_id: str):
        """Remove a finding whose condition is now clean."""
        with self._lock:
            self._findings.pop(finding_id, None)

    @staticmethod
    def _fid(*parts: str) -> str:
        return hashlib.md5("|".join(parts).encode()).hexdigest()[:8]

    # ── main loop ──────────────────────────────────────────────────────────────

    def _loop(self):
        self._full_static_scan()
        self._runtime_scan()
        last_full    = time.monotonic()
        last_runtime = time.monotonic()

        while self._running:
            time.sleep(_WATCH_INTERVAL)
            self._watch_changed_files()
            now = time.monotonic()
            if now - last_full >= _FULL_SCAN_INTERVAL:
                self._full_static_scan()
                last_full = now
            if now - last_runtime >= _RUNTIME_INTERVAL:
                self._runtime_scan()
                last_runtime = now

    # ── file watcher ───────────────────────────────────────────────────────────

    def _watch_changed_files(self):
        for root, _, files in os.walk(BACKEND_DIR):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(root, fname)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if self._file_mtimes.get(path) != mtime:
                    self._file_mtimes[path] = mtime
                    self._scan_file(path)

    # ── full static scan ───────────────────────────────────────────────────────

    def _full_static_scan(self):
        self.scan_count  += 1
        self.last_scan_time = datetime.now().isoformat()

        for root, _, files in os.walk(BACKEND_DIR):
            for fname in files:
                if fname.endswith(".py"):
                    path = os.path.join(root, fname)
                    try:
                        self._file_mtimes[path] = os.path.getmtime(path)
                    except OSError:
                        pass
                    self._scan_file(path)

        # Cross-file logic checks
        self._check_essential_fields()
        self._check_symbol_beta_coverage()
        self._check_fomc_dates()

    # ══════════════════════════════════════════════════════════════════════════
    #  Per-file checks
    # ══════════════════════════════════════════════════════════════════════════

    def _scan_file(self, path: str):
        short = os.path.relpath(path, os.path.dirname(BACKEND_DIR)).replace("\\", "/")
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            return

        # ── 1. Null bytes (Edit-tool truncation artifact) ──────────────────────
        fid_null = self._fid(short, "null_bytes")
        if b"\x00" in raw:
            self._add(Finding(
                "CRITICAL", "SYNTAX", short, "entire file",
                "File contains null bytes — a sign of a truncated write by the Edit tool.",
                "Re-write the affected section from a clean copy."))
            return
        else:
            self._resolve(fid_null)

        # ── 2. Syntax check ────────────────────────────────────────────────────
        fid_syn = self._fid(short, "syntax")
        try:
            ast.parse(raw)
            self._resolve(fid_syn)
        except SyntaxError as e:
            self._add(Finding(
                "CRITICAL", "SYNTAX", short, f"line {e.lineno}",
                f"Syntax error: {e.msg}",
                "Fix this before starting the bot — the module will fail to import."))
            return

        src   = raw.decode("utf-8", errors="replace")
        fname = os.path.basename(path)

        # ── 3. File-specific logic checks ─────────────────────────────────────
        dispatch = {
            "smart_execution.py": self._check_force_close,
            "ingestion.py":       self._check_ingestion,
            "committee.py":       self._check_committee,
            "rl_engine.py":       self._check_rl_engine,
            "routes.py":          self._check_routes,
            "portfolio_risk.py":  self._check_portfolio_risk,
            "event_awareness.py": self._check_event_awareness,
        }
        if fname in dispatch:
            dispatch[fname](src, short)

    # ── smart_execution.py ─────────────────────────────────────────────────────

    def _check_force_close(self, src: str, short: str):
        fid_missing = self._fid(short, "force_close", "missing")
        if "def force_close" not in src:
            self._add(Finding("HIGH", "LOGIC", short, "SmartExecutionEngine",
                "force_close() method is missing — stop-loss and take-profit cannot be enforced.",
                "Add force_close(symbol, direction, reason) to SmartExecutionEngine.",
                fid=fid_missing))
            return
        else:
            self._resolve(fid_missing)

        # Slice to the end of the method (next def at same indent), not a
        # fixed char count — a fixed window cut the method off mid-body and
        # produced false "missing" findings.
        start = src.find("def force_close")
        nxt   = re.search(r"\n    (?:async )?def ", src[start + 10:])
        end   = start + 10 + nxt.start() if nxt else len(src)
        body  = src[start:end]

        fid_comm = self._fid(short, "force_close", "exit_comm")
        if "_exit_comm" in body:
            self._resolve(fid_comm)
        else:
            self._add(Finding("HIGH", "LOGIC", short, "force_close()",
                "Exit commission (_exit_comm) not deducted — forced-exit P&L is inflated by ~0.1%.",
                "Add: _exit_comm = shares * price * 0.001 before computing profit_loss.",
                fid=fid_comm))

        fid_stop = self._fid(short, "force_close", "stop_distance_pct")
        if "stop_distance_pct" in body:
            self._resolve(fid_stop)
        else:
            self._add(Finding("HIGH", "LOGIC", short, "force_close()",
                "stop_distance_pct missing from trade_result — RL R-multiple reward will always be 0 on forced exits.",
                "Compute _stop_dist_pct and include stop_distance_pct in the trade_result dict.",
                fid=fid_stop))

    # ── ingestion.py ───────────────────────────────────────────────────────────

    def _check_ingestion(self, src: str, short: str):
        idx = src.find("def run_feature_selection")
        if idx == -1:
            return
        body = src[idx: idx + 5000]

        # RSI formula
        fid_rsi = self._fid(short, "run_feature_selection", "rsi_wilder")
        uses_wilder = "_compute_rsi" in body or ("ewm" in body and "rsi" in body.lower())
        uses_sma    = "rolling" in body and "rsi" in body.lower() and not uses_wilder
        if uses_wilder:
            self._resolve(fid_rsi)
        elif uses_sma:
            self._add(Finding("MEDIUM", "LOGIC", short, "run_feature_selection() — RSI",
                "RSI uses SMA rolling window, not Wilder's exponential smoothing — creates a training/live mismatch.",
                "Replace with: _compute_rsi() or ewm-based Wilder formula.", fid=fid_rsi))

        # MACD formula
        fid_macd = self._fid(short, "run_feature_selection", "macd_hist")
        if "macd_hist" in body and "ewm" in body:
            self._resolve(fid_macd)
        elif "macd" in body.lower() and "macd_hist" not in body:
            self._add(Finding("MEDIUM", "LOGIC", short, "run_feature_selection() — MACD",
                "MACD stored as the MACD line, not the histogram — training/live mismatch.",
                "Compute: _ml = ema12 - ema26; macd_hist = _ml - _ml.ewm(span=9, adjust=False).mean()",
                fid=fid_macd))

    # ── committee.py ───────────────────────────────────────────────────────────

    def _check_committee(self, src: str, short: str):
        fid = self._fid(short, "IndianInstitutionalFlowAgent")
        if "IndianInstitutionalFlowAgent" in src:
            self._resolve(fid)
        else:
            self._add(Finding("HIGH", "LOGIC", short, "Indian committee",
                "IndianInstitutionalFlowAgent class missing — India bot has no institutional flow signal.",
                "Add IndianInstitutionalFlowAgent using nifty_3d_return as FII proxy.", fid=fid))

        fid2 = self._fid(short, "IndianMasterAgent")
        if "IndianMasterAgent" in src or "indian" in short.lower():
            # IndianMasterAgent lives in master.py, check that file instead
            self._resolve(fid2)

    # ── rl_engine.py ───────────────────────────────────────────────────────────

    def _check_rl_engine(self, src: str, short: str):
        fid = self._fid(short, "stop_distance_pct")
        if "stop_distance_pct" in src:
            self._resolve(fid)
        else:
            self._add(Finding("MEDIUM", "LOGIC", short, "reward calculation",
                "stop_distance_pct not referenced — R-multiple reward component may be disabled.",
                "Use: r_multiple = pnl_pct / stop_distance_pct in the reward function.", fid=fid))

    # ── routes.py ──────────────────────────────────────────────────────────────

    def _check_routes(self, src: str, short: str):
        fid = self._fid(short, "feature_selection_loop")
        # Good: loop over data_engine.symbols; Bad: only hardcoded symbol strings
        has_loop = bool(re.search(
            r'for\s+\w+\s+in\s+(?:data_engine|data_engine_in)\.symbols',
            src))
        if has_loop:
            self._resolve(fid)
        elif re.search(r'run_feature_selection,\s*["\']MGC=F["\']', src):
            self._add(Finding("MEDIUM", "LOGIC", short, "periodic feature selection",
                "Feature selection only retrains hardcoded symbols, not all data_engine.symbols.",
                "Use: for _sym in data_engine.symbols: await asyncio.to_thread(data_engine.run_feature_selection, _sym)",
                fid=fid))

    # ── portfolio_risk.py ──────────────────────────────────────────────────────

    def _check_portfolio_risk(self, src: str, short: str):
        expected = [
            "MNQ=F", "MGC=F", "MES=F", "MCL=F", "M2K=F",
            "NIFTYBEES.NS", "BANKBEES.NS", "GOLDBEES.NS", "JUNIORBEES.NS",
            "WIPRO.NS", "RELIANCE.NS", "TCS.NS", "INFY.NS",
            "HDFCBANK.NS", "ICICIBANK.NS", "ONGC.NS",
        ]
        missing = [s for s in expected if s not in src]
        fid = self._fid(short, "INSTRUMENT_BETAS", "coverage")
        if missing:
            self._add(Finding("LOW", "DATA", short, "INSTRUMENT_BETAS",
                f"Missing beta values for: {missing}. Portfolio beta defaults to 1.0.",
                "Add each symbol to INSTRUMENT_BETAS with its approximate equity beta.", fid=fid))
        else:
            self._resolve(fid)

    # ── event_awareness.py ─────────────────────────────────────────────────────

    def _check_event_awareness(self, src: str, short: str):
        wrong_dates = {
            "2026-06-30": "June 30 2026 is not an FOMC date — correct July date is 28-29.",
            "2026-07-01": "July 1 2026 is not an FOMC date — correct July date is 28-29.",
        }
        for date_str, msg in wrong_dates.items():
            fid = self._fid(short, "FOMC_DATES", date_str)
            if date_str in src:
                self._add(Finding("MEDIUM", "LOGIC", short, "FOMC_DATES_2025",
                    f"Wrong FOMC date present: {date_str}. {msg}",
                    f"Remove {date_str} and replace with the correct date.", fid=fid))
            else:
                self._resolve(fid)

    # ══════════════════════════════════════════════════════════════════════════
    #  Cross-file checks
    # ══════════════════════════════════════════════════════════════════════════

    def _check_essential_fields(self):
        """Verify _filter_features essential list covers all fields agents need."""
        path  = os.path.join(BACKEND_DIR, "data", "ingestion.py")
        short = "backend/data/ingestion.py"
        required = [
            "india_vix_level", "nifty_3d_return", "nifty_above_20ema",
            "usdinr_momentum", "usdinr_value",
            "volume_z", "is_rollover_week", "is_london_fix_window",
        ]
        try:
            with open(path, encoding="utf-8") as f:
                src = f.read()
        except OSError:
            return

        fid = self._fid(short, "_filter_features", "essential_coverage")
        idx = src.find("essential = [")
        if idx == -1:
            self._add(Finding("CRITICAL", "DATA", short, "_filter_features()",
                "essential = [...] list not found — all metadata / India macro fields will be stripped silently.",
                "Add an essential list in _filter_features() covering all non-active fields that agents require.",
                fid=fid))
            return

        block   = src[idx: src.find("]", idx)]
        missing = [f for f in required if f not in block]
        if missing:
            self._add(Finding("CRITICAL", "DATA", short, "_filter_features() — essential list",
                f"Fields missing from essential list: {missing}. Agents will receive defaults (0 / None) for these.",
                "Add the missing field names to the essential = [...] list.", fid=fid))
        else:
            self._resolve(fid)

    def _check_symbol_beta_coverage(self):
        """Every tradeable symbol in ingestion.py should appear in INSTRUMENT_BETAS."""
        ing_path  = os.path.join(BACKEND_DIR, "data",  "ingestion.py")
        risk_path = os.path.join(BACKEND_DIR, "risk",  "portfolio_risk.py")
        fid = self._fid("portfolio_risk.py", "INSTRUMENT_BETAS", "sym_vs_ingestion")
        try:
            with open(ing_path,  encoding="utf-8") as f: ing_src  = f.read()
            with open(risk_path, encoding="utf-8") as f: risk_src = f.read()
        except OSError:
            return

        syms    = set(re.findall(r'"([A-Z0-9]+=F|[A-Z0-9]+\.NS)"', ing_src))
        missing = [s for s in syms if s not in risk_src]
        if missing:
            self._add(Finding("LOW", "DATA",
                "backend/risk/portfolio_risk.py", "INSTRUMENT_BETAS",
                f"Symbols from ingestion.py not in INSTRUMENT_BETAS: {missing}. Beta defaults to 1.0.",
                "Add each symbol with its approximate equity/futures beta.", fid=fid))
        else:
            self._resolve(fid)

    def _check_fomc_dates(self):
        """Delegate to per-file check (avoids duplication)."""
        path  = os.path.join(BACKEND_DIR, "data", "event_awareness.py")
        short = "backend/data/event_awareness.py"
        try:
            with open(path, encoding="utf-8") as f:
                src = f.read()
        except OSError:
            return
        self._check_event_awareness(src, short)

    # ══════════════════════════════════════════════════════════════════════════
    #  Runtime health checks
    # ══════════════════════════════════════════════════════════════════════════

    def _runtime_scan(self):
        self.last_runtime_time = datetime.now().isoformat()
        try:
            import requests as _req
        except ImportError:
            return

        self._rt_server_health(_req)
        self._rt_rl_weights(_req)
        self._rt_portfolio_balance(_req)
        self._rt_log_exceptions()

    _NO_PROXY = {"http": None, "https": None}   # never route loopback via env proxies

    def _rt_server_health(self, req):
        fid = self._fid("runtime", "server", "health")
        try:
            r = req.get(f"{self.base_url}/health", timeout=5, proxies=self._NO_PROXY)
            if r.status_code == 200:
                self._resolve(fid)
            else:
                self._add(Finding("HIGH", "RUNTIME", "api/server.py", "GET /health",
                    f"/health returned HTTP {r.status_code}.",
                    "Check uvicorn logs for startup errors.", fid=fid))
        except Exception:
            self._add(Finding("CRITICAL", "RUNTIME", "api/server.py", "FastAPI server",
                "Cannot reach backend on port 8080 — server may be down.",
                "Start: cd backend && python -m uvicorn api.server:app --port 8080",
                fid=fid))

    # IV&V finding 2026-08-21: both runtime checks below previously only
    # covered US (and, for balance, India) — Stocks/Crypto/Forex had ZERO
    # runtime monitoring from this tool, the same 3-market blind spot as the
    # market_name bug (Finding #1 in the audit). A negative balance or
    # NaN/Inf RL weight in those 3 markets would have gone completely
    # undetected by the "AI Bug Finder" that's supposed to catch exactly
    # this. Read-only diagnostic checks — low risk to extend.
    _MARKET_PREFIXES = [
        ("", "US", ""), ("/indian", "India", "_in"), ("/stocks", "Stocks", "_st"),
        ("/crypto", "Crypto", "_cx"), ("/forex", "Forex", "_fx"),
    ]  # (url_prefix, label, rl_state_file_suffix) — suffixes match SmartExecutionEngine's actual filenames

    def _rt_rl_weights(self, req):
        for prefix, label, suffix in self._MARKET_PREFIXES:
            try:
                r = req.get(f"{self.base_url}{prefix}/analytics/rl-stats", timeout=5, proxies=self._NO_PROXY)
                if r.status_code != 200:
                    continue
                weights = r.json().get("weights", {})
                for regime, agent_map in weights.items():
                    if not isinstance(agent_map, dict):
                        continue
                    for agent, w in agent_map.items():
                        fid = self._fid("runtime", "rl_weight", label, regime, agent)
                        bad = (w is None
                               or (isinstance(w, float) and (w != w or abs(w) == float("inf"))))
                        if bad:
                            self._add(Finding("HIGH", "RL",
                                "analytics/rl_engine.py", f"{label} weights[{regime}][{agent}]",
                                f"RL weight NaN/Inf for agent '{agent}' in regime '{regime}' ({label}).",
                                f"Delete rl_state{suffix}.json to reset weights to uniform.", fid=fid))
                        else:
                            self._resolve(fid)
            except Exception:
                pass

    def _rt_portfolio_balance(self, req):
        for prefix, label, _suffix in self._MARKET_PREFIXES:
            fid = self._fid("runtime", "balance", label)
            try:
                r = req.get(f"{self.base_url}{prefix}/portfolio/holdings", timeout=5, proxies=self._NO_PROXY)
                if r.status_code != 200:
                    continue
                balance = r.json().get("balance", 1)
                if isinstance(balance, (int, float)) and balance < 0:
                    self._add(Finding("CRITICAL", "RUNTIME",
                        "execution/smart_execution.py", f"{label} balance",
                        f"{label} portfolio balance is negative: {balance:.2f}.",
                        "Inspect force_close() commission and P&L calculation.", fid=fid))
                else:
                    self._resolve(fid)
            except Exception:
                pass

    def _rt_log_exceptions(self):
        """Scan the last N lines of server.log for uncaught exceptions."""
        log_path = os.path.join(BACKEND_DIR, "server.log")
        fid      = self._fid("runtime", "server_log", "exception")
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                lines  = f.readlines()
            recent = lines[-_LOG_TAIL_LINES:]
            errors = [l.strip() for l in recent
                      if any(kw in l for kw in ("Traceback", "ERROR", "Exception", "CRITICAL"))]
            if errors:
                sample = errors[-1][:250]
                self._add(Finding("HIGH", "RUNTIME", "backend/server.log",
                    f"recent log (last {_LOG_TAIL_LINES} lines)",
                    f"Exception detected in server.log: {sample}",
                    "Open server.log for the full traceback.", fid=fid))
            else:
                self._resolve(fid)
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  Singleton accessor
# ══════════════════════════════════════════════════════════════════════════════

_instance: Optional[AIBugFinder] = None
_instance_lock = threading.Lock()


def get_bug_finder() -> AIBugFinder:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AIBugFinder()
    return _instance


def start_bug_finder() -> AIBugFinder:
    finder = get_bug_finder()
    finder.start()
    return finder
