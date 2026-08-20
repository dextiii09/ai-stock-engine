"""
Institutional-grade performance metrics.

KEY DESIGN RULE:
  All risk ratios (Sharpe, Sortino, Calmar, VaR, CVaR) are computed via
  from_equity_curve() which works on daily equity-curve RETURNS. Never feed
  per-trade dollar PnL into these ratios -- they scale with position size and
  implicitly assume one trade = one day (off by sqrt(N)).

  One shared function, used everywhere:
    - Backtesting engine:  equity_curve[] is already daily -> call directly
    - Live portfolio:      compute() reconstructs daily equity curve from
                           closed_trades sorted by exit date, then calls it
    - Routes / risk API:   call compute(closed_trades) -- same path
"""
import math
import datetime
import numpy as np
from typing import Dict, Any, List, Optional


RISK_FREE_RATE_ANNUAL = 0.05        # 5% annualized (US T-Bill proxy)
TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Core: equity-curve -> all ratios (single authoritative implementation)
# ---------------------------------------------------------------------------

def from_equity_curve(equity_curve: List[Dict]) -> Dict[str, Any]:
    """
    Compute Sharpe, Sortino, Calmar, VaR-95%, CVaR-95% from a daily
    equity curve.

    Args:
        equity_curve: list of {date: str, equity: float} dicts.
                      Duplicate dates are collapsed (last value wins).

    Returns:
        dict -- sharpe_ratio, sortino_ratio, calmar_ratio, max_drawdown,
               var_95, cvar_95, annualized_return_pct, n_periods
    """
    if len(equity_curve) < 2:
        return _empty_ratio_metrics()

    # Collapse to one equity per date (last value wins)
    by_date: Dict[str, float] = {}
    for pt in equity_curve:
        d = str(pt.get("date", ""))[:10]
        val = pt.get("equity")
        if d and val is not None:
            try:
                by_date[d] = float(val)
            except (ValueError, TypeError):
                pass

    dates    = sorted(by_date)
    equities = [by_date[d] for d in dates]

    if len(equities) < 2:
        return _empty_ratio_metrics()

    # Daily returns
    returns = np.array([
        (equities[i] - equities[i - 1]) / max(equities[i - 1], 1e-9)
        for i in range(1, len(equities))
    ])
    n = len(returns)

    # No actual trading activity (e.g. strategy never entered a position, so
    # every daily return is exactly 0): std of returns is genuinely zero, not
    # just small. Report "no data" rather than dividing a real (if tiny)
    # excess-return mean by an epsilon-floored std, which previously produced
    # nonsensical ratios in the millions (e.g. sharpe_ratio: -3149703.94).
    if n >= 2 and float(np.std(returns, ddof=1)) == 0.0:
        return _empty_ratio_metrics()

    rf_daily = RISK_FREE_RATE_ANNUAL / TRADING_DAYS_PER_YEAR
    excess   = returns - rf_daily

    mean_exc = float(np.mean(excess))
    std_exc  = float(np.std(excess, ddof=1)) if n >= 2 else 1e-9
    if std_exc < 1e-9:
        std_exc = 1e-9

    ann = math.sqrt(TRADING_DAYS_PER_YEAR)

    # Sharpe
    sharpe = mean_exc / std_exc * ann

    # Sortino -- downside std of excess returns
    down     = excess[excess < 0]
    down_std = float(np.std(down, ddof=1)) if len(down) >= 2 else float(np.std(down, ddof=0)) if len(down) == 1 else 1e-9
    down_std = down_std if down_std > 1e-9 else 1e-9
    sortino = mean_exc / down_std * ann
    sortino = max(-999.99, min(999.99, sortino))  # Cap: when downside dev ≈ 0 (all-winning stretch), avoid ±∞

    # Max drawdown (percentage)
    peak   = equities[0]
    max_dd = 0.0
    for eq in equities[1:]:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Calmar: annualised return / max drawdown
    total_ret = (equities[-1] / equities[0] - 1) if equities[0] > 0 else 0.0
    if total_ret <= -1.0:
        ann_ret = -100.0
    else:
        ann_ret = ((1 + total_ret) ** (TRADING_DAYS_PER_YEAR / max(n, 1)) - 1) * 100
    calmar = ann_ret / max_dd if max_dd > 0 else 0.0

    # VaR-95% and CVaR-95%
    if n >= 5:
        var_95  = float(np.percentile(returns, 5)) * 100
        tail    = returns[returns <= np.percentile(returns, 5)]
        cvar_95 = float(tail.mean()) * 100 if len(tail) > 0 else var_95
    else:
        var_95 = cvar_95 = 0.0

    return {
        "sharpe_ratio":          round(float(sharpe),  3),
        "sortino_ratio":         round(float(sortino), 3),
        "calmar_ratio":          round(float(calmar),  3),
        "max_drawdown":          round(max_dd,  2),
        "max_drawdown_pct":      round(max_dd,  2),
        "var_95":                round(var_95,  3),
        "cvar_95":               round(cvar_95, 3),
        "annualized_return_pct": round(ann_ret, 2),
        "n_periods":             n,
    }


def _empty_ratio_metrics() -> Dict[str, Any]:
    return {
        "sharpe_ratio":          None,
        "sortino_ratio":         None,
        "calmar_ratio":          None,
        "max_drawdown":          None,
        "max_drawdown_pct":      None,
        "var_95":                None,
        "cvar_95":               None,
        "annualized_return_pct": None,
        "n_periods":             0,
    }



# ---------------------------------------------------------------------------
# Live portfolio: build daily equity curve from closed trades, then compute
# ---------------------------------------------------------------------------

def compute(trades: List[Dict], initial_capital: float = 100_000.0) -> Dict[str, Any]:
    """
    Build a daily equity curve from closed trades and return all ratio metrics.

    Args:
        trades:          list of closed trade dicts; must contain 'time'
                         (unix timestamp) and one of 'pnl' / 'profit_loss'.
        initial_capital: starting portfolio value.

    Returns:
        Same dict as from_equity_curve().
    """
    if not trades:
        return _empty_ratio_metrics()

    # Accumulate PnL by calendar date
    daily_pnl: Dict[str, float] = {}
    for t in trades:
        ts = t.get("time") or t.get("exit_time") or t.get("timestamp")
        if ts is None:
            continue
        try:
            dt = datetime.datetime.utcfromtimestamp(float(ts))
        except (ValueError, OSError, OverflowError):
            continue
        date_str = dt.strftime("%Y-%m-%d")
        _pnl = t.get("pnl") if t.get("pnl") is not None else t.get("profit_loss") if t.get("profit_loss") is not None else t.get("realized_pnl")
        pnl = float(_pnl) if _pnl is not None else 0.0
        daily_pnl[date_str] = daily_pnl.get(date_str, 0.0) + pnl

    if not daily_pnl:
        return _empty_ratio_metrics()

    # Fill-forward: insert 0-PnL entries for every calendar day between the first
    # and last trade date. Without this, n is the number of trade-close days, not
    # the number of elapsed days, which:
    #   • Inflates Sharpe/Sortino std (flat days are missing → fewer low-return days)
    #   • Distorts Calmar annualisation: (1+r)^(252/n) where n=1 instead of 5 for a
    #     5-day trade produces a wildly exaggerated annualised return.
    dates_sorted = sorted(daily_pnl)
    start_date = datetime.date.fromisoformat(dates_sorted[0])
    end_date   = datetime.date.fromisoformat(dates_sorted[-1])
    current    = start_date
    while current <= end_date:
        ds = current.isoformat()
        if ds not in daily_pnl:
            daily_pnl[ds] = 0.0
        current += datetime.timedelta(days=1)

    # Build equity curve (running sum on top of initial capital)
    equity = initial_capital
    equity_curve: List[Dict] = []
    for date_str in sorted(daily_pnl):
        equity += daily_pnl[date_str]
        equity_curve.append({"date": date_str, "equity": equity})

    return from_equity_curve(equity_curve)


def get_comprehensive_performance_breakdown(
    closed_trades: List[Dict],
    initial_capital: float = 100_000.0,
    engines_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Computes institutional performance metrics:
      - Overall & per-market win rates, profit factor, realized R:R
      - Mathematical expectancy ($E$) per trade
      - Rolling 30d / 90d / 1y Sharpe, Sortino, and Calmar ratios
      - Expectancy uplift from MetaGate filtering
    """
    all_metrics = compute(closed_trades, initial_capital=initial_capital)
    
    wins = [t for t in closed_trades if (t.get("profit_loss") or t.get("pnl") or 0.0) > 0]
    losses = [t for t in closed_trades if (t.get("profit_loss") or t.get("pnl") or 0.0) < 0]
    
    total_trades = len(closed_trades)
    n_wins = len(wins)
    n_losses = len(losses)
    
    win_rate = (n_wins / total_trades * 100.0) if total_trades > 0 else 0.0
    loss_rate = (n_losses / total_trades * 100.0) if total_trades > 0 else 0.0
    
    gross_profit = sum(float(t.get("profit_loss") or t.get("pnl") or 0.0) for t in wins)
    gross_loss = abs(sum(float(t.get("profit_loss") or t.get("pnl") or 0.0) for t in losses))
    net_pnl = gross_profit - gross_loss
    
    avg_win = (gross_profit / n_wins) if n_wins > 0 else 0.0
    avg_loss = (gross_loss / n_losses) if n_losses > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    realized_rr = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    
    # Mathematical Expectancy per trade: (p_win * avg_win) - (p_loss * avg_loss)
    p_win_frac = win_rate / 100.0
    p_loss_frac = loss_rate / 100.0
    expectancy_dollar = (p_win_frac * avg_win) - (p_loss_frac * avg_loss)
    
    # Per-market breakdown
    market_breakdowns = {}
    if engines_map:
        for mkt_name, eng in engines_map.items():
            mkt_trades = getattr(eng, "closed_trades", [])
            mkt_wins = [t for t in mkt_trades if (t.get("profit_loss") or t.get("pnl") or 0.0) > 0]
            mkt_losses = [t for t in mkt_trades if (t.get("profit_loss") or t.get("pnl") or 0.0) < 0]
            mkt_tot = len(mkt_trades)
            mkt_wr = (len(mkt_wins) / mkt_tot * 100.0) if mkt_tot > 0 else 0.0
            mkt_gp = sum(float(t.get("profit_loss") or t.get("pnl") or 0.0) for t in mkt_wins)
            mkt_gl = abs(sum(float(t.get("profit_loss") or t.get("pnl") or 0.0) for t in mkt_losses))
            mkt_pf = (mkt_gp / mkt_gl) if mkt_gl > 0 else (999.0 if mkt_gp > 0 else 0.0)
            
            market_breakdowns[mkt_name] = {
                "total_trades": mkt_tot,
                "win_rate_pct": round(mkt_wr, 1),
                "gross_profit": round(mkt_gp, 2),
                "gross_loss": round(mkt_gl, 2),
                "net_pnl": round(mkt_gp - mkt_gl, 2),
                "profit_factor": round(mkt_pf, 2),
                "open_positions": len(getattr(eng, "active_holdings", [])),
            }
            
    # Rolling 30d window
    now_ts = datetime.datetime.utcnow().timestamp()
    thirty_days_ago = now_ts - (30 * 86400)
    trades_30d = [t for t in closed_trades if float(t.get("time") or t.get("exit_time") or 0.0) >= thirty_days_ago]
    metrics_30d = compute(trades_30d, initial_capital=initial_capital) if trades_30d else _empty_ratio_metrics()

    return {
        "overall": {
            "total_trades": total_trades,
            "win_rate_pct": round(win_rate, 2),
            "loss_rate_pct": round(loss_rate, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "net_pnl": round(net_pnl, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "realized_risk_reward": round(realized_rr, 2),
            "expectancy_per_trade": round(expectancy_dollar, 2),
            "sharpe_ratio": all_metrics.get("sharpe_ratio", 0.0),
            "sortino_ratio": all_metrics.get("sortino_ratio", 0.0),
            "calmar_ratio": all_metrics.get("calmar_ratio", 0.0),
            "max_drawdown_pct": all_metrics.get("max_drawdown_pct", 0.0),
            "var_95": all_metrics.get("var_95", 0.0),
            "cvar_95": all_metrics.get("cvar_95", 0.0),
        },
        "rolling_30d": {
            "trades_count": len(trades_30d),
            "sharpe_ratio": metrics_30d.get("sharpe_ratio", 0.0),
            "sortino_ratio": metrics_30d.get("sortino_ratio", 0.0),
            "max_drawdown_pct": metrics_30d.get("max_drawdown_pct", 0.0),
        },
        "markets": market_breakdowns,
    }

