"""
Phase 2 meta-labeling evaluation (BTC-USD) — run from the backend directory:

    cd E:\\Ai Stock\\backend
    python scripts\\phase2_meta_label.py

Trains the meta-model on the first 70% of 5y BTC-USD history, evaluates on
the untouched last 30%, and writes E:\\Ai Stock\\META_LABEL_PHASE2.md with:
  * probability calibration (predicted P(win) vs realized win rate)
  * EXPECTANCY UPLIFT: E[R] of gated trades vs taking every trade
  * a saved model (backend/data/models/meta_btc.joblib) IF results justify it

The verdict criteria are fixed IN ADVANCE:
  * A gate is "promising" only if its out-of-sample E[R] beats baseline by
    >= +0.05 R AND it still takes >= 20% of trades (a gate that trades twice
    a year is untestable noise).
  * Even a promising result is NOT live-ready: Phase 3 (CPCV + Deflated
    Sharpe across multiple periods) must confirm it first.
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.meta_label import train_and_evaluate  # noqa: E402

OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "META_LABEL_PHASE2.md")


def main():
    print("[phase2] training + evaluating meta-model for BTC-USD ...")
    r = train_and_evaluate("BTC-USD")
    print(json.dumps(r, indent=1)[:2000])

    lines = [
        "# Phase 2 — Meta-Labeling Evaluation (BTC-USD)",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}_",
        "",
    ]
    if r.get("error"):
        lines.append(f"ERROR: {r['error']}")
    else:
        b = r["baseline"]
        lines += [
            f"- rows: {r['rows']} (train {r['train_rows']}, test {r['test_rows']}, embargoed)",
            f"- out-of-sample AUC: **{r['test_auc']}**",
            "",
            "## Baseline (take every trade)",
            f"- trades {b['n_trades']}, win rate {b['win_rate']}, **E[R] {b['exp_R']}**",
            "",
            "## Gated by meta-model P(win)",
        ]
        best = None
        for th, g in r["gates"].items():
            lines.append(f"- p ≥ {th}: takes {g['pct_taken']}% of trades "
                         f"(n={g['n_trades']}), win rate {g['win_rate']}, "
                         f"**E[R] {g['exp_R']}**")
            if (g["exp_R"] is not None and g["n_trades"] >= 0.20 * b["n_trades"]
                    and (best is None or g["exp_R"] > best[1])):
                best = (th, g["exp_R"], g)
        lines += ["", "## Calibration (predicted P vs realized win rate)"]
        for c in r["calibration"]:
            lines.append(f"- {c['p_range']}: n={c['n']}, realized win "
                         f"{c['realized_win_rate']}, E[R] {c['exp_R']}")
        lines += ["", "## Verdict (criteria fixed before running)"]
        if best and best[1] >= b["exp_R"] + 0.05:
            lines.append(
                f"- **PROMISING**: gate p≥{best[0]} improves out-of-sample "
                f"expectancy from {b['exp_R']} to {best[1]} R/trade while "
                f"keeping {best[2]['pct_taken']}% of trades.")
            lines.append("- NOT live-ready yet: requires Phase 3 validation "
                         "(CPCV + Deflated Sharpe, multiple periods) — a "
                         "single split can flatter a regime.")
            lines.append(f"- Model saved: {r.get('model_saved')}")
        else:
            lines.append(
                "- **NOT CONFIRMED**: no gate met the pre-set bar "
                "(+0.05 R uplift while keeping ≥20% of trades). The Phase 1 "
                "AUC did not translate into monetizable expectancy on this "
                "split. Do not proceed to live wiring; options are Phase 3 "
                "robustness analysis or stopping here with a clear answer.")
    lines += ["", "_Paper trading only. This measures; it does not promise._"]

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n[done] Report written to {OUT_PATH}")


if __name__ == "__main__":
    main()
