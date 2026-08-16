#!/usr/bin/env python3
"""RECENT-WINDOW beat study — the numbers the submission recommendation rests on.

    forecast = consensus x (1 + alpha)

WHY THIS FILE EXISTS SEPARATELY FROM per_metric_study.py
per_metric_study.py uses the FULL yfinance history (99 quarters back to 2001).
Its chronological split therefore trains on 2001-2016 and scores 2016-2026,
which is the wrong experiment for a decision about the quarter now printing:
  - a beat habit from the 2000s tells you little about 2026;
  - 2008-2010 EPS near zero makes the relative-beat MEAN explode
    (DE full-sample mean alpha = -7.88%, CI [-64%, +24%] — meaningless).
This file restricts to the last 24 quarters (6 years), drops observations with
|consensus| < $0.20 so a near-zero denominator cannot dominate, and uses the
MEDIAN, which is the robust statistic when a few quarters are extreme.

Split: first 16 quarters fit, last 8 score. Nothing from the test window
touches the estimate.

Usage:  python alpha_recent.py
Needs:  yfinance + network.
"""
import statistics
import sys

try:
    import yfinance as yf
except ImportError:
    sys.exit("needs yfinance:  pip install yfinance")

WINDOW, TRAIN, MIN_C = 24, 16, 0.20

# metric label, submitted value, the consensus the engine anchored on
CASES = [
    ("HD",  "Adjusted diluted EPS", 4.65, 4.69,
     "yfinance EPS is the street/adjusted number — same measure"),
    ("ADI", "Adjusted diluted EPS", 3.31, 3.33,
     "verified: yfinance actual 3.09 == corpus adjusted EPS 3.09"),
    ("DE",  "Diluted EPS (GAAP)",   4.70, 4.72,
     "verified: Q2 8-K says '$6.55 per share', yfinance reports 6.55 — "
     "yfinance IS the GAAP figure for Deere, no basis risk"),
]


def rows_for(tk):
    ed = yf.Ticker(tk).get_earnings_dates(limit=60)
    if ed is None or not len(ed):
        return []
    h = ed.dropna(subset=["Reported EPS", "EPS Estimate"]).sort_index()
    out = [{"d": str(i.date()), "c": float(r["EPS Estimate"]), "a": float(r["Reported EPS"])}
           for i, r in h.iterrows()]
    return [r for r in out if abs(r["c"]) >= MIN_C][-WINDOW:]


def mae(rows, alpha):
    return sum(abs(r["c"] * (1 + alpha) - r["a"]) for r in rows) / len(rows)


def main():
    print("RECENT-WINDOW BEAT STUDY   forecast = consensus x (1 + alpha)")
    print(f"last {WINDOW} quarters | fit on first {TRAIN}, score on last {WINDOW-TRAIN}"
          f" | median | |consensus| >= ${MIN_C:.2f}")
    print("consensus + actual: yfinance earnings_dates, same basis both legs.\n")
    verdicts = []
    for tk, label, submitted, cons, basis in CASES:
        rows = rows_for(tk)
        if len(rows) < WINDOW:
            print(f"{tk}: only {len(rows)} usable quarters — skipped\n")
            continue
        beats = [(r["a"] - r["c"]) / r["c"] for r in rows]
        train, test = rows[:TRAIN], rows[TRAIN:]
        med_tr = statistics.median((r["a"] - r["c"]) / r["c"] for r in train)
        med_all = statistics.median(beats)
        base, alt = mae(test, 0.0), mae(test, med_tr)
        delta = (alt / base - 1) * 100
        helps = alt < base

        print("=" * 76)
        print(f"{tk}  —  {label}")
        print(f"  basis: {basis}")
        print("=" * 76)
        print(f"  n={len(rows)}  {rows[0]['d']} .. {rows[-1]['d']}   "
              f"beats consensus {sum(1 for b in beats if b > 0)}/{len(beats)}")
        print(f"  median alpha: full window {med_all*100:+.2f}%   train-only {med_tr*100:+.2f}%")
        print(f"  last 4 beats: {[f'{b*100:+.1f}%' for b in beats[-4:]]}")
        print(f"\n  OUT OF SAMPLE (last {len(test)} quarters, alpha fitted on the first {len(train)}):")
        print(f"    consensus untouched      MAE {base:.4f}")
        print(f"    consensus x (1+alpha)    MAE {alt:.4f}   {delta:+.1f}%")
        print(f"    -> alpha {'HELPS' if helps else 'HURTS'}")
        print(f"\n  IMPLIED THIS QUARTER (engine consensus {cons}):")
        print(f"    submitted                {submitted:.2f}")
        print(f"    consensus x (1+alpha)    {cons*(1+med_all):.2f}   (alpha {med_all*100:+.2f}%)")
        print()
        verdicts.append((tk, label, submitted, cons * (1 + med_all), helps, delta, med_all))

    print("=" * 76)
    print("SUMMARY")
    print("=" * 76)
    print(f"  {'':4}{'submitted':>11}{'alpha-implied':>15}{'OOS':>9}   action")
    for tk, label, sub, imp, helps, delta, al in verdicts:
        action = f"CHANGE -> {imp:.2f}" if helps else "KEEP submitted (alpha fails OOS)"
        print(f"  {tk:4}{sub:>11.2f}{imp:>15.2f}{delta:>8.0f}%   {action}")
    print("\n  Non-EPS metrics are NOT here: no historical consensus series exists for")
    print("  net sales, comp sales, gross margin, segment profit, or any Hays line.")
    print("  The only non-EPS number with evidence is ADI revenue, which is")
    print("  guide-relative (see README_FOR_JAYESH.md).")


if __name__ == "__main__":
    main()
