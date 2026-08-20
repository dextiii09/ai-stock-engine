"""
One-time migration — 2026-07-20 shared-DB-row bug.

BACKGROUND
----------
SmartExecutionEngine and ReinforcementLearningEngine inferred their market
with `"_st" in filename`. Since "portfolio_state.json", "portfolio_state_cx
.json" and "portfolio_state_fx.json" all contain "_st" (inside "_state"),
US / STOCKS / CRYPTO / FOREX all mapped to market="STOCKS" and shared one
portfolio row and one set of RLWeight rows. Books cross-contaminated
(forex held NVDA, crypto managed MSFT, etc.).

WHAT THIS DOES
--------------
1. Rebuilds every `portfolio` row from that engine's own JSON state file
   (the per-engine JSON files were never aliased — they are the last
   trustworthy per-market snapshot, written at shutdown).
2. Deletes all rl_weights rows (they were shared garbage; engines re-seed
   clean rows from their sanitized JSON state on next boot).
3. Strips rl_metadata from portfolio.state_data (synthetic-seed pollution;
   the RL engine's load-time sanitizer keeps only real trades anyway).

RUN WITH THE BACKEND SERVER STOPPED:
    cd backend
    python scripts/migrate_market_rows.py
"""
import json
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB   = os.path.join(BASE, "ai_stock.db")
DATA = os.path.join(BASE, "data")

FILES = {
    "US":     "portfolio_state.json",
    "STOCKS": "portfolio_state_st.json",
    "CRYPTO": "portfolio_state_cx.json",
    "FOREX":  "portfolio_state_fx.json",
    "INDIA":  "portfolio_state_in.json",
}


def main():
    if not os.path.exists(DB):
        print(f"DB not found: {DB} — nothing to migrate.")
        return

    con = sqlite3.connect(DB, timeout=5)
    cur = con.cursor()

    # Refuse to run against a live server (best effort: try exclusive lock)
    try:
        cur.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError:
        print("ERROR: database is locked — stop the backend server first.")
        sys.exit(1)

    # Pick an existing user_id (rows must reference a valid user)
    row = cur.execute("SELECT user_id FROM portfolio LIMIT 1").fetchone()
    user_id = row[0] if row else 1

    for market, fname in FILES.items():
        path = os.path.join(DATA, fname)
        if not os.path.exists(path):
            print(f"[{market}] no state file ({fname}) — deleting stale row if any")
            cur.execute("DELETE FROM portfolio WHERE market=?", (market,))
            continue
        with open(path) as f:
            state = json.load(f)
        payload = json.dumps({
            "active_holdings": state.get("active_holdings", []),
            "execution_logs":  state.get("execution_logs", [])[-500:],
            "closed_trades":   state.get("closed_trades", []),
            # rl_metadata intentionally omitted — RL restarts clean from
            # the sanitized rl_state JSON files.
        })
        cash = state.get("portfolio_balance", 0.0)
        existing = cur.execute(
            "SELECT id FROM portfolio WHERE market=?", (market,)).fetchone()
        if existing:
            cur.execute(
                "UPDATE portfolio SET cash=?, state_data=? WHERE market=?",
                (cash, payload, market))
            print(f"[{market}] row updated from {fname} (cash={cash:.2f}, "
                  f"closed={len(state.get('closed_trades', []))})")
        else:
            cur.execute(
                "INSERT INTO portfolio (user_id, market, cash, state_data) "
                "VALUES (?,?,?,?)", (user_id, market, cash, payload))
            print(f"[{market}] row created from {fname} (cash={cash:.2f})")

    n = cur.execute("SELECT COUNT(*) FROM rl_weights").fetchone()[0]
    cur.execute("DELETE FROM rl_weights")
    print(f"Deleted {n} shared/garbage rl_weights rows — engines re-seed on boot.")

    con.commit()
    con.close()
    print("Migration complete. Start the backend — per-engine sanitizers "
          "will strip any remaining foreign symbols from each book.")


if __name__ == "__main__":
    main()
