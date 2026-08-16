"""Consensus anchors (build step 2): fetched TODAY from public sources.

The scoring benchmark is frozen Wall Street consensus we can't see; visible
consensus is our best reconstruction of it. yfinance covers HD/ADI/DE EPS +
revenue. Where no public consensus exists the entry is null WITH the reason,
so the engine anchors on guidance instead — never a silent gap.

Usage: python -m agent.consensus   -> cache/consensus.json
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "cache"


def next_report_estimates(ticker):
    """(eps_estimate, report_date) from the earnings calendar row tied to the
    next report — immune to fiscal-label drift — plus revenue/EPS 0q means."""
    t = yf.Ticker(ticker)
    out = {}
    ed = t.get_earnings_dates(limit=8)
    if ed is not None:
        upcoming = ed[ed["Reported EPS"].isna()]
        if len(upcoming):
            row = upcoming.iloc[-1]
            out["eps"] = float(row["EPS Estimate"])
            out["report_date"] = str(row.name.date())
    re_ = t.revenue_estimate
    if re_ is not None and "0q" in re_.index:
        out["revenue_usdm"] = float(re_.loc["0q", "avg"]) / 1e6
    ee = t.earnings_estimate
    if ee is not None and "0q" in ee.index:
        out["eps_range"] = [float(ee.loc["0q", "low"]), float(ee.loc["0q", "high"])]
        out.setdefault("eps", float(ee.loc["0q", "avg"]))
    return out


def main():
    C = {"fetched_at": datetime.now(timezone.utc).isoformat(),
         "source": "yfinance (public, fetched during event)"}
    for tk in ["HD", "ADI", "DE"]:
        try:
            C[tk] = next_report_estimates(tk)
            print(tk, C[tk])
        except Exception as e:
            C[tk] = {"error": str(e)[:150]}
            print(tk, "FAIL", e)
    try:
        C["HAS"] = next_report_estimates("HAS.L")
        print("HAS", C["HAS"])
    except Exception as e:
        C["HAS"] = {"error": str(e)[:150]}
        print("HAS FAIL", e)

    C["no_public_consensus"] = {
        "HD.comparable_sales_pct": "no public consensus feed; anchor = FY guidance phased to Q2",
        "ADI.adj_gross_margin_pct": "not guided, no consensus feed; anchor = trailing actuals + revenue link",
        "DE.ppa_op_profit_usdm": "segment-level; anchor = segment guidance x FY25 Q3 base",
        "HAS.net_fees_gbpm": "anchor = FY25 base x quarterly LFL path (trading updates)",
        "HAS.pre_exceptional_op_profit_gbpm": "company-published consensus range in trading update",
        "HAS.pre_exceptional_basic_eps_gbp": "derived from op profit, interest, tax, shares",
    }
    CACHE.mkdir(exist_ok=True)
    (CACHE / "consensus.json").write_text(json.dumps(C, indent=2))
    print("-> cache/consensus.json")


if __name__ == "__main__":
    main()
