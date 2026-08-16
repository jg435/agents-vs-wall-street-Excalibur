#!/usr/bin/env python3
"""Settle it in one run: does FMP (or Finnhub) give us a REVENUE surprise history?

We need, per past quarter: actual revenue AND the revenue estimate that stood
at the time. EPS-only endpoints don't help — we already have EPS from yfinance.

Usage:
    FMP_API_KEY=xxx python fmp_probe.py
    FMP_API_KEY=xxx FINNHUB_API_KEY=yyy python fmp_probe.py NVDA WMT TJX

Stdlib only. Read-only. Prints a verdict per endpoint.
"""
import json
import os
import sys
import urllib.error
import urllib.request

TICKERS = sys.argv[1:] or ["NVDA", "WMT", "HD"]
FMP_KEY = os.environ.get("FMP_API_KEY")
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY")

# Endpoints that MIGHT carry revenue actual + estimate per historical quarter.
# 'pit' = is the estimate point-in-time (as it stood at the report) or a
# current estimate retro-applied to a past period? The latter is leakage.
FMP_ENDPOINTS = [
    ("v3 historical/earning_calendar",
     "https://financialmodelingprep.com/api/v3/historical/earning_calendar/{t}?apikey={k}",
     ("revenue", "revenueEstimated"), "PIT (estimate as of report) — the one we want"),
    ("stable earnings",
     "https://financialmodelingprep.com/stable/earnings?symbol={t}&apikey={k}",
     ("revenue", "revenueEstimated"), "PIT if populated — newer naming of the above"),
    ("v3 analyst-estimates (quarter)",
     "https://financialmodelingprep.com/api/v3/analyst-estimates/{t}?period=quarter&apikey={k}",
     ("estimatedRevenueAvg", "estimatedRevenueLow", "estimatedRevenueHigh"),
     "NOT PIT — current estimates for past periods. Usable for the FORWARD "
     "quarter only; using it historically = lookahead"),
    ("stable analyst-estimates",
     "https://financialmodelingprep.com/stable/analyst-estimates?symbol={t}&period=quarter&apikey={k}",
     ("estimatedRevenueAvg",), "NOT PIT — same caveat"),
    ("v3 earnings-surprises",
     "https://financialmodelingprep.com/api/v3/earnings-surprises/{t}?apikey={k}",
     ("actualEarningResult", "estimatedEarning"), "EPS only — expected to be useless for revenue"),
]


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "excalibur-probe"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:200]
        return e.code, body
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def coverage(rows, actual_field, est_field):
    """How many historical quarters have BOTH numbers? Plus the date range."""
    both, dates = 0, []
    for r in rows:
        if not isinstance(r, dict):
            continue
        a, e = r.get(actual_field), r.get(est_field)
        if a not in (None, 0) and e not in (None, 0):
            both += 1
            d = r.get("date") or r.get("fiscalDateEnding") or r.get("period")
            if d:
                dates.append(str(d)[:10])
    return both, (min(dates), max(dates)) if dates else None


def probe_fmp():
    print("=" * 78)
    print("FMP")
    print("=" * 78)
    if not FMP_KEY:
        print("  FMP_API_KEY not set — get a free key at "
              "financialmodelingprep.com/developer and re-run.\n")
        return
    for name, tmpl, fields, note in FMP_ENDPOINTS:
        print(f"\n--- {name}")
        print(f"    note: {note}")
        for t in TICKERS:
            status, data = fetch(tmpl.format(t=t, k=FMP_KEY))
            if status != 200:
                print(f"    {t:5s} HTTP {status}: {str(data)[:120]}")
                continue
            if isinstance(data, dict):
                # FMP returns {"Error Message": ...} on plan restrictions
                msg = data.get("Error Message") or data.get("message") or str(data)[:120]
                print(f"    {t:5s} non-list response: {msg[:120]}")
                continue
            if not data:
                print(f"    {t:5s} empty list (endpoint exists, no data on this plan)")
                continue
            present = [f for f in fields if any(
                isinstance(r, dict) and f in r for r in data[:5])]
            missing = [f for f in fields if f not in present]
            line = f"    {t:5s} {len(data):4d} rows | fields present: {present or 'NONE'}"
            if missing:
                line += f" | missing: {missing}"
            print(line)
            if len(fields) >= 2 and len(present) >= 2:
                n, rng = coverage(data, fields[0], fields[1])
                print(f"          -> {n} quarters with BOTH "
                      f"{fields[0]} and {fields[1]}"
                      + (f", {rng[0]} .. {rng[1]}" if rng else ""))
                if n >= 8:
                    print("          *** USABLE: 8+ quarters of revenue surprise ***")
            if data and isinstance(data[0], dict):
                print(f"          sample keys: {sorted(data[0])[:12]}")


def probe_finnhub():
    print("\n" + "=" * 78)
    print("FINNHUB")
    print("=" * 78)
    if not FINNHUB_KEY:
        print("  FINNHUB_API_KEY not set — skipping (optional second opinion).\n")
        return
    eps = ("https://finnhub.io/api/v1/stock/earnings?symbol={t}&token={k}",
           "earnings surprises (expected EPS-only)")
    rev = ("https://finnhub.io/api/v1/stock/revenue-estimate?symbol={t}"
           "&freq=quarterly&token={k}", "revenue estimates (forward; check for past periods)")
    for tmpl, label in (eps, rev):
        print(f"\n--- {label}")
        for t in TICKERS:
            status, data = fetch(tmpl.format(t=t, k=FINNHUB_KEY))
            if status != 200:
                print(f"    {t:5s} HTTP {status}: {str(data)[:120]}")
                continue
            rows = data.get("data", data) if isinstance(data, dict) else data
            if not rows:
                print(f"    {t:5s} empty")
                continue
            print(f"    {t:5s} {len(rows)} rows | sample keys: "
                  f"{sorted(rows[0])[:12] if isinstance(rows[0], dict) else type(rows[0])}")


def verdict():
    print("\n" + "=" * 78)
    print("HOW TO READ THIS")
    print("=" * 78)
    print("""
  You need ONE endpoint showing 8+ quarters with BOTH an actual revenue and a
  point-in-time revenue estimate. If you get that:

    -> build Row1_rev from the true revenue-surprise series (feed "surprise"),
       AND a revenue backtest becomes possible — run it.

  If every endpoint is EPS-only, empty, or plan-restricted:

    -> fall back to the guide-beat feed (feed "guide_beat"), which needs no
       external data. Say the limitation out loud rather than substituting
       analyst-estimates retro-applied to past quarters — that is lookahead,
       and it is the exact sin the RFS 2023 paper got flagged for.

  WATCH FOR: analyst-estimates endpoints happily return rows for past periods.
  Those are TODAY'S estimates, not the estimate that stood before the print.
  Only historical/earning_calendar-style 'revenueEstimated' is point-in-time.
""")


if __name__ == "__main__":
    print(f"tickers: {', '.join(TICKERS)}\n")
    probe_fmp()
    probe_finnhub()
    verdict()
