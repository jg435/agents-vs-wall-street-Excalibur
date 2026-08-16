"""Prove the fetch_gaap fix against live EDGAR: OLD logic vs NEW logic."""
import json, sys, time
from datetime import date
from urllib.request import Request, urlopen

UA = {"User-Agent": "Team JLV hackathon jgupta0700@gmail.com"}
REVENUE_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "Revenues", "SalesRevenueNet"]

def get(url):
    with urlopen(Request(url, headers=UA), timeout=40) as r:
        return r.read()

def cik_for(t):
    m = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    for row in m.values():
        if row["ticker"] == t:
            return int(row["cik_str"])
    raise KeyError(t)

def _iso(s): return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))

def OLD(facts, tags):
    for tag in tags:
        node = facts.get("us-gaap", {}).get(tag)
        if not node: continue
        out = {}
        for unit_vals in node["units"].values():
            for v in unit_vals:
                start, end = v.get("start"), v.get("end")
                if not (start and end and v.get("val") is not None): continue
                days = (int(end[5:7]) - int(start[5:7])) % 12
                if 2 <= days <= 4 and v.get("form") in ("10-Q", "10-K"):
                    out[end] = float(v["val"])
        if out: return out
    return {}

def NEW(facts, tags):
    merged = {}
    for tag in reversed(tags):
        node = facts.get("us-gaap", {}).get(tag)
        if not node: continue
        best = {}
        for unit, unit_vals in node.get("units", {}).items():
            if unit not in ("USD", "USD/shares"): continue
            for v in unit_vals:
                start, end, val = v.get("start"), v.get("end"), v.get("val")
                if not (start and end) or val is None: continue
                if v.get("form") not in ("10-Q", "10-K"): continue
                try: days = (_iso(end) - _iso(start)).days
                except Exception: continue
                if not (75 <= days <= 115): continue
                filed = v.get("filed") or ""
                if end not in best or filed >= best[end][0]:
                    best[end] = (filed, float(val))
        merged.update({k: v[1] for k, v in best.items()})
    return merged

for t in (sys.argv[1:] or ["NVDA", "TJX", "WMT"]):
    facts = json.loads(get(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_for(t):010d}.json"))["facts"]
    o, n = OLD(facts, REVENUE_TAGS), NEW(facts, REVENUE_TAGS)
    ok, nk = sorted(o), sorted(n)
    print(f"\n=== {t} ===")
    print(f"  OLD  n={len(ok):3d}  {ok[0] if ok else '-'} .. {ok[-1] if ok else '-'}")
    print(f"  NEW  n={len(nk):3d}  {nk[0] if nk else '-'} .. {nk[-1] if nk else '-'}")
    tags_present = [tg for tg in REVENUE_TAGS if tg in facts.get("us-gaap", {})]
    print(f"  revenue tags this filer uses: {[tg[:38] for tg in tags_present]}")
    print("  latest 4 quarters (NEW):")
    for k in nk[-4:]:
        print(f"     {k}  ${n[k]/1e9:,.2f}bn")
    time.sleep(0.5)
