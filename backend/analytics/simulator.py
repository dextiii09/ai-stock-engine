"""
Monte Carlo Trade Simulator — GBM with realized-win-rate drift.

Why drift matters:
  The original mu=0.0 (zero-drift GBM) produces P(TP first) = SL/(SL+TP)
  analytically, which is 0.375 for our 1.5/2.5 ATR barrier pair. The EV is
  exactly 0 before slippage → the gate either vetoes every trade (barely) or
  passes all of them. It cannot distinguish a good setup from a bad one.

  Fix: parameterise mu_daily with the engine's realized win rate (p_win).
  Using the logit of p_win scaled by σ/steps gives a drift whose magnitude
  correctly inflates win probability when the system has edge and deflates it
  when win rate is below breakeven. The gate now tightens automatically in
  losing streaks and loosens during winning runs.
"""
import math
import numpy as np
import yfinance as yf
from typing import Dict, Any, Optional, Tuple

_VOL_CACHE: Dict[str, Tuple[float, float]] = {}  # symbol -> (sigma, fetched_at)
_VOL_TTL_SECONDS = 3600.0  # H-5: invalidate after 1 hour


def _get_historical_vol(symbol: str) -> float:
    """Compute annualised daily-return volatility from 30 days of real closes.
    H-5: Cache entries expire after 1 hour so intraday vol events are reflected.
    """
    import time as _time
    now = _time.time()
    if symbol in _VOL_CACHE:
        sigma, fetched_at = _VOL_CACHE[symbol]
        if now - fetched_at < _VOL_TTL_SECONDS:
            return sigma
    # IV&V H3: prefer the shared, cached, rate-limited data provider over a
    # second yfinance client so we don't duplicate network calls. This function
    # is now only invoked from a worker thread (simulate() is called via
    # asyncio.to_thread in the engine), so the request no longer blocks the loop.
    df = None
    try:
        from data.provider import DataProviderFactory
        df = DataProviderFactory.get_provider().get_historical_ohlcv(
            symbol=symbol, period="30d", interval="1d"
        )
    except Exception:
        df = None
    if df is None or len(df) < 5:
        try:
            df = yf.Ticker(symbol).history(period="30d", interval="1d")
        except Exception:
            df = None
    try:
        if df is not None and len(df) >= 5:
            returns = df["Close"].pct_change().dropna()
            sigma = float(returns.std()) * np.sqrt(252)
            _VOL_CACHE[symbol] = (max(0.01, sigma), now)
            return _VOL_CACHE[symbol][0]
    except Exception:
        pass
    return 0.25  # Market-average annual vol as last resort


def _win_rate_to_daily_drift(p_win: float, daily_vol: float, steps: int) -> float:
    """
    LEGACY (kept for reference): symmetric-barrier logit approximation.
    At p_win = 0.5 it returns mu = 0, which is only correct when TP and SL are
    EQUIDISTANT. With the engine's asymmetric barriers (TP ≈ 2.5 ATR vs
    SL ≈ 1.5 ATR), a 50% realized win rate is a strongly POSITIVE edge
    (EV = 0.5*2.5R − 0.5*1.5R = +0.5R), yet zero drift makes the GBM hit the
    nearer stop first ~62% of the time → EV ≈ 0 → the gate vetoed nearly every
    trade. Superseded by _calibrate_drift_asymmetric().
    """
    p = float(np.clip(p_win, 0.05, 0.95))
    logit_p = math.log(p / (1.0 - p))
    return daily_vol * logit_p / max(steps, 1)


def _calibrate_drift_asymmetric(
    p_win: float,
    daily_vol: float,
    current_price: float,
    stop_loss: float,
    take_profit: float,
    direction: str = "LONG",
) -> float:
    """
    Solve for the GBM drift mu such that the model's P(hit TP before SL)
    EQUALS the realized win rate, honoring the ACTUAL barrier distances.

    First-passage of Brownian motion with drift nu and vol sigma between a win
    barrier at log-distance +w and a loss barrier at log-distance -l:

        P(win first) = (e^{theta*l} - 1) / (e^{theta*l} - e^{-theta*w}),
        theta = 2*nu / sigma^2

    (limit theta->0 gives the classic l/(l+w) zero-drift result). We bisect on
    theta — P is strictly increasing in theta — then return
    mu = nu + sigma^2/2 (simulate() subtracts the Ito term back out).
    For SHORT trades the barrier geometry is mirrored, so the drift sign flips.
    """
    p = float(np.clip(p_win, 0.05, 0.95))
    sigma2 = max(daily_vol, 1e-6) ** 2

    # Log-space barrier distances (always positive)
    if direction == "LONG":
        w = abs(math.log(max(take_profit, 1e-12) / current_price))  # win barrier above
        l = abs(math.log(max(stop_loss,  1e-12) / current_price))   # loss barrier below
    else:  # SHORT: win barrier below, loss barrier above — mirror the geometry
        w = abs(math.log(max(take_profit, 1e-12) / current_price))
        l = abs(math.log(max(stop_loss,  1e-12) / current_price))

    if w <= 0 or l <= 0:
        return 0.0

    def p_win_first(theta: float) -> float:
        if abs(theta) < 1e-12:
            return l / (l + w)
        # Guard against overflow: theta*(w+l) capped by bisection range below
        return (math.exp(theta * l) - 1.0) / (math.exp(theta * l) - math.exp(-theta * w))

    # Bisection on theta; range wide enough for p in [0.05, 0.95]
    cap = 50.0 / (w + l)
    lo, hi = -cap, cap
    if p <= p_win_first(lo):
        theta = lo
    elif p >= p_win_first(hi):
        theta = hi
    else:
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if p_win_first(mid) < p:
                lo = mid
            else:
                hi = mid
        theta = 0.5 * (lo + hi)

    nu = theta * sigma2 / 2.0          # arithmetic (log-space) drift, "win up" frame
    if direction != "LONG":
        nu = -nu                        # mirror back: SHORT wins when price falls
    return nu + sigma2 / 2.0            # convert to GBM mu (Ito adjustment)


class AITradeSimulator:
    """
    GBM Monte Carlo gate.
    Uses real 30-day historical volatility (Yahoo Finance).
    Parameterised by the engine's realized win rate so the gate reflects
    actual edge rather than a fixed zero-drift assumption.
    """

    def __init__(self, simulations: int = 5000):
        self.simulations = simulations

    def simulate(
        self,
        current_price: float,
        stop_loss: float,
        take_profit: float,
        symbol: str = "MNQ=F",
        steps: int = 20,
        session_quality: str = "NORMAL",
        direction: str = "LONG",
        p_win: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Geometric Brownian Motion Monte Carlo with realized-edge drift.

        Args:
            p_win: Realized win-rate probability (0–1) from the RL engine.
                   Pass rl_engine.win_rate / 100.0.
                   None or 0.0 → zero-drift fallback (conservative default).
        """
        annual_vol = _get_historical_vol(symbol)
        daily_vol  = annual_vol / np.sqrt(252)
        dt         = 1.0  # 1 day per step

        # GBM drift calibrated so P(TP first) matches the realized win rate
        # for the ACTUAL asymmetric barrier distances. The old symmetric logit
        # mapping returned mu=0 at p_win=0.5, which with 2.5/1.5 ATR barriers
        # collapsed EV to ~0 and made the gate veto virtually every signal.
        if p_win is not None and p_win > 0.02:
            mu = _calibrate_drift_asymmetric(
                p_win, daily_vol, current_price, stop_loss, take_profit, direction
            )
        else:
            mu = 0.0  # No history yet — conservative zero-drift

        # PERF-1: Vectorized GBM — ~80x faster than the Python double-loop.
        # Generate all random shocks at once, cumsum for log-price paths, then
        # use argmax to find the first barrier crossing per path.
        # IV&V Medium: seed the RNG deterministically from the setup so the
        # viability verdict is REPRODUCIBLE. An unseeded RNG could flip
        # is_viable on identical inputs near the hurdle, making entries and
        # backtests non-deterministic. hashlib (not builtin hash()) is used
        # because hash() is salted per-process and would break cross-run repro.
        import hashlib as _hashlib
        _key  = f"{current_price:.6f}|{stop_loss:.6f}|{take_profit:.6f}|{steps}|{direction}|{float(mu):.8f}"
        _seed = int(_hashlib.md5(_key.encode()).hexdigest()[:8], 16)
        rng  = np.random.default_rng(_seed)
        Z    = rng.standard_normal((self.simulations, steps))
        log_ret  = (mu - 0.5 * daily_vol ** 2) * dt + daily_vol * math.sqrt(dt) * Z
        # price_paths shape: (simulations, steps)
        price_paths = current_price * np.exp(np.cumsum(log_ret, axis=1))

        if direction == "LONG":
            hit_tp = (price_paths >= take_profit)
            hit_sl = (price_paths <= stop_loss)
        else:
            hit_tp = (price_paths <= take_profit)
            hit_sl = (price_paths >= stop_loss)

        # For each simulation, find the first step where TP or SL is crossed
        # argmax returns 0 if no True found — handle with any()
        any_tp   = hit_tp.any(axis=1)
        any_sl   = hit_sl.any(axis=1)
        # First crossing index (0-based)
        tp_first = np.where(any_tp, np.argmax(hit_tp, axis=1), steps)
        sl_first = np.where(any_sl, np.argmax(hit_sl, axis=1), steps)

        success_count = int(np.sum(any_tp & (~any_sl | (tp_first <= sl_first))))
        loss_count    = int(np.sum(any_sl & (~any_tp | (sl_first <  tp_first))))
        unresolved    = self.simulations - success_count - loss_count

        win_prob  = success_count / self.simulations
        loss_prob = loss_count / self.simulations
        # unresolved_prob = unresolved / self.simulations
        # Unresolved paths hit the step limit without touching either barrier.
        # Closing at step 20 yields a partial profit or loss, not the full -risk.
        # Treating them as -risk (the old (1-win_prob)*risk formula) was pessimistic
        # because it bundled unresolved paths with actual stop-loss hits.
        # Fix: charge only confirmed stop-loss hits; unresolved paths contribute 0 EV.
        if direction == "LONG":
            reward = take_profit - current_price
            risk   = current_price - stop_loss
        else:
            reward = current_price - take_profit
            risk   = stop_loss - current_price

        expected_value = (win_prob * reward) - (loss_prob * risk)

        # Hurdle: must clear slippage / spread cost
        # Session-quality tiers reflect real bid-ask spread costs per instrument class.
        if session_quality == "ASIAN_THIN":
            hurdle_pct = 0.0035  # widest spread: thin volume, Asian hours
        elif session_quality == "LONDON_FIX":
            hurdle_pct = 0.0025  # moderate: institutional flow but volatile
        else:
            hurdle_pct = 0.0015  # normal session

        hurdle    = current_price * hurdle_pct
        is_viable = expected_value > hurdle

        return {
            "is_viable":       is_viable,
            "win_probability": round(win_prob, 4),
            "expected_value":  round(expected_value / max(current_price, 1e-9), 6),
            "simulations":     self.simulations,
            "success_count":   success_count,
            "loss_count":      loss_count,
            "unresolved":      unresolved,
            "hurdle_pct":      hurdle_pct,
            "direction":       direction,
        }
