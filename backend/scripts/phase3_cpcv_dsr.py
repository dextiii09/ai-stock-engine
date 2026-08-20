"""
Phase 3 — CPCV + Deflated Sharpe validation of the BTC-USD meta-label gate.

    cd E:\\Ai Stock\\backend
    python scripts\\phase3_cpcv_dsr.py

Runs 15 combinatorial purged train/test splits (C(6,2)), evaluates the
p>=0.50 gate net of costs on each, aggregates all out-of-sample gated trades,
and computes the Deflated Sharpe Ratio (accounts for the ~16 configurations
this research program has tried — luck is priced in).

Output: E:\\Ai Stock\\CPCV_DSR_PHASE3.md

Verdicts are decided by criteria fixed in advance (see analytics/cpcv.py):
CONFIRMED / INCONCLUSIVE / REJECTED. Only CONFIRMED justifies wiring the
gate into the live crypto loop — and even then, paper trading only.
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.cpcv import run_cpcv  # noqa: E402

OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "CPCV_DSR_PHASE3.md")


def main():
    print("[phase3] running CPCV (15 purged splits) + DSR for BTC-USD ...")
    r = run_cpcv("BTC-USD")
    print(json.dumps({k: v for k, v in r.items() if k != "splits"}, indent=1))

    lines = [
        "# Phase 3 — CPCV + Deflated Sharpe (BTC-USD, p>=0.50 gate)",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}_",
        "",
    ]
    if r.get("error"):
        lines.append(f"ERROR: {r['error']}")
    else:
        lines += [
            f"- rows: {r['rows']}, splits: {r['n_splits']}, gate p>={r['gate']},"
            f" cost model {r['cost_model_pct']*100:.2f}% round trip",
            f"- splits net-positive (gated): **{r['pct_splits_net_positive']}%**",
            f"- splits with positive UPLIFT (gate beats no-gate):"
            f" **{r.get('pct_splits_uplift_positive')}%**"
            f" | mean uplift {r.get('mean_uplift_R')} R",
        ]
        if "oos_exp_R_net" in r:
            lines += [
                f"- aggregate OOS gated trades: {r['oos_trades']}",
                f"- aggregate OOS expectancy (net): **{r['oos_exp_R_net']} R/trade**",
                f"- per-trade Sharpe: {r['oos_sharpe_per_trade']}"
                f" | null-max Sharpe ({16} trials): {r['sr_star_null_max']}",
                f"- **Deflated Sharpe Ratio: {r['deflated_sharpe']}**"
                " (probability the edge is real after luck adjustment)",
            ]
        lines += ["", "## Per-split detail", ""]
        for s in r.get("splits", []):
            lines.append(f"- groups {s['test_groups']}: AUC {s['auc']}, "
                         f"gated {s['pct_gated']}% of {s['n_test']}, "
                         f"E[R] all {s['exp_R_all_net']} vs gated"
                         f" **{s['exp_R_gated_net']}**")
        lines += ["", f"## VERDICT: **{r['verdict']}**", ""]
        if r["verdict"] == "CONFIRMED":
            lines.append("Next step: wire the gate into the live crypto loop as"
                         " a BTC-only entry veto (paper), monitored weekly.")
        elif r["verdict"] == "REJECTED":
            lines.append("The Phase 2 result did not survive combinatorial"
                         " validation — it was likely a single-split artifact."
                         " Do not wire live. This is a clean, valuable answer.")
        else:
            lines.append("Evidence is mixed. Do not wire live. Options: extend"
                         " history, retest in 3 months with more data, or stop"
                         " here.")
    lines += ["", "_Criteria were fixed before running. Paper trading only._"]

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n[done] Report written to {OUT_PATH}")


if __name__ == "__main__":
    main()
