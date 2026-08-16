"""Row1_rev with two interchangeable feeds — drop in as excalibur/revenue_prior.py

The revenue ledger mirrors EPS but with different weights and one fewer row:

    forecast_Rev = consensus_rev x (1 + A_rev)
    A_rev = (Row1_rev + Row2_rev + Row5_rev) x Row3_rev      # NO Row4 (buybacks
                                                             # don't touch the top line)

Row 2 (guidance) is the WORKHORSE here, not Row 1: the analyst walk-down is an
EPS phenomenon (revenue beats ~60% at ~+1% vs EPS 75-78% at +2-5%), while
management guides revenue explicitly and narrowly.

Row 1 accepts EITHER feed, same machinery, swapped input:

  "revenue_surprise"  (actual_rev - consensus_rev_at_the_time) / consensus
                      needs a point-in-time revenue estimate history
                      (Primer / FMP historical-earning-calendar). Preferred.

  "guide_beat"        (actual_rev - guided_midpoint) / guided_midpoint
                      needs only the cached 8-K guidance + actual revenue.
                      Always available offline. Measures the sandbag at source.

Whichever fires is recorded in the ledger row's `source` so the glass box stays
honest about which prior it used.
"""
import json
import statistics
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import params as P
from .engine import LedgerRow, row1_firm_prior, row3_damp, row5_evidence
from .universe import COMPS, SECTOR_BASKET

CACHE = Path(__file__).resolve().parent.parent / "cache"
RAW = CACHE / "raw"

PBEAT_BASE_RATE_REV = 0.60      # revenue beat rate, vs 0.77 for EPS
GUIDANCE_GAP_FRACTION_REV = 0.8  # Row 2 carries more weight than EPS's 0.5:
                                 # revenue guides are tighter and more binding


# --------------------------------------------------------------- actuals I/O

def revenue_actuals(ticker):
    """{period_end (YYYY-MM-DD): revenue} oldest->newest.

    Prefers cache/raw/<T>/revenue_actuals.json (yfinance quarterly_income_stmt
    'TotalRevenue' — fresher and free of the XBRL tag trap); falls back to
    gaap.json. NOTE: fetch_gaap.quarterly_series returns the FIRST revenue tag
    with any data, which strands NVDA on 2017-2020 and TJX on 2013-2015 —
    merge across tags before trusting gaap.json here.
    """
    f = RAW / ticker / "revenue_actuals.json"
    if f.exists():
        d = json.loads(f.read_text())
    else:
        g = RAW / ticker / "gaap.json"
        if not g.exists():
            return {}
        d = {k: v["revenue"] for k, v in json.loads(g.read_text()).items()
             if v.get("revenue")}
    return dict(sorted(d.items()))


def _d(s):
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def year_ago_quarter(actuals, period_end, tol_days=45):
    """Revenue for the same fiscal quarter one year earlier.

    DATE-matched, not index-matched. EDGAR series contain holes (a quarter
    whose revenue or net income is missing), and stepping back 4 INDEXES
    across a hole silently returns the wrong quarter. We look for the period
    end nearest to target-365d and reject it if it is not within tolerance.
    """
    if not actuals:
        return None
    target = _d(period_end).toordinal() - 365
    best = min(actuals, key=lambda k: abs(_d(k).toordinal() - target))
    return actuals[best] if abs(_d(best).toordinal() - target) <= tol_days else None


def _fiscal_year_window(actuals, period_end, tol_days=45):
    """The four quarter-ends forming the fiscal year that ENDS at period_end.
    Returns None unless all four are present and span ~365 days."""
    if period_end not in actuals:
        return None
    ends = [period_end]
    cur = period_end
    for _ in range(3):
        target = _d(cur).toordinal() - 91
        prior = [k for k in actuals if k < cur]
        if not prior:
            return None
        nxt = min(prior, key=lambda k: abs(_d(k).toordinal() - target))
        if abs(_d(nxt).toordinal() - target) > tol_days:
            return None
        ends.append(nxt)
        cur = nxt
    span = _d(ends[0]).toordinal() - _d(ends[-1]).toordinal()
    return ends if 250 <= span <= 300 else None   # 3 steps of ~91d


def seasonal_share(actuals, period_end, lookback_years=3):
    """This fiscal quarter's historical share of its fiscal year's revenue.
    Used to allocate ANNUAL guidance down to one quarter.

    Only counts years where the full four-quarter window is present, so a hole
    in the series drops that year rather than corrupting the ratio. Falls back
    to 0.25 (an equal-quarters prior) if nothing clean is available.
    """
    shares = []
    cur = max((k for k in actuals if k < period_end), default=None)
    while cur and len(shares) < lookback_years:
        window = _fiscal_year_window(actuals, cur)
        if window:
            total = sum(actuals[k] for k in window)
            if total:
                shares.append(actuals[cur] / total)
        target = _d(cur).toordinal() - 365
        prior = [k for k in actuals if k < cur]
        if not prior:
            break
        nxt = min(prior, key=lambda k: abs(_d(k).toordinal() - target))
        cur = nxt if abs(_d(nxt).toordinal() - target) <= 45 else None
    return statistics.median(shares) if shares else 0.25


# ----------------------------------------------- guidance: typed -> dollars

@dataclass
class GuidanceSpec:
    """What the LLM extracts. It NEVER computes the dollar figure — that is
    the job of to_quarterly_dollars() below, in plain auditable code."""
    kind: str          # DOLLARS | GROWTH_PCT | COMP_PCT | ARR
    period: str        # QUARTER | YEAR
    low: float | None
    high: float | None
    basis: str = "reported"      # reported | constant_currency
    source: str = ""

    @property
    def midpoint(self):
        vals = [v for v in (self.low, self.high) if v is not None]
        return sum(vals) / len(vals) if vals else None


def to_quarterly_dollars(spec, ticker, period_end, comp_spread=None):
    """Normalise any guidance shape to an implied quarterly revenue in dollars.
    Returns (value, how) — `how` is the audit trail for the ledger. None if the
    shape cannot be converted (ARR), so Row 2 falls back to zero rather than guessing.
    """
    if spec is None or spec.midpoint is None:
        return None, "no guidance parsed"
    actuals = revenue_actuals(ticker)
    mid = spec.midpoint

    if spec.kind == "DOLLARS" and spec.period == "QUARTER":
        return mid, f"guided ${mid/1e9:.2f}bn directly"

    if spec.kind == "DOLLARS" and spec.period == "YEAR":
        share = seasonal_share(actuals, period_end)
        return mid * share, (f"annual guide ${mid/1e9:.1f}bn x seasonal share "
                             f"{share:.1%}")

    if spec.kind == "GROWTH_PCT" and spec.period == "QUARTER":
        base = year_ago_quarter(actuals, period_end)
        if not base:
            return None, "no year-ago quarter"
        return base * (1 + mid), (f"guided +{mid:.1%} on year-ago "
                                  f"${base/1e9:.2f}bn")

    if spec.kind == "GROWTH_PCT" and spec.period == "YEAR":
        keys = sorted(k for k in actuals if k < period_end)
        if len(keys) < 8:
            return None, "insufficient history for annual allocation"
        prior_fy = sum(actuals[k] for k in keys[-4:])
        share = seasonal_share(actuals, period_end)
        return prior_fy * (1 + mid) * share, (
            f"FY guide +{mid:.1%} on ${prior_fy/1e9:.1f}bn x seasonal share "
            f"{share:.1%}")

    if spec.kind == "COMP_PCT":
        # comp sales exclude new/closed stores; total growth runs above comps by
        # a fairly stable spread (new square footage). Measure it, don't guess.
        base = year_ago_quarter(actuals, period_end)
        if not base:
            return None, "no year-ago quarter"
        spread = comp_spread if comp_spread is not None else 0.0
        return base * (1 + mid + spread), (
            f"comp guide +{mid:.1%} + measured total-vs-comp spread "
            f"{spread:+.1%} on ${base/1e9:.2f}bn")

    return None, f"{spec.kind}/{spec.period} not convertible — Row 2 = 0"


# ------------------------------------------------------- the two Row-1 feeds

@dataclass
class PriorFeed:
    name: str      # revenue_surprise | guide_beat
    series: list   # winsorized fractions, oldest -> newest
    source: str    # provenance string shown in the ledger


def _winsor(x):
    return max(-P.WINSOR, min(P.WINSOR, x))


def revenue_surprise_series(ticker, n=8):
    """FEED A (preferred). Needs cache/raw/<T>/revenue_surprises.json:
        [{"period_end": "2026-05-02", "actual": 1.2e10, "estimate": 1.18e10}, ...]
    written by whatever source delivers point-in-time revenue estimates
    (Primer adapter, or FMP historical/earning_calendar). Returns None if absent
    so the caller falls through to feed B."""
    f = RAW / ticker / "revenue_surprises.json"
    if not f.exists():
        return None
    rows = sorted(json.loads(f.read_text()), key=lambda r: r["period_end"])
    series = [_winsor(r["actual"] / r["estimate"] - 1)
              for r in rows[-n:] if r.get("estimate")]
    if len(series) < 4:
        return None
    return PriorFeed("revenue_surprise", series,
                     f"{len(series)}q revenue actual vs point-in-time consensus")


def guide_beat_series(ticker, n=8):
    """FEED B (always available offline). Needs cache/raw/<T>/guidance_history.json:
        [{"period_end": "2026-05-02", "guided_midpoint": 9.1e10}, ...]
    built once by running the guidance extractor over the cached 8-K exhibits.
    Pairs each guided midpoint with the revenue that actually landed."""
    f = RAW / ticker / "guidance_history.json"
    actuals = revenue_actuals(ticker)
    if not f.exists() or not actuals:
        return None
    rows = sorted(json.loads(f.read_text()), key=lambda r: r["period_end"])
    series = []
    for r in rows[-n:]:
        guided, actual = r.get("guided_midpoint"), actuals.get(r["period_end"])
        if guided and actual:
            series.append(_winsor(actual / guided - 1))
    if len(series) < 4:
        return None
    return PriorFeed("guide_beat", series,
                     f"{len(series)}q revenue vs management's own guidance midpoint")


def build_feed(ticker, prefer=None):
    """Pick the Row-1 feed. Preference order is explicit and logged."""
    order = ([prefer] if prefer else []) + ["revenue_surprise", "guide_beat"]
    builders = {"revenue_surprise": revenue_surprise_series,
                "guide_beat": guide_beat_series}
    for name in dict.fromkeys(order):
        feed = builders[name](ticker)
        if feed:
            return feed
    return None


def sector_feed_median(ticker, prefer=None):
    """Same feed type, taken across the comp basket."""
    meds = []
    for peer in COMPS[SECTOR_BASKET[ticker]]:
        feed = build_feed(peer, prefer)
        if feed and len(feed.series) >= 8:
            meds.append(statistics.median(feed.series))
    return statistics.median(meds) if meds else None


# ------------------------------------------------------------------- Row 1

def row1_rev(ticker, lam=None, reference_std=None, prefer=None):
    """Returns (value, LedgerRow). Reuses the EPS reliability/shrinkage maths
    verbatim — only the input series changes."""
    feed = build_feed(ticker, prefer)
    if feed is None:
        return 0.0, LedgerRow("Row1_rev firm+sector prior", 0.0,
                              "no usable feed",
                              "neither revenue-surprise nor guide-beat history available")
    sector_med = sector_feed_median(ticker, prefer=feed.name)
    value, reliability = row1_firm_prior(
        statistics.median(feed.series),
        statistics.stdev(feed.series) if len(feed.series) > 1 else 0.0,
        sector_med, lam, reference_std)
    return value, LedgerRow(
        "Row1_rev firm+sector prior", value, feed.source,
        f"feed={feed.name} reliability={reliability:.2f} "
        f"sector_med={'n/a' if sector_med is None else format(sector_med, '.2%')}")


# ------------------------------------------------------------ full revenue ledger

@dataclass
class RevenueForecast:
    ticker: str
    consensus: float
    rows: list
    damp: float
    a_total: float
    revenue: float
    interval: tuple
    p_beat: float
    audit: dict


def forecast_revenue(ticker, consensus_rev, period_end, guidance=None,
                     qualitative_signal=0.0, revision_30d=None,
                     comp_spread=None, lam=None, reference_std=None, prefer=None):
    r1, row1 = row1_rev(ticker, lam, reference_std, prefer)

    guided, how = to_quarterly_dollars(guidance, ticker, period_end, comp_spread)
    if guided and consensus_rev:
        gap = guided / consensus_rev - 1.0
        r2 = GUIDANCE_GAP_FRACTION_REV * gap        # signed BOTH ways (U1):
                                                    # a guide-down must pull down
    else:
        r2, gap = 0.0, None
    row2 = LedgerRow("Row2_rev guidance gap", r2, "8-K press release",
                     how + (f" -> gap {gap:+.2%} vs consensus" if gap is not None else ""))

    r5 = row5_evidence(qualitative_signal)
    row5 = LedgerRow("Row5_rev evidence (capped)", r5, "LLM: filings/news",
                     "volume / pricing / FX / segment mix")

    feed = build_feed(ticker, prefer)
    damp = row3_damp(revision_30d, feed.series[-1] if feed else None)
    a_total = (r1 + r2 + r5) * damp

    series = feed.series if feed else []
    if len(series) >= 4:
        qs = statistics.quantiles(series, n=4)
        centre = consensus_rev * (1 + a_total)      # Reading B: centre on OUR forecast
        interval = (centre * (1 + qs[0] - statistics.median(series)),
                    centre * (1 + qs[2] - statistics.median(series)))
    else:
        interval = (consensus_rev * (1 + a_total),) * 2

    hit = sum(1 for s in series if s > 0) / len(series) if series else None
    p = (0.5 * hit + 0.5 * PBEAT_BASE_RATE_REV) if hit is not None else PBEAT_BASE_RATE_REV

    return RevenueForecast(
        ticker=ticker, consensus=consensus_rev,
        rows=[row1, row2, row5], damp=damp, a_total=a_total,
        revenue=consensus_rev * (1 + a_total), interval=interval, p_beat=p,
        audit={"row1_feed": feed.name if feed else None, "guidance_conversion": how},
    )


# --------------------------------------------------------- LLM extraction schema

GUIDANCE_EXTRACT_SYSTEM = """You extract REVENUE guidance from an earnings press \
release. You never compute or convert anything — you only report what management \
said, in the units they said it. Reply with ONLY this JSON:
{"kind": "DOLLARS" | "GROWTH_PCT" | "COMP_PCT" | "ARR" | "NONE",
 "period": "QUARTER" | "YEAR" | null,
 "low": float | null, "high": float | null,
 "basis": "reported" | "constant_currency",
 "quote": "<the sentence you took it from, verbatim>"}
Rules:
- DOLLARS: absolute revenue (e.g. "$91.0 billion plus or minus 2%") -> low/high
  in DOLLARS (91e9*0.98, 91e9*1.02).
- GROWTH_PCT: growth in net sales/revenue (e.g. "net sales to grow 4% to 5%")
  -> low/high as FRACTIONS (0.04, 0.05).
- COMP_PCT: comparable/same-store sales only. Do NOT report it as GROWTH_PCT —
  comps exclude new stores and the engine corrects for that separately.
- ARR: annual recurring revenue. Report it, but it is not quarterly revenue.
- If management gave a single point, set low = high. If no revenue guidance,
  kind = "NONE". Never infer a number that is not stated."""
