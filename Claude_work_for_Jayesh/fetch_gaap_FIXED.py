"""GAAP fundamentals from SEC EDGAR XBRL companyfacts (plan A.4 rule 1).

PURPOSE: margins / share counts / revenue history for the AUDITOR's
margin-vs-history check and revenue forecasts. NEVER for surprise math —
surprises stay on the non-GAAP street basis from yfinance (like-for-like
with analyst consensus, which is also street basis).

Usage: python -m excalibur.fetch_gaap
Output: cache/raw/<TICKER>/gaap.json  {quarter_end: {revenue, net_income,
        eps_diluted, net_margin}}

--- FIXED 2026-08-15 -----------------------------------------------------
Three bugs in quarterly_series():

 1. TAG SHADOWING (the one that bit). It returned the FIRST tag in the list
    that had ANY data, and never looked at the rest. Companies switch revenue
    tags over time (ASC 606 moved most filers from SalesRevenueNet /
    Revenues to RevenueFromContractWithCustomer*). So a filer whose OLD data
    sits under the first-listed tag got stranded there:
        NVDA -> 2017-04-30 .. 2020-01-26   (six years stale)
        TJX  -> 2013-05-04 .. 2015-08-01   (eleven years stale)
    Both then silently poisoned the auditor's margin-vs-history check.
    FIX: merge across ALL tags, iterating lowest-priority first so a
    higher-priority tag overwrites on overlapping periods.

 2. QUARTER DETECTION BY MONTH ARITHMETIC. `(month(end) - month(start)) % 12`
    in 2..4 is a proxy for "about a quarter" that also admits 4-month stubs
    and mis-handles 52/53-week retail calendars.
    FIX: real day count, 75..115 days.

 3. RESTATEMENTS RESOLVED BY ITERATION ORDER. The old comment said "later
    filings overwrite", but companyfacts unit arrays are not guaranteed to be
    filing-ordered.
    FIX: keep the observation with the latest `filed` date explicitly.

 4. MISSING Q4 (surfaced by fixing 1-3). Filers report Q1-Q3 as discrete
    quarterly durations in 10-Qs, but Q4 exists only inside the 10-K's ANNUAL
    figure — so every fiscal year had a hole:
        NVDA ... 2025-10-26, [2026-01-25 MISSING], 2026-04-26 ...
    Holes are worse than they look: revenue_prior.year_ago_quarter() and
    seasonal_share() walk the series by INDEX, so a gap silently returns the
    wrong quarter.
    FIX: derive Q4 = FY - (Q1 + Q2 + Q3) whenever the annual duration and all
    three interior quarters are present. Derived values are marked so the
    audit trail stays honest.
--------------------------------------------------------------------------
"""
import json
from datetime import date
from pathlib import Path

from .fetch import log_provenance
from .fetch_text import cik_for, get
from .universe import forecast_tickers

CACHE = Path(__file__).resolve().parent.parent / "cache"
RAW = CACHE / "raw"

# Highest priority first. Merged, not first-match.
REVENUE_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "Revenues", "SalesRevenueNet"]
INCOME_TAGS = ["NetIncomeLoss"]
EPS_TAGS = ["EarningsPerShareDiluted"]

MIN_Q_DAYS, MAX_Q_DAYS = 75, 115     # a fiscal quarter, incl. 52/53-week calendars
MIN_Y_DAYS, MAX_Y_DAYS = 340, 380    # a fiscal year, incl. the 53-week year


def _iso(s):
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def _durations(facts, tags, lo, hi):
    """{(start, end): value} for durations of lo..hi days, merged across tags,
    latest-filed wins. Shared by the quarterly and annual passes."""
    merged = {}
    for tag in reversed(tags):                     # lowest priority first
        node = facts.get("us-gaap", {}).get(tag)
        if not node:
            continue
        best = {}
        for unit, unit_vals in node.get("units", {}).items():
            if unit not in ("USD", "USD/shares"):
                continue
            for v in unit_vals:
                start, end, val = v.get("start"), v.get("end"), v.get("val")
                if not (start and end) or val is None:
                    continue
                if v.get("form") not in ("10-Q", "10-K"):
                    continue
                try:
                    days = (_iso(end) - _iso(start)).days
                except Exception:
                    continue
                if not (lo <= days <= hi):
                    continue
                filed = v.get("filed") or ""
                key = (start, end)
                if key not in best or filed >= best[key][0]:
                    best[key] = (filed, float(val))
        merged.update({k: v[1] for k, v in best.items()})
    return merged


def derive_q4(quarters, annuals):
    """Q4 = FY - (Q1+Q2+Q3). Returns {end: value} for the quarters we can fill.

    quarters/annuals are {(start, end): value}. For each fiscal year we take
    the three quarters lying strictly inside it and subtract.
    """
    filled = {}
    for (fy_start, fy_end), fy_val in annuals.items():
        inside = [(s, e, v) for (s, e), v in quarters.items()
                  if s >= fy_start and e <= fy_end]
        if len(inside) != 3:
            continue                      # ambiguous — don't guess
        q4_val = fy_val - sum(v for _, _, v in inside)
        q4_start = max(e for _, e, _ in inside)     # day after last interior Q
        if fy_end in filled or q4_val <= 0:
            continue
        span = (_iso(fy_end) - _iso(q4_start)).days
        if MIN_Q_DAYS <= span <= MAX_Q_DAYS:
            filled[fy_end] = q4_val
    return filled


def quarterly_series(facts, tags, fill_q4=True):
    """{quarter_end: value}, merged across every tag, quarterly durations only,
    with Q4 derived from the annual figure where it is missing.

    Returns (series, derived_ends) so callers can mark derived values.
    """
    q = _durations(facts, tags, MIN_Q_DAYS, MAX_Q_DAYS)
    series = {end: v for (_, end), v in q.items()}
    derived = set()
    if fill_q4:
        annual = _durations(facts, tags, MIN_Y_DAYS, MAX_Y_DAYS)
        for end, val in derive_q4(q, annual).items():
            if end not in series:
                series[end] = val
                derived.add(end)
    return series, derived


def fetch_gaap(ticker, n=12):
    cik = cik_for(ticker)
    facts = json.loads(get(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"))["facts"]
    rev, rev_derived = quarterly_series(facts, REVENUE_TAGS)
    ni, ni_derived = quarterly_series(facts, INCOME_TAGS)
    eps, _ = quarterly_series(facts, EPS_TAGS, fill_q4=False)  # EPS doesn't sum
    quarters = sorted(set(rev) & set(ni), reverse=True)[:n]
    out = {}
    for q in quarters:
        row = {"revenue": rev[q], "net_income": ni[q],
               "eps_diluted_gaap": eps.get(q),
               "net_margin": ni[q] / rev[q] if rev[q] else None}
        if q in rev_derived or q in ni_derived:
            row["derived_q4"] = True     # FY minus Q1-Q3; audit trail
        out[q] = row
    (RAW / ticker / "gaap.json").write_text(json.dumps(out, indent=2))
    return out


def gaps(ends):
    """Quarter-ends that are more than ~1 quarter apart = a hole in the series.
    Index-based lookups (year_ago_quarter, seasonal_share) are wrong across a hole."""
    out = []
    for a, b in zip(ends, ends[1:]):
        if (_iso(b) - _iso(a)).days > MAX_Q_DAYS:
            out.append(f"{a}->{b}")
    return out


def main():
    problems = []
    for t in forecast_tickers():
        try:
            out = fetch_gaap(t)
            ks = sorted(out)
            span = f"{ks[0]} .. {ks[-1]}" if ks else "EMPTY"
            n_der = sum(1 for v in out.values() if v.get("derived_q4"))
            holes = gaps(ks)
            flags = []
            if ks and ks[-1] < "2025-10-01":
                flags.append(f"STALE (latest {ks[-1]})")
            if holes:
                flags.append(f"GAPS {holes}")
            print(f"{t:5s} {len(out):2d}q  {span}  (Q4 derived: {n_der})"
                  + ("  !! " + "; ".join(flags) if flags else ""))
            log_provenance(t, "gaap_companyfacts", True,
                           note=f"n={len(out)}q {span} derived_q4={n_der}")
            if flags:
                problems.append((t, flags))
        except Exception as e:
            log_provenance(t, "gaap_companyfacts", False, note=str(e)[:200])
            print(f"{t:5s} FAIL: {e}")
            problems.append((t, [str(e)[:80]]))
    if problems:
        print("\n!! do NOT trust the auditor margin check or the revenue "
              "year-ago lookups for:")
        for t, f in problems:
            print(f"   {t}: {'; '.join(f)}")
    else:
        print("\nall names current and contiguous.")


if __name__ == "__main__":
    main()
