"""
Phase 1 feature evaluation — run this ONCE from the backend directory:

    cd E:\\Ai Stock\\backend
    python scripts\\phase1_feature_eval.py

It downloads 5 years of daily data per symbol, builds the economic features
(VIX term structure, yield-curve spread, COT positioning momentum) alongside
the baseline technicals, labels every bar with the Triple-Barrier Method, and
runs a purged walk-forward RandomForest evaluation.

Output: E:\\Ai Stock\\FEATURE_EVAL_PHASE1.md  (plus a console summary).

Runtime: a few minutes (network fetches + 3 RF fits per symbol).
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.feature_lab import evaluate  # noqa: E402

SYMBOLS = ["MNQ=F", "MGC=F", "BTC-USD", "NVDA", "EURUSD=X"]

OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "FEATURE_EVAL_PHASE1.md")


def main():
    results = []
    for sym in SYMBOLS:
        print(f"[eval] {sym} ...")
        try:
            r = evaluate(sym)
        except Exception as e:
            r = {"symbol": sym, "error": str(e)[:200]}
        results.append(r)
        print("      ", json.dumps({k: r.get(k) for k in
              ("rows", "mean_auc", "fold_aucs", "error")}))

    lines = [
        "# Phase 1 — Feature Predictive-Power Evaluation",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}_",
        "",
        "**Question:** do the new economically-motivated features (VIX term",
        "structure, yield-curve spread, COT positioning momentum) — or the old",
        "technicals — predict Triple-Barrier trade outcomes out-of-sample?",
        "",
        "**How to read this:** AUC 0.50 = coin flip (no signal). AUC 0.52-0.55",
        "held across folds AND symbols = weak-but-interesting, worth Phase 2",
        "(meta-labeling) and Phase 3 (CPCV + Deflated Sharpe) validation.",
        "Single-fold spikes are noise. |IC| < 0.03 is noise.",
        "",
    ]
    aucs_all = []
    for r in results:
        lines.append(f"## {r['symbol']}")
        if r.get("error"):
            lines.append(f"- ERROR: {r['error']}")
            lines.append("")
            continue
        lines.append(f"- rows: {r['rows']}  |  label balance (profit-first): {r['label_balance']}")
        lines.append(f"- **fold AUCs: {r['fold_aucs']}  →  mean {r['mean_auc']}**")
        if r.get("mean_auc") is not None:
            aucs_all.append(r["mean_auc"])
        top_ic = list(r["feature_ic"].items())[:5]
        lines.append(f"- top |IC| features: {top_ic}")
        top_imp = list(r["feature_importance"].items())[:5]
        lines.append(f"- top RF importance: {top_imp}")
        lines.append("")

    lines.append("## Overall verdict")
    if aucs_all:
        import statistics
        m = statistics.mean(aucs_all)
        lines.append(f"- mean AUC across symbols: **{m:.4f}**")
        if m < 0.52:
            lines.append("- Verdict: **no exploitable signal detected** in these"
                         " features at daily resolution. Phase 2 (meta-labeling)"
                         " would be building on sand — not recommended until a"
                         " feature shows AUC ≥ 0.52 consistently.")
        else:
            lines.append("- Verdict: weak signal candidate detected. Next step:"
                         " re-test stability (different periods), then Phase 2"
                         " meta-labeling and Phase 3 CPCV/DSR validation before"
                         " ANY live use.")
    else:
        lines.append("- No symbol produced enough data to evaluate.")
    lines.append("")
    lines.append("_This evaluation reduces self-deception; it cannot create"
                 " signal. Paper trading only._")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n[done] Report written to {OUT_PATH}")


if __name__ == "__main__":
    main()
