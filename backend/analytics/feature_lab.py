"""
Feature Laboratory — Phase 1 of the signal-research program.

Purpose: answer ONE question honestly — do any economically-motivated
features carry predictive power for this system's trade outcomes?

Components
  1. Economic features (beyond raw RSI/MACD):
       * vix_ts        — volatility term structure (^VIX3M − ^VIX). Positive =
                         contango (calm); negative = backwardation (stress).
       * yield_spread  — 10Y − 13-week Treasury yield (^TNX − ^IRX), plus its
                         5-day momentum. Daily resolution (minute-level
                         lead-lag is NOT possible with free data).
       * cot_net_mom   — WEEKLY CHANGE in CFTC net positioning (managed money
                         for Gold, leveraged funds for NQ) — rate of change,
                         not levels. Only available for MGC=F / MNQ=F.
     Baseline technicals (rsi, macd_hist, atr_pct, ret_5d, vol_z) are included
     so the evaluation can compare new vs old features fairly.

  2. Triple-Barrier labeling (TBM): each bar is labeled by which barrier a
     LONG entered at next-bar-open would hit first — profit barrier
     (+RR·stop_dist), stop barrier (−stop_dist, stop_dist = ATR_MULT·ATR%),
     or the vertical time barrier (HORIZON bars → label by sign of return).
     This matches how the live engine actually exits, unlike "next-bar return".

  3. Purged walk-forward evaluation: sequential folds with an embargo gap of
     HORIZON bars between train and test (prevents label-overlap leakage).
     Reports per-feature Spearman IC and RandomForest AUC per fold.

Interpretation guide (be honest with yourself):
  * AUC ≈ 0.50            → no predictive power. Expected outcome.
  * AUC 0.52–0.55 stable  → weak but possibly real; needs more validation
                            (CPCV + Deflated Sharpe = Phase 3) before ANY use.
  * |IC| < 0.03           → noise.
  This module does not and cannot guarantee a profitable strategy.
"""
import json
import math
import ssl
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd

from data.provider import DataProviderFactory

_provider = DataProviderFactory.get_provider()

ATR_MULT = 2.5      # matches live STOP_ATR_MULT
RR       = 2.0      # matches live TP_RISK_REWARD
HORIZON  = 20       # vertical barrier (bars)
MIN_STOP = 0.005    # matches live MIN_STOP_PCT


# ── Basic indicator helpers (Wilder, matching live/backtest) ─────────────────

def _wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rsi = 100 - 100 / (1 + (up / dn.replace(0, np.nan)))
    rsi = rsi.where(dn > 0, 100.0)
    rsi = rsi.where((up > 0) | (dn > 0), 50.0)
    return rsi


def _macd_hist(close: pd.Series) -> pd.Series:
    ml = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    return ml - ml.ewm(span=9, adjust=False).mean()


def _atr_pct(df: pd.DataFrame, n: int = 14) -> pd.Series:
    c = df["Close"]
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - c.shift()).abs(),
                    (df["Low"] - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean() / c


# ── External series ──────────────────────────────────────────────────────────

def _daily(symbol: str, period: str) -> Optional[pd.DataFrame]:
    try:
        df = _provider.get_historical_ohlcv(symbol=symbol, period=period, interval="1d")
        return df if df is not None and len(df) > 30 else None
    except Exception:
        return None


def _close_series(symbol: str, period: str) -> Optional[pd.Series]:
    df = _daily(symbol, period)
    if df is None:
        return None
    s = df["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    return s[~s.index.duplicated(keep="last")]


def cot_history(market: str, limit: int = 300) -> Optional[pd.Series]:
    """Weekly net-positioning history from CFTC SODA (free, tokenless).
    market: 'gold' (managed money) or 'nq' (leveraged funds).
    Returns a date-indexed Series of net positions, or None on failure."""
    if market == "gold":
        endpoint, code = "kh3c-gbw2", "088691"
        lf, sf = "m_money_positions_long_all", "m_money_positions_short_all"
    else:
        endpoint, code = "yw9f-hn96", "209742"
        lf, sf = "lev_money_positions_long", "lev_money_positions_short"
    params = urllib.parse.urlencode({"cftc_contract_market_code": code})
    url = (f"https://publicreporting.cftc.gov/resource/{endpoint}.json?{params}"
           f"&$order=report_date_as_yyyy_mm_dd%20DESC&$limit={limit}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AiStock/1.0"})
        with urllib.request.urlopen(req, timeout=10,
                                    context=ssl.create_default_context()) as r:
            rows = json.loads(r.read().decode())
        out = {}
        for row in rows:
            date = row.get("report_date_as_yyyy_mm_dd", "")[:10]
            # TFF field names vary between _all suffix and none — try both.
            lo = row.get(lf) or row.get(lf + "_all") or 0
            sh = row.get(sf) or row.get(sf + "_all") or 0
            try:
                out[pd.Timestamp(date)] = int(float(lo)) - int(float(sh))
            except Exception:
                continue
        if not out:
            return None
        return pd.Series(out).sort_index()
    except Exception:
        return None


# ── Dataset construction ─────────────────────────────────────────────────────

def build_dataset(symbol: str, period: str = "5y") -> Optional[pd.DataFrame]:
    """OHLCV + features + triple-barrier labels for one symbol.
    Returns a DataFrame with feature columns, 'label' (1=profit barrier first,
    0=stop barrier first / negative timeout) — or None if data unavailable."""
    df = _daily(symbol, period)
    if df is None:
        return None
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")]

    feat = pd.DataFrame(index=df.index)
    close = df["Close"]

    # Baseline technicals
    feat["rsi"]       = _wilder_rsi(close)
    feat["macd_hist"] = _macd_hist(close) / close          # scale-free
    feat["atr_pct"]   = _atr_pct(df)
    feat["ret_5d"]    = close.pct_change(5)
    vol = df["Volume"].fillna(0)
    feat["vol_z"]     = ((vol - vol.rolling(20).mean()) /
                         vol.rolling(20).std().replace(0, np.nan)).fillna(0)

    # Economic features (aligned + forward-filled onto trading days)
    vix   = _close_series("^VIX", period)
    vix3m = _close_series("^VIX3M", period)
    if vix is not None and vix3m is not None:
        ts = (vix3m - vix).reindex(feat.index, method="ffill")
        feat["vix_ts"]  = ts
        feat["vix_lvl"] = vix.reindex(feat.index, method="ffill")
    tnx = _close_series("^TNX", period)
    irx = _close_series("^IRX", period)
    if tnx is not None and irx is not None:
        ys = (tnx - irx).reindex(feat.index, method="ffill")
        feat["yield_spread"]      = ys
        feat["yield_spread_mom5"] = ys.diff(5)

    # COT momentum — futures only (weekly data, ffilled; CHANGE not level)
    cot_mkt = {"MGC=F": "gold", "MNQ=F": "nq"}.get(symbol.upper())
    if cot_mkt:
        cot = cot_history(cot_mkt)
        if cot is not None and len(cot) > 10:
            mom = cot.diff()  # weekly rate of change of net positioning
            feat["cot_net_mom"] = mom.reindex(feat.index, method="ffill")

    # Triple-barrier labels (LONG perspective, entry at next bar's open).
    # Also record realized R per trade: −1R on stop, +RR on profit barrier,
    # drift/stop_d on the vertical barrier — needed by Phase 2 to measure
    # EXPECTANCY uplift (AUC alone can't tell you if a gate makes money).
    n = len(df)
    highs, lows, opens = df["High"].values, df["Low"].values, df["Open"].values
    closes = df["Close"].values
    atrp = feat["atr_pct"].values
    labels     = np.full(n, np.nan)
    realized_r = np.full(n, np.nan)
    for i in range(n - 2):
        if not np.isfinite(atrp[i]):
            continue
        entry = opens[i + 1]
        stop_d = max(ATR_MULT * atrp[i], MIN_STOP) * entry
        up, dn = entry + RR * stop_d, entry - stop_d
        lbl = rr = None
        for j in range(i + 1, min(i + 1 + HORIZON, n)):
            hit_up, hit_dn = highs[j] >= up, lows[j] <= dn
            if hit_dn:            # conservative: same-bar dual touch = loss
                lbl, rr = 0, -1.0; break
            if hit_up:
                lbl, rr = 1, RR; break
        if lbl is None:           # vertical barrier: realized drift in R units
            j_end = min(i + HORIZON, n - 1)
            rr  = (closes[j_end] - entry) / stop_d
            lbl = 1 if rr > 0 else 0
        labels[i]     = lbl
        realized_r[i] = rr
    feat["label"]      = labels
    feat["realized_r"] = realized_r

    return feat.dropna()


# ── Evaluation ───────────────────────────────────────────────────────────────

def evaluate(symbol: str, period: str = "5y", n_folds: int = 3) -> Dict[str, Any]:
    """Per-feature Spearman IC + purged walk-forward RandomForest AUC."""
    from scipy.stats import spearmanr
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score

    data = build_dataset(symbol, period)
    if data is None or len(data) < 300:
        return {"symbol": symbol, "error": "insufficient data",
                "rows": 0 if data is None else len(data)}

    y = data["label"].astype(int)
    # realized_r is an OUTCOME, not a feature — must never enter X (leakage).
    X = data.drop(columns=["label", "realized_r"], errors="ignore")

    ics = {}
    for col in X.columns:
        try:
            ic, _ = spearmanr(X[col], y)
            ics[col] = round(float(ic), 4) if np.isfinite(ic) else 0.0
        except Exception:
            ics[col] = 0.0

    n = len(X)
    fold_edges = np.linspace(0.5, 1.0, n_folds + 1)   # train on ≥50% first
    aucs, importances = [], np.zeros(len(X.columns))
    for k in range(n_folds):
        tr_end = int(fold_edges[k] * n)
        te_start = tr_end + HORIZON                    # purge/embargo gap
        te_end = int(fold_edges[k + 1] * n)
        if te_end - te_start < 40:
            continue
        Xtr, ytr = X.iloc[:tr_end], y.iloc[:tr_end]
        Xte, yte = X.iloc[te_start:te_end], y.iloc[te_start:te_end]
        if yte.nunique() < 2 or ytr.nunique() < 2:
            continue
        clf = RandomForestClassifier(n_estimators=300, max_depth=4,
                                     min_samples_leaf=50, class_weight="balanced",
                                     random_state=42, n_jobs=-1)
        clf.fit(Xtr, ytr)
        p = clf.predict_proba(Xte)[:, 1]
        aucs.append(round(float(roc_auc_score(yte, p)), 4))
        importances += clf.feature_importances_

    imp = {c: round(float(v / max(len(aucs), 1)), 4)
           for c, v in zip(X.columns, importances)}
    return {
        "symbol":       symbol,
        "rows":         n,
        "label_balance": round(float(y.mean()), 3),   # fraction of profit-first
        "feature_ic":   dict(sorted(ics.items(), key=lambda x: -abs(x[1]))),
        "fold_aucs":    aucs,
        "mean_auc":     round(float(np.mean(aucs)), 4) if aucs else None,
        "feature_importance": dict(sorted(imp.items(), key=lambda x: -x[1])),
    }
