"""
One-time cleanup: remove cross-market legacy trades from each market's
portfolio state file.

Root cause being fixed: when the platform was split into 5 market engines,
portfolio_state_st.json / _cx.json / _fx.json were created as COPIES of the
original portfolio_state.json — so all of them inherited the same ~26 mixed
legacy closed trades (crypto + stocks + futures in every file). Result:
every market's money-tracker/win-rate stats were polluted by the same shared
history, and cross-market analytics triple-counted those trades.

What this does, per state file:
  * keeps only closed_trades whose symbol belongs to that engine's market
    (US: *=F futures | STOCKS: plain tickers | CRYPTO: *-USD | FOREX: *=X |
    INDIA: *.NS/*.BO)
  * drops obvious test artifacts (reason contains "Test")
  * filters execution_logs by the same symbol rule
  * does NOT touch portfolio_balance or active_holdings (live positions and
    cash are left exactly as they are)
  * writes a .pre_cleanup backup of every file it modifies

RUN ONLY WHILE THE SERVER IS STOPPED:
    stop_servers.bat
    cd E:\\Ai Stock\\backend
    python scripts\\cleanup_legacy_trades.py
    start_daemon.bat
"""
import json
import os
import shutil

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

FILES = {
    "portfolio_state.json":    "US",
    "portfolio_state_st.json": "STOCKS",
    "portfolio_state_cx.json": "CRYPTO",
    "portfolio_state_fx.json": "FOREX",
    "portfolio_state_in.json": "INDIA",
}


def belongs(symbol: str, market: str) -> bool:
    s = (symbol or "").upper()
    if market == "US":
        return s.endswith("=F")
    if market == "CRYPTO":
        return s.endswith("-USD")
    if market == "FOREX":
        return s.endswith("=X")
    if market == "INDIA":
        return s.endswith(".NS") or s.endswith(".BO")
    if market == "STOCKS":
        return s.isalpha()          # plain equity tickers (AAPL, NVDA, ...)
    return False


def main():
    for fname, market in FILES.items():
        path = os.path.join(DATA, fname)
        if not os.path.exists(path):
            print(f"[skip] {fname} (missing)")
            continue
        with open(path, encoding="utf-8") as f:
            state = json.load(f)

        ct = state.get("closed_trades", [])
        el = state.get("execution_logs", [])
        keep_ct = [t for t in ct
                   if belongs(t.get("symbol", ""), market)
                   and "test" not in str(t.get("reason", "")).lower()]
        keep_el = [e for e in el if belongs(e.get("symbol", ""), market)]

        if len(keep_ct) == len(ct) and len(keep_el) == len(el):
            print(f"[clean] {fname}: nothing to remove ({len(ct)} trades)")
            continue

        shutil.copy2(path, path + ".pre_cleanup")
        state["closed_trades"]  = keep_ct
        state["execution_logs"] = keep_el
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
        print(f"[fixed] {fname} ({market}): trades {len(ct)} -> {len(keep_ct)}, "
              f"exec_logs {len(el)} -> {len(keep_el)} "
              f"(backup: {fname}.pre_cleanup)")

    print("\nDone. Start the server again (start_daemon.bat). Each market's "
          "money-tracker now shows only its own trades.")


if __name__ == "__main__":
    main()
