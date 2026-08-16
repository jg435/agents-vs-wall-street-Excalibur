"""Smoke test revenue_prior against the real cache."""
from excalibur.revenue_prior import (GuidanceSpec, to_quarterly_dollars,
                                     revenue_actuals, year_ago_quarter,
                                     seasonal_share, build_feed, forecast_revenue)

print("=== revenue actuals available (from gaap.json fallback) ===")
for t in ["WMT", "TGT", "NVDA"]:
    a = revenue_actuals(t)
    ks = sorted(a)
    print(f"  {t:5s} n={len(a)}  {ks[0] if ks else '-'} .. {ks[-1] if ks else '-'}")

print("\n=== guidance conversion: all five shapes ===")
# WMT: real guide from the cached 8-K -> net sales +4% to +5%, quarterly
wmt_end = sorted(revenue_actuals("WMT"))[-1]
cases = [
    ("NVDA dollars/quarter", "NVDA",
     GuidanceSpec("DOLLARS", "QUARTER", 91e9 * 0.98, 91e9 * 1.02), None),
    ("WMT growth%/quarter", "WMT",
     GuidanceSpec("GROWTH_PCT", "QUARTER", 0.04, 0.05), None),
    ("TGT growth%/YEAR", "TGT",
     GuidanceSpec("GROWTH_PCT", "YEAR", 0.03, 0.05), None),
    ("TJX comp%/quarter", "TJX",
     GuidanceSpec("COMP_PCT", "QUARTER", 0.03, 0.04), 0.015),
    ("CRWD ARR (should refuse)", "CRWD",
     GuidanceSpec("ARR", "YEAR", 5.792e9, 5.792e9), None),
]
for label, t, spec, spread in cases:
    a = revenue_actuals(t)
    pe = sorted(a)[-1] if a else "2026-05-02"
    val, how = to_quarterly_dollars(spec, t, pe, comp_spread=spread)
    shown = "None" if val is None else f"${val/1e9:.2f}bn"
    print(f"  {label:28s} -> {shown:>10s}   [{how}]")

print("\n=== seasonality + year-ago lookups (WMT) ===")
a = revenue_actuals("WMT")
pe = sorted(a)[-1]
print(f"  latest period {pe}: ${a[pe]/1e9:.1f}bn")
print(f"  year-ago quarter: ${(year_ago_quarter(a, pe) or 0)/1e9:.1f}bn")
print(f"  seasonal share of FY: {seasonal_share(a, pe):.1%}")

print("\n=== Row-1 feed availability (neither file exists yet -> expect None) ===")
for t in ["NVDA", "WMT"]:
    print(f"  {t:5s} feed = {build_feed(t)}")

print("\n=== end-to-end revenue forecast, guidance-only (the Tier-3 ship) ===")
fc = forecast_revenue("WMT", consensus_rev=178.0e9, period_end=wmt_end,
                      guidance=GuidanceSpec("GROWTH_PCT", "QUARTER", 0.04, 0.05))
print(f"  consensus  ${fc.consensus/1e9:.2f}bn")
print(f"  forecast   ${fc.revenue/1e9:.2f}bn   A_total {fc.a_total:+.2%}  damp {fc.damp:.2f}")
print(f"  interval   ${fc.interval[0]/1e9:.2f}bn - ${fc.interval[1]/1e9:.2f}bn")
print(f"  fcst inside its own interval? "
      f"{fc.interval[0] <= fc.revenue <= fc.interval[1]}")
print(f"  P(rev beat) {fc.p_beat:.0%}   audit {fc.audit}")
for r in fc.rows:
    print(f"    {r.name:32s} {r.value:+.2%}  [{r.source}] {r.note}")

print("\n=== same, with a GUIDE-DOWN (checks U1 sign convention) ===")
fc2 = forecast_revenue("WMT", consensus_rev=178.0e9, period_end=wmt_end,
                       guidance=GuidanceSpec("GROWTH_PCT", "QUARTER", -0.02, -0.01))
print(f"  forecast ${fc2.revenue/1e9:.2f}bn  A_total {fc2.a_total:+.2%} "
      f"(must be NEGATIVE — EPS Row2 would have returned 0 here)")
