"""
One-shot repair: restore RL counters lost in the pre-2026-08-03 restart wipes.

Background: before the 2026-08-03 persistence fix, RL counters lived only in
RAM between graceful shutdowns — and server.log shows a graceful shutdown has
never actually run on this machine, so every restart silently reset
total_closed_trades / winning_trades / retrain_count to ~0. The trade BOOKS
persisted fine, so the true counts are recoverable: every closed trade with
time > the 2026-07-20 baseline (when RL was deliberately reset to zero) is a
trade the RL engine processed.

This script recounts per engine from backend/data/portfolio_state*.json
(hot-path-saved on every close, so current) and writes the counters back into
backend/data/rl_state*.json. Weights are NOT touched. _trade_history is left
as-is (it rebuilds organically; the Sharpe window warms up within ~5 trades).

On next server start, load_state's JSON-fresher rule (added 2026-08-03) sees
the higher JSON trade count and restores from it automatically.

USAGE — server MUST be stopped:
    python backend/scripts/restore_rl_counters.py
Then start the server and verify /api/v1/analytics/rl-stats continues from
the restored counts.
"""

import json
import os
import socket
import sys

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# RL counters were zeroed 2026-07-20; every close after this epoch was
# processed by RL. (= max_trade_time of the baseline-v2 performance_log record)
BASELINE_EPOCH = 1784539813.9008603

RETRAIN_INTERVAL = 5  # must match analytics/rl_engine.py

ENGINES = {
    "US":     ("portfolio_state.json",    "rl_state.json"),
    "INDIA":  ("portfolio_state_in.json", "rl_state_in.json"),
    "STOCKS": ("portfolio_state_st.json", "rl_state_st.json"),
    "CRYPTO": ("portfolio_state_cx.json", "rl_state_cx.json"),
    "FOREX":  ("portfolio_state_fx.json", "rl_state_fx.json"),
}


def server_running() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        return s.connect_ex(("127.0.0.1", 8080)) == 0
    finally:
        s.close()


def main():
    if server_running():
        print("REFUSING TO RUN: backend is up on :8080. It would overwrite the "
              "repair on its next trade close (and its in-memory counters would "
              "diverge from disk). Stop the server first, run this, restart.")
        sys.exit(1)

    for market, (pf_name, rl_name) in ENGINES.items():
        pf_path = os.path.join(DATA, pf_name)
        rl_path = os.path.join(DATA, rl_name)
        if not os.path.exists(pf_path) or not os.path.exists(rl_path):
            print(f"{market}: missing {pf_name if not os.path.exists(pf_path) else rl_name} — skipped.")
            continue

        with open(pf_path) as f:
            book = json.load(f)
        trades = book.get("closed_trades", [])

        # Dedupe defensively (same key as the weekly report), then filter to
        # post-baseline trades — exactly the set RL processed since its reset.
        seen, post = set(), []
        for t in trades:
            key = (t.get("symbol"), t.get("time"), t.get("profit_loss"))
            if key in seen:
                continue
            seen.add(key)
            if t.get("time", 0) > BASELINE_EPOCH:
                post.append(t)

        total = len(post)
        wins = sum(1 for t in post if t.get("profit_loss", 0) > 0)

        with open(rl_path) as f:
            state = json.load(f)
        old = state.get("total_closed_trades", 0)

        if old >= total:
            print(f"{market}: rl_state already has {old} >= recount {total} — left alone.")
            continue

        state["total_closed_trades"] = total
        state["winning_trades"] = wins
        state["retrain_count"] = total // RETRAIN_INTERVAL
        state["_trades_since_last_retrain"] = total % RETRAIN_INTERVAL

        tmp = rl_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, rl_path)
        print(f"{market}: {old} -> {total} trades ({wins} wins, "
              f"retrain_count {total // RETRAIN_INTERVAL}). Restored.")

    print("\nDone. Start the server; expect '[RL Engine] JSON snapshot is "
          "fresher than DB' in its output, then verify the rl-stats endpoints.")


if __name__ == "__main__":
    main()
