"""
Standalone weekly performance report for the AI Stock paper-trading experiment.

Run every Monday with the backend running:
    python weekly_report.py

What it does (mirrors the old scheduled Claude task):
  1. Fetches closed trades from all 5 market endpoints, dedupes by
     (symbol, time, profit_loss). If dedupe removes >0 trades, that may mean
     the 2026-07-20 aliasing bug regressed — it will warn loudly.
  2. Computes cumulative and this-week stats (n, win rate, avg win/loss,
     realized RR, expectancy/trade, total PnL), split USD vs INR.
  3. Computes the stop:target exit ratio (pre-fix baseline was 82:26, i.e.
     24% target share — the trailing-stop fix predicts this should rise).
  4. Reads per-engine RL stats (NOT just the US one) and reports counters.
     After the 2026-08-03 persistence fix, counters must CONTINUE across
     restarts — if any engine's total_closed_trades ever DROPS, the
     persistence bug is back.
  5. Appends a record to performance_log.json and prints the report with an
     honest trend verdict.

Experiment success criterion (agreed 2026-07): monthly expectancy per trade
improving month-over-month toward breakeven or better. Trend baseline is the
2026-07-20 "baseline v2" record — never compare against anything earlier.
Week-to-week changes on <30 trades are mostly noise.
"""

import json
import os
import sys
import time
import urllib.request
from datetime import date

BASE = "http://localhost:8080/api/v1"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "performance_log.json")

TRADE_ENDPOINTS = {
    "portfolio": "/portfolio/money-tracker",          # US futures
    "stocks":    "/stocks/portfolio/money-tracker",
    "crypto":    "/crypto/portfolio/money-tracker",
    "forex":     "/forex/portfolio/money-tracker",
    "indian":    "/indian/portfolio/money-tracker",   # INR!
}
RL_ENDPOINTS = {
    "US":     "/analytics/rl-stats",
    "STOCKS": "/stocks/analytics/rl-stats",
    "CRYPTO": "/crypto/analytics/rl-stats",
    "FOREX":  "/forex/analytics/rl-stats",
    "INDIA":  "/indian/analytics/rl-stats",
}


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode())


def stats(trades):
    n = len(trades)
    wins = [t["profit_loss"] for t in trades if t["profit_loss"] > 0]
    losses = [t["profit_loss"] for t in trades if t["profit_loss"] < 0]
    total = sum(t["profit_loss"] for t in trades)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": n - len(wins) - len(losses),
        "win_rate_pct": round(len(wins) / n * 100, 2) if n else 0.0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "realized_rr": round(abs(avg_win / avg_loss), 2) if avg_loss else 0.0,
        "expectancy_per_trade": round(total / n, 2) if n else 0.0,
        "total_pnl": round(total, 2),
    }


def main():
    # ── 1. Health check ────────────────────────────────────────────────────
    try:
        health = get("/health")
    except Exception as e:
        print(f"Backend not reachable at {BASE} ({e}). Start it and re-run.")
        sys.exit(1)

    stalled = [m for m, v in (health.get("engines") or {}).items()
               if v.get("status") not in ("ok", None)]
    if stalled:
        print(f"WARNING: engines not ok: {stalled} — their books may be stale.\n")

    # ── 2. Fetch + dedupe trades ───────────────────────────────────────────
    all_trades = []
    for src, ep in TRADE_ENDPOINTS.items():
        try:
            data = get(ep)
        except Exception as e:
            print(f"WARNING: {src} endpoint failed: {e}")
            continue
        for t in data.get("closed_trades", []):
            t["__src"] = src
            all_trades.append(t)

    seen, deduped = set(), []
    for t in all_trades:
        key = (t.get("symbol"), t.get("time"), t.get("profit_loss"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)
    removed = len(all_trades) - len(deduped)
    if removed > 0:
        print(f"*** ALIASING WARNING: dedupe removed {removed} of {len(all_trades)} "
              f"trades. The shared-DB-row bug may have REGRESSED. Investigate! ***\n")

    # ── 3. Previous run info ───────────────────────────────────────────────
    log = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            log = json.load(f)
    last_max_time = log[-1]["max_trade_time"] if log else 0

    new_trades = [t for t in deduped if t.get("time", 0) > last_max_time]
    inr = [t for t in deduped if t["__src"] == "indian"]
    usd = [t for t in deduped if t["__src"] != "indian"]
    wk_inr = [t for t in new_trades if t["__src"] == "indian"]
    wk_usd = [t for t in new_trades if t["__src"] != "indian"]

    # ── 4. Exit ratio (new trades) ─────────────────────────────────────────
    stop = target = other = 0
    for t in new_trades:
        r = (t.get("reason") or "").upper()
        if "STOP" in r:
            stop += 1
        elif "PROFIT" in r or "TARGET" in r:
            target += 1
        else:
            other += 1
    tgt_share = round(target / (stop + target) * 100, 1) if (stop + target) else 0.0

    # ── 5. RL stats per engine ─────────────────────────────────────────────
    rl = {}
    for mk, ep in RL_ENDPOINTS.items():
        try:
            d = get(ep)
            rl[mk] = {"total": d.get("total_closed_trades"),
                      "retrain": d.get("retrain_count"),
                      "win_rate": d.get("win_rate_pct")}
        except Exception as e:
            rl[mk] = {"error": str(e)}

    # Persistence regression check: counters must never DROP vs last run.
    prev_rl = (log[-1].get("rl_per_engine") or {}) if log else {}
    for mk, cur in rl.items():
        prev_total = (prev_rl.get(mk) or {}).get("total")
        if prev_total is not None and cur.get("total") is not None and cur["total"] < prev_total:
            print(f"*** RL PERSISTENCE WARNING: {mk} total_closed_trades dropped "
                  f"{prev_total} -> {cur['total']}. The restart-wipe bug "
                  f"(fixed 2026-08-03) may have REGRESSED. ***\n")

    # ── 6. Build record + append to log ────────────────────────────────────
    cumulative = stats(deduped)
    this_week = stats(new_trades)
    max_time = max((t.get("time", 0) for t in deduped), default=last_max_time)

    record = {
        "run_date": str(date.today()),
        "generated_by": "weekly_report.py (standalone)",
        "dedupe": {"raw": len(all_trades), "deduped": len(deduped), "removed": removed},
        "cumulative": {**cumulative, "currency": "MIXED INR+USD"},
        "cumulative_usd_only": stats(usd),
        "cumulative_inr_only": stats(inr),
        "this_week": {**this_week, "currency": "MIXED INR+USD"},
        "this_week_usd_only": stats(wk_usd),
        "this_week_inr_only": stats(wk_inr),
        "exit_ratio_this_week": {"stop": stop, "target": target,
                                 "other_committee_closes": other,
                                 "target_share_pct": tgt_share},
        "max_trade_time": max_time,
        "rl_per_engine": rl,
    }
    log.append(record)
    tmp = LOG_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, LOG_FILE)

    # ── 7. Print report ────────────────────────────────────────────────────
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    line = "-" * 62
    print(line)
    print(f"WEEKLY REPORT - {date.today()}  (paper trading, no real money)")
    print(line)
    print(f"This week:  {this_week['n']} trades | win rate {this_week['win_rate_pct']}% "
          f"| expectancy {this_week['expectancy_per_trade']}/trade (MIXED currency)")
    print(f"  USD-only: {record['this_week_usd_only']['n']} trades, "
          f"exp ${record['this_week_usd_only']['expectancy_per_trade']}/trade")
    print(f"  INR-only: {record['this_week_inr_only']['n']} trades, "
          f"exp Rs {record['this_week_inr_only']['expectancy_per_trade']}/trade")
    print(f"Cumulative: {cumulative['n']} trades | win rate {cumulative['win_rate_pct']}% "
          f"| expectancy {cumulative['expectancy_per_trade']}/trade | "
          f"PnL {cumulative['total_pnl']}")
    print(f"Exit ratio: stop {stop} : target {target} "
          f"(target share {tgt_share}% vs pre-fix 24%)")
    print(f"RL per engine: " + ", ".join(
        f"{mk}={v.get('total', '?')}" for mk, v in rl.items()))
    print(line)
    print("EXPECTANCY TREND (mixed currency, from 2026-07-20 baseline v2):")
    for rec in log:
        wk = rec.get("this_week", {})
        print(f"  {rec['run_date']}: {wk.get('expectancy_per_trade', '?'):>8} /trade "
              f"on {wk.get('n', '?')} trades")
    print(line)
    # Honest verdict
    weekly = [(r["run_date"], r["this_week"].get("expectancy_per_trade"))
              for r in log if r.get("this_week", {}).get("n", 0) >= 30]
    if len(weekly) >= 8:
        recent = [e for _, e in weekly[-4:]]
        early = [e for _, e in weekly[:4]]
        improving = sum(recent) / len(recent) > sum(early) / len(early)
        if improving and sum(recent) / len(recent) > -1.0:
            print("VERDICT: trend improving toward breakeven — keep going.")
        elif improving:
            print("VERDICT: improving but still clearly negative — learning may be "
                  "raising the floor, not the ceiling. Watch 4 more weeks.")
        else:
            print("VERDICT: no improving trend. If this persists past week 12, the "
                  "experiment's answer is NEGATIVE: RL reweighting is not enough; "
                  "the entry signals themselves need work.")
    else:
        print(f"VERDICT: only {len(weekly)} valid weeks so far — too early to call. "
              "Need 8+ weeks of 30+ trades for a real trend.")
    print("NOTE: this-week numbers under ~30 trades are mostly noise.")
    print(line)


if __name__ == "__main__":
    main()
