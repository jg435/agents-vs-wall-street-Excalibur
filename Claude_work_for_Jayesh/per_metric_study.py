#!/usr/bin/env python3
"""Per-company, per-metric beat estimate + out-of-sample test. FAST PATH.

The intercept model needs only (consensus, actual) -- no guidance:

        forecast = consensus x (1 + alpha)

alpha is the persistent beat consensus fails to capture. yfinance
earnings_dates supplies both legs on the street basis for HD / ADI / DE.

For every metric it reports: n, hit rate, alpha on several windows, and a
CHRONOLOGICAL out-of-sample test (fit early, score late) against
consensus-untouched. If alpha does not beat consensus out of sample, it says so.

Usage:  python per_metric_study.py [--corpus challenge/offline-data]
"""
import argparse
import statistics
import sys

try:
    import yfinance as yf
except ImportError:
    sys.exit("needs yfinance")

TICKERS = {"HD": "HD", "ADI": "ADI", "DE": "DE", "HAS": "HAS.L"}

# What the competition actually asks for, and whether yfinance's EPS series is
# the SAME measure. A mismatch here silently corrupts everything downstream.
EPS_METRIC = {
    "HD":  ("Adjusted diluted EPS", "MATCH - yfinance EPS is the street/adjusted number"),
    "ADI": ("Adjusted diluted EPS", "MATCH - verified 3.09 vs corpus adjusted EPS 3.09"),
    "DE":  ("Diluted EPS (GAAP)",   "*** BASIS RISK - metric says GAAP, yfinance is street. "
                                    "Check the gap before applying alpha ***"),
    "HAS": ("Pre-exceptional basic EPS (pence)", "NO yfinance coverage - UK name"),
}

# Submitted numbers, to show what alpha would imply.
SUBMITTED = {"HD": 4.65, "ADI": 3.31, "DE": 4.70, "HAS": 1.12}
CONSENSUS_USED = {"HD": 4.69, "ADI": 3.33, "DE": 4.72, "HAS": None}


def series(tk):
    ed = yf.Ticker(tk).get_earnings_dates(limit=60)
    if ed is None or not len(ed):
        return []
    h = ed.dropna(subset=["Reported EPS", "EPS Estimate"]).sort_index()
    out = []
    for ix, r in h.iterrows():
        c, a = float(r["EPS Estimate"]), float(r["Reported EPS"])
        if abs(c) > 1e-6:
            out.append({"date": str(ix.date()), "c": c, "a": a, "beat": (a - c) / abs(c)})
    return out


def alpha_of(rows):
    """Mean relative beat. Median reported alongside -- it is the robust one."""
    b = [r["beat"] for r in rows]
    return statistics.mean(b), statistics.median(b)


def mae_alpha(rows, alpha):
    return sum(abs(r["c"] * (1 + alpha) - r["a"]) for r in rows) / len(rows)


def boot_ci(rows, iters=6000, seed=11):
    n, st, draws = len(rows), seed, []
    for _ in range(iters):
        s = []
        for _ in range(n):
            st = (1103515245 * st + 12345) % (2 ** 31)
            s.append(rows[st % n])
        draws.append(statistics.mean(r["beat"] for r in s))
    draws.sort()
    return draws[int(len(draws) * .05)], draws[int(len(draws) * .95)]


def run(key):
    tk = TICKERS[key]
    label, basis = EPS_METRIC[key]
    print(f"\n{'='*78}\n{key}  —  {label}\n  basis: {basis}\n{'='*78}")
    rows = series(tk)
    if len(rows) < 8:
        print(f"  n={len(rows)} — NOT ESTIMABLE from yfinance. Skipped.")
        return
    hits = sum(1 for r in rows if r["beat"] > 0)
    print(f"  n={len(rows)} quarters, {rows[0]['date']} .. {rows[-1]['date']}")
    print(f"  beats consensus {hits}/{len(rows)} ({hits/len(rows):.0%})")

    print(f"\n  alpha by window (mean / median):")
    for w in (8, 12, 20, len(rows)):
        sub = rows[-w:]
        m, md = alpha_of(sub)
        tag = "  <- full" if w == len(rows) else ""
        print(f"    last {w:>3}q   {m*100:+6.2f}% / {md*100:+6.2f}%{tag}")
    lo, hi = boot_ci(rows)
    m_all, md_all = alpha_of(rows)
    print(f"  bootstrap 90% CI on full-sample mean alpha: "
          f"[{lo*100:+.2f}%, {hi*100:+.2f}%]")

    # ---- chronological out-of-sample
    k = int(len(rows) * 0.6)
    train, test = rows[:k], rows[k:]
    a_tr, md_tr = alpha_of(train)
    base = mae_alpha(test, 0.0)
    cands = [("consensus untouched", 0.0),
             (f"alpha mean  (train {a_tr*100:+.2f}%)", a_tr),
             (f"alpha median(train {md_tr*100:+.2f}%)", md_tr)]
    print(f"\n  OUT OF SAMPLE — train {train[0]['date']}..{train[-1]['date']} (n={len(train)}), "
          f"test {test[0]['date']}..{test[-1]['date']} (n={len(test)})")
    print(f"    {'rule':<34}{'test MAE':>10}{'vs consensus':>14}")
    best = None
    for name, al in cands:
        m = mae_alpha(test, al)
        print(f"    {name:<34}{m:>10.4f}{(m/base-1)*100:>13.1f}%")
        if best is None or m < best[1]:
            best = (name, m, al)
    verdict = "HOLDS" if best[2] != 0.0 else "FAILS — alpha does not help"
    print(f"    -> {verdict}  (best: {best[0]})")

    # ---- what it implies for the submitted number
    c = CONSENSUS_USED.get(key)
    if c:
        rec_lo, rec_hi = md_tr, md_all
        print(f"\n  IMPLIED FOR THIS QUARTER (consensus {c}):")
        print(f"    submitted            {SUBMITTED[key]:.2f}")
        for nm, al in (("median alpha, train-fit", md_tr),
                       ("median alpha, full", md_all),
                       ("mean alpha, full", m_all)):
            print(f"    {nm:<24} {c*(1+al):.2f}   (alpha {al*100:+.2f}%)")
    return


def main():
    ap = argparse.ArgumentParser()
    ap.parse_args()
    print("PER-METRIC BEAT STUDY  —  forecast = consensus x (1 + alpha)")
    print("consensus + actual: yfinance earnings_dates, street basis both legs.")
    for k in ("HD", "ADI", "DE", "HAS"):
        run(k)

    print(f"\n{'='*78}\nNOT ESTIMABLE — no historical consensus series exists\n{'='*78}")
    for m in ["HD  Net sales            (no historical revenue consensus)",
              "ADI Revenue              (no historical revenue consensus)",
              "DE  Worldwide net sales  (no historical revenue consensus; also a",
              "                          different measure from the yfinance feed)",
              "HD  Comparable sales %   (no consensus feed at all)",
              "ADI Adjusted gross margin(not guided, no consensus feed)",
              "DE  PPA operating profit (segment level, no feed)",
              "HAS Net fees / EPS / op profit (UK, no yfinance; Hays publishes",
              "                          its own consensus - build by hand)"]:
        print("  " + m)
    print("\n  For these, the shipped rule stands. There is no data to replace it with")
    print("  in the time available, and inventing one would be worse than keeping it.")


if __name__ == "__main__":
    main()
