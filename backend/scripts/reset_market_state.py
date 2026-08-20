"""
Reset a single market's on-disk JSON state to a clean, empty paper book.

WHY THIS EXISTS
---------------
The 2026-07-20 reset zeroed the live SQLite books and RL state but left the
per-market JSON state files untouched. `portfolio_state_fx.json` kept a stale
$78.5k balance / 5 holdings / 26 closed trades, and `risk_state_fx.json` kept a
weekly baseline of ~$98,714. On a restart *within the same ISO week*, the risk
manager reloaded that stale weekly baseline against live equity of $50k, saw a
phantom ~49% weekly drawdown, and halted forex for the whole week (WEEKLY_HALT).

`cleanup_legacy_trades.py` does NOT fix this: it filters trades by symbol, and
the forex phantom trades are legitimate `=X` symbols, so they pass the filter.
The problem is JSON drift from the (authoritative) reset DB, not cross-market
contamination — so this script reconciles the JSON side directly.

There is also a runtime guard in risk/portfolio_risk.py
(PortfolioRiskManager.STALE_BASELINE_DD) that clamps a persisted baseline sitting
implausibly far above live equity. This script is the explicit, offline
counterpart: use it whenever you reset a book so the JSON never drifts in the
first place.

WHAT IT DOES (per selected market)
----------------------------------
  * portfolio_state_<m>.json -> {balance, [], [], []}  (empty book)
  * risk_state_<m>.json      -> daily & weekly baselines set to `balance` for
                               today / the current ISO week
  * writes a timestamped .bak of every file it changes

RUN ONLY WHILE THE SERVER IS STOPPED:
    stop_servers.bat
    cd E:\\Ai Stock\\backend
    python scripts\\reset_market_state.py --market FOREX          # default $50,000
    python scripts\\reset_market_state.py --market ALL --balance 50000
    start_daemon.bat
"""
import argparse
import datetime
import json
import os
import shutil

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# market -> (portfolio_state file, risk_state file)
MARKETS = {
    "US":     ("portfolio_state.json",    "risk_state_us.json"),
    "STOCKS": ("portfolio_state_st.json", "risk_state_st.json"),
    "CRYPTO": ("portfolio_state_cx.json", "risk_state_cx.json"),
    "FOREX":  ("portfolio_state_fx.json", "risk_state_fx.json"),
    "INDIA":  ("portfolio_state_in.json", "risk_state_in.json"),
}


def _backup(path: str) -> None:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, f"{path}.bak-{stamp}")


def reset_market(market: str, balance: float) -> None:
    pf_name, risk_name = MARKETS[market]
    pf_path   = os.path.join(DATA, pf_name)
    risk_path = os.path.join(DATA, risk_name)

    # portfolio state -> empty book
    pf_clean = {
        "portfolio_balance": float(balance),
        "active_holdings":   [],
        "execution_logs":    [],
        "closed_trades":     [],
    }
    if os.path.exists(pf_path):
        _backup(pf_path)
    with open(pf_path, "w", encoding="utf-8") as f:
        json.dump(pf_clean, f, indent=2)

    # risk state -> baselines at `balance` for the current period
    today    = datetime.date.today()
    iso_week = list(today.isocalendar()[:2])
    risk_clean = {
        "daily_start_capital":  float(balance),
        "daily_reset_date":     str(today),
        "weekly_start_capital": float(balance),
        "weekly_reset_week":    iso_week,
    }
    if os.path.exists(risk_path):
        _backup(risk_path)
    with open(risk_path, "w", encoding="utf-8") as f:
        json.dump(risk_clean, f, indent=2)

    print(f"[reset] {market}: {pf_name} -> empty book @ {balance:.2f}; "
          f"{risk_name} -> baselines @ {balance:.2f} (day {today}, week {iso_week}). "
          f"Backups written.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Reset a market's JSON state to a clean book.")
    ap.add_argument("--market", required=True,
                    help="US | STOCKS | CRYPTO | FOREX | INDIA | ALL")
    ap.add_argument("--balance", type=float, default=50000.0,
                    help="Starting paper balance to reset to (default 50000).")
    args = ap.parse_args()

    target = args.market.upper()
    markets = list(MARKETS) if target == "ALL" else [target]
    for m in markets:
        if m not in MARKETS:
            raise SystemExit(f"Unknown market {m!r}. Choose from {list(MARKETS)} or ALL.")

    print("Reset market state — RUN ONLY WITH THE SERVER STOPPED.")
    for m in markets:
        reset_market(m, args.balance)
    print("\nDone. Restart the server (start_daemon.bat). The DB remains the "
          "source of truth; these JSONs now match a clean book instead of "
          "re-seeding stale trades if the DB is ever empty.")


if __name__ == "__main__":
    main()
