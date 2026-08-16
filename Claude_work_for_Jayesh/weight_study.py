#!/usr/bin/env python3
"""Estimate the guidance weight w, and test it out of sample.

The engine's rule is   forecast = c + w x (g - c)   with w fixed at 0.8 by
judgement. This script estimates w from data and checks whether the estimate
survives a chronological split.

THE ESTIMATOR (analysis 1). Minimising sum (c + w(g-c) - a)^2 over w has a
closed form -- OLS through the origin of (a - c) on (g - c):

        w* = SUM (g-c)(a-c) / SUM (g-c)^2

Read it as: of the distance from consensus to guidance, what fraction did the
actual actually travel? w*=0 means guidance added nothing over consensus;
w*=1 means guidance was exactly right; w*>1 means the actual overshot the guide.

THE TEST (analysis 8). Fit w on the earlier fraction of events, evaluate MAE on
the later fraction, and compare against the fixed alternatives (w=0 consensus-
only, w=1 guidance-only, w=0.8 as shipped). Beating both endpoints out of
sample is the bar the rule has to clear.

WHY THIS IS EPS-ONLY. A triple needs point-in-time consensus. yfinance
earnings_dates carries the final pre-report EPS estimate and the reported EPS
on the same street basis, going back ~12 years. There is no revenue
equivalent, so revenue cannot be studied this way -- the same wall that blocks
a revenue surprise history.

WHY ADI IS THE CLEAN NAME. ADI guides next-quarter adjusted EPS as a dollar
figure. HD and DE guide the full year, so a triple would need a phasing rule
(temper()) applied first -- which is itself under test, and would confound the
estimate. They are reported separately and flagged, never pooled.

Usage:
    python weight_study.py              # ADI, the clean panel
    python weight_study.py --all        # + HD/DE, phased (confounded, shown apart)
    python weight_study.py --corpus PATH
"""
import argparse
import json
import re
import statistics
import sys
from datetime import timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    sys.exit("needs yfinance:  pip install yfinance")

SHIPPED_W = 0.8

# ---------------------------------------------------------------- extraction

# The corpus is PDF->markdown, which sprays spaces inside numbers ("$3 . 3 0",
# "£4 3.5 m"). Every numeric group therefore allows internal whitespace and is
# de-spaced before parsing.
NUM = r"([\d][\d.,\s]*)"


def _num(s):
    try:
        return float(re.sub(r"[\s,]", "", s).rstrip("."))
    except ValueError:
        return None


ADI_EPS_GUIDE = [
    re.compile(r"adjusted\s+EPS\s+(?:to be|is expected to be|of)\s*\$\s*" + NUM, re.I),
    re.compile(r"adjusted\s+earnings per share\s+(?:to be|of)\s*\$\s*" + NUM, re.I),
]
ADI_REV_GUIDE = [
    re.compile(r"forecasting revenue of\s*\$\s*" + NUM + r"\s*billion", re.I),
    re.compile(r"revenue of\s*\$\s*" + NUM + r"\s*billion[,\s]*\+?\s*/\s*[-−]", re.I),
]


def adi_guidance(corpus):
    """[{filed, eps_guide, rev_guide_usdm}] from every ADI earnings 8-K.

    Only the GUIDE is taken from the corpus. Consensus and actual come from
    yfinance, so the fragile actual-table regexes are out of the loop entirely.
    """
    out = []
    fdir = Path(corpus) / "analog-devices" / "filings"
    for f in sorted(fdir.glob("*8k*.md")):
        txt = f.read_text(errors="ignore")
        eps = rev = None
        for rx in ADI_EPS_GUIDE:
            m = rx.search(txt)
            if m:
                v = _num(m.group(1))
                if v and 0.1 < v < 20:          # an EPS, not a stray table cell
                    eps = v
                    break
        for rx in ADI_REV_GUIDE:
            m = rx.search(txt)
            if m:
                v = _num(m.group(1))
                if v and 0.1 < v < 20:          # $bn
                    rev = v * 1000
                    break
        if eps or rev:
            out.append({"filed": f.name[:10], "doc": f.name,
                        "eps_guide": eps, "rev_guide_usdm": rev})
    return out


# ---------------------------------------------------------------- market data

def consensus_actuals(ticker):
    """[{date, consensus, actual}] oldest->newest, street basis both sides."""
    ed = yf.Ticker(ticker).get_earnings_dates(limit=60)
    if ed is None or not len(ed):
        return []
    h = ed.dropna(subset=["Reported EPS", "EPS Estimate"]).sort_index()
    return [{"date": ix.date(), "consensus": float(r["EPS Estimate"]),
             "actual": float(r["Reported EPS"])} for ix, r in h.iterrows()]


def build_triples(guides, reports, lo_days=30, hi_days=130):
    """Join each guide to the NEXT report after it.

    An 8-K reports the quarter just ended and guides the next one, so the
    guided quarter is the first earnings date after the filing. The window
    guard drops pairs that straddle a corpus gap instead of silently pairing
    a guide with a report two quarters later.
    """
    triples, skipped = [], 0
    from datetime import date as _date
    for g in guides:
        if g.get("eps_guide") is None:
            continue
        fd = _date(*map(int, g["filed"].split("-")))
        nxt = [r for r in reports
               if timedelta(days=lo_days) <= (r["date"] - fd) <= timedelta(days=hi_days)]
        if not nxt:
            skipped += 1
            continue
        r = min(nxt, key=lambda r: r["date"])
        triples.append({"filed": g["filed"], "reported": str(r["date"]),
                        "c": r["consensus"], "g": g["eps_guide"], "a": r["actual"],
                        "doc": g["doc"]})
    # One observation per reported quarter. Intra-quarter updates (conference
    # decks, mid-quarter 8-Ks) would otherwise enter the regression twice with
    # the same (c, a) and inflate n. Keep the LATEST guide before the print.
    by_report = {}
    for x in triples:
        prev = by_report.get(x["reported"])
        if prev is None or x["filed"] > prev["filed"]:
            by_report[x["reported"]] = x
    deduped = sorted(by_report.values(), key=lambda x: x["filed"])
    return deduped, skipped + (len(triples) - len(deduped))


# ---------------------------------------------------------------- estimator

def w_star(t):
    """OLS through the origin of (a-c) on (g-c). None if guidance never
    departs from consensus (w is unidentified when every gap is zero)."""
    num = sum((x["g"] - x["c"]) * (x["a"] - x["c"]) for x in t)
    den = sum((x["g"] - x["c"]) ** 2 for x in t)
    return None if den == 0 else num / den


def mae(t, w):
    return sum(abs(x["c"] + w * (x["g"] - x["c"]) - x["a"]) for x in t) / len(t)


def rmse(t, w):
    return (sum((x["c"] + w * (x["g"] - x["c"]) - x["a"]) ** 2 for x in t) / len(t)) ** 0.5


def alpha_w(t):
    """Two-parameter fit in RELATIVE terms:

        (a - c)/c  =  alpha  +  w * (g - c)/c

    alpha is a persistent proportional beat that neither consensus nor guidance
    captures; w is what the guidance gap adds ON TOP of that. The one-parameter
    model has no intercept, so if the data contain a large constant beat the
    estimator is forced to express it through the only free term it has -- the
    gap -- which can drive w to a nonsensical value. Fitting both separates the
    two effects, and is the honest specification when beats are systematic.
    """
    xs = [(x["g"] - x["c"]) / x["c"] for x in t]
    ys = [(x["a"] - x["c"]) / x["c"] for x in t]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return my, 0.0
    w = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - w * mx, w


def mae_alpha(t, alpha, w):
    return sum(abs(x["c"] * (1 + alpha + w * (x["g"] - x["c"]) / x["c"]) - x["a"])
               for x in t) / len(t)


def bootstrap_ci(t, iters=10000, lo=5, hi=95, seed=7):
    """Percentile CI for w*. Deterministic LCG so the number is reproducible."""
    n, state, draws = len(t), seed, []
    for _ in range(iters):
        sample = []
        for _ in range(n):
            state = (1103515245 * state + 12345) % (2 ** 31)
            sample.append(t[state % n])
        w = w_star(sample)
        if w is not None:
            draws.append(w)
    draws.sort()
    return (draws[int(len(draws) * lo / 100)], draws[int(len(draws) * hi / 100)],
            statistics.median(draws))


# ---------------------------------------------------------------- reporting

def describe(t, label):
    gaps = [(x["g"] - x["c"]) / x["c"] * 100 for x in t]
    trav = [(x["a"] - x["c"]) / (x["g"] - x["c"]) for x in t if abs(x["g"] - x["c"]) > 1e-9]
    print(f"\n{'='*78}\n{label}  (n={len(t)})\n{'='*78}")
    print(f"{'filed':<12}{'reported':<12}{'consensus':>10}{'guide':>9}{'actual':>9}"
          f"{'gap%':>8}{'travelled':>11}")
    for x in t:
        gap = (x["g"] - x["c"]) / x["c"] * 100
        tr = (x["a"] - x["c"]) / (x["g"] - x["c"]) if abs(x["g"] - x["c"]) > 1e-9 else float("nan")
        print(f"{x['filed']:<12}{x['reported']:<12}{x['c']:>10.2f}{x['g']:>9.2f}"
              f"{x['a']:>9.2f}{gap:>8.1f}{tr:>11.2f}")
    print(f"\n  guidance-vs-consensus gap: median {statistics.median(gaps):+.2f}%, "
          f"range {min(gaps):+.2f}% to {max(gaps):+.2f}%")
    if trav:
        print(f"  fraction travelled toward guide: median {statistics.median(trav):+.2f}")


def analyse(t, label):
    if len(t) < 4:
        print(f"\n{label}: n={len(t)} — too few to estimate")
        return None
    describe(t, label)
    w = w_star(t)
    lo, hi, med = bootstrap_ci(t)
    print(f"\n  --- ANALYSIS 1: the estimator -------------------------------")
    print(f"  w* (full sample)        = {w:+.3f}")
    print(f"  bootstrap 90% CI        = [{lo:+.3f}, {hi:+.3f}]   (median {med:+.3f})")
    print(f"  shipped w               =  {SHIPPED_W:.3f}"
          f"   {'INSIDE the CI' if lo <= SHIPPED_W <= hi else '*** OUTSIDE the CI ***'}")

    print(f"\n  in-sample MAE by w:")
    grid = [0.0, 0.25, 0.5, 0.8, 1.0, 1.25, 1.5]
    best = min(grid + [w], key=lambda ww: mae(t, ww))
    for ww in grid:
        star = "  <- shipped" if abs(ww - SHIPPED_W) < 1e-9 else ""
        print(f"    w={ww:<5.2f} MAE={mae(t, ww):.4f}  RMSE={rmse(t, ww):.4f}{star}")
    print(f"    w={w:<5.2f} MAE={mae(t, w):.4f}  RMSE={rmse(t, w):.4f}  <- w* (best: {best:.2f})")

    alpha, w2 = alpha_w(t)
    beats = [(x["a"] - x["c"]) / x["c"] * 100 for x in t]
    print(f"\n  --- specification check: add an intercept ------------------")
    print(f"  (a-c)/c = alpha + w x (g-c)/c")
    print(f"    alpha (persistent beat) = {alpha*100:+.2f}%   "
          f"[raw mean beat vs consensus {statistics.mean(beats):+.2f}%, "
          f"median {statistics.median(beats):+.2f}%]")
    print(f"    w      (gap adds)       = {w2:+.3f}")
    print(f"    MAE with both           = {mae_alpha(t, alpha, w2):.4f}  "
          f"(vs {mae(t, 0.0):.4f} consensus-only)")
    print(f"    beats consensus in {sum(1 for b in beats if b > 0)}/{len(beats)} quarters")
    return w


def out_of_sample(t, label, split=0.6):
    if len(t) < 8:
        print(f"\n  --- ANALYSIS 8: skipped, n={len(t)} too small for a split")
        return
    k = max(4, int(len(t) * split))
    train, test = t[:k], t[k:]
    if len(test) < 3:
        print(f"\n  --- ANALYSIS 8: skipped, test fold would be {len(test)} events")
        return
    w_fit = w_star(train)
    print(f"\n  --- ANALYSIS 8: chronological out-of-sample -----------------")
    print(f"  train {train[0]['filed']} .. {train[-1]['filed']}  (n={len(train)})"
          f"   -> w_fit = {w_fit:+.3f}")
    print(f"  test  {test[0]['filed']} .. {test[-1]['filed']}  (n={len(test)})")
    rows = [("consensus only        (w=0)", 0.0),
            ("guidance only         (w=1)", 1.0),
            ("shipped               (w=0.8)", SHIPPED_W),
            (f"fitted on train       (w={w_fit:.2f})", w_fit)]
    base = mae(test, 0.0)
    print(f"\n  {'rule':<32}{'test MAE':>10}{'vs consensus':>14}")
    for name, ww in rows:
        m = mae(test, ww)
        print(f"  {name:<32}{m:>10.4f}{(m/base - 1)*100:>13.1f}%")
    # the intercept specification, also fitted on train only
    a_fit, w2_fit = alpha_w(train)
    m_alpha = mae_alpha(test, a_fit, w2_fit)
    print(f"  {'alpha+w fitted on train':<32}{m_alpha:>10.4f}{(m_alpha/base - 1)*100:>13.1f}%"
          f"   [alpha={a_fit*100:+.2f}%, w={w2_fit:+.2f}]")
    m_alpha_only = mae_alpha(test, a_fit, 0.0)
    print(f"  {'alpha only, gap ignored':<32}{m_alpha_only:>10.4f}"
          f"{(m_alpha_only/base - 1)*100:>13.1f}%")
    beat_both = mae(test, SHIPPED_W) < min(base, mae(test, 1.0))
    print(f"\n  shipped w=0.8 beats BOTH endpoints out of sample: "
          f"{'YES' if beat_both else 'NO'}")
    print(f"  best rule on the test fold: "
          f"{min([('consensus', base), ('guidance', mae(test,1.0)), ('w=0.8', mae(test,SHIPPED_W)), ('fitted w', mae(test,w_fit)), ('alpha+w', m_alpha), ('alpha only', m_alpha_only)], key=lambda r: r[1])[0]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="challenge/offline-data",
                    help="path to the challenge offline-data directory")
    ap.add_argument("--all", action="store_true",
                    help="also report HD/DE (needs FY-guide phasing; confounded)")
    ap.add_argument("--json", help="write triples to this path")
    a = ap.parse_args()

    print("GUIDANCE-WEIGHT STUDY — estimating w in  forecast = c + w x (g - c)")
    print("consensus + actual: yfinance earnings_dates (final pre-report estimate,")
    print("street basis both sides).  guide: corpus 8-K.  EPS only — no historical")
    print("revenue consensus exists on free data.\n")

    guides = adi_guidance(a.corpus)
    eps_guides = [g for g in guides if g["eps_guide"]]
    print(f"ADI: {len(guides)} earnings 8-Ks with guidance, "
          f"{len(eps_guides)} carrying an adjusted-EPS guide")
    reports = consensus_actuals("ADI")
    print(f"ADI: {len(reports)} reported quarters with consensus from yfinance")
    t, skipped = build_triples(eps_guides, reports)
    print(f"ADI: {len(t)} complete triples, {skipped} guides dropped "
          f"(no report in the 30-130 day window)")

    w = analyse(t, "ADI — adjusted EPS, quarterly dollar guidance (clean panel)")
    if w is not None:
        out_of_sample(t, "ADI")

    if a.json:
        Path(a.json).write_text(json.dumps(t, indent=2))
        print(f"\ntriples -> {a.json}")

    if a.all:
        print("\n" + "=" * 78)
        print("HD / DE deliberately NOT pooled: both guide the FULL YEAR, so a")
        print("triple requires the phasing rule (temper) to be applied first.")
        print("That rule is itself under test — pooling would confound the")
        print("estimate of w with the quality of the phasing. Estimate w on ADI,")
        print("then test whether it transfers, rather than fitting on a mixture.")

    print("\nNOTE ON SCOPE: one company. w estimated here is ADI's guidance")
    print("conservatism, not a universal constant. Widening the panel is the")
    print("single highest-value extension.")


if __name__ == "__main__":
    main()
