"""Corpus reader — search + cited fact extraction from challenge/offline-data.

Every extracted fact carries its receipt: {value, doc, quote}. Facts are
cached to cache/facts.json (committed) so the 17:15 final run is deterministic.
No LLM here (Jayesh lane) — targeted regex against known filings; anything
regex can't reach is David's lane (LLM guidance specs) or manual+cited.
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "challenge" / "offline-data"
RESEARCH = REPO / "research"          # organiser scratch (gitignored)
FACTS_DIR = REPO / "cache"            # committed: facts travel with the repo

FOLDER = {"HD": "home-depot", "ADI": "analog-devices",
          "HAS": "hays", "DE": "deere"}


def docs(ticker, kind=None):
    """All corpus docs for a ticker, newest first. kind: filings /
    call-transcripts / slides / None for all."""
    base = DATA / FOLDER[ticker]
    dirs = [base / kind] if kind else [p for p in base.iterdir() if p.is_dir()]
    out = []
    for d in dirs:
        out += list(d.glob("*.md"))
    return sorted(out, key=lambda p: p.name, reverse=True)


def search(ticker, pattern, kind=None, limit=10):
    """Regex search across a ticker's docs. Returns [(doc, line)] receipts."""
    rx = re.compile(pattern, re.I)
    hits = []
    for doc in docs(ticker, kind):
        for line in doc.read_text(errors="ignore").splitlines():
            if rx.search(line):
                hits.append((doc.relative_to(REPO).as_posix(), line.strip()))
                if len(hits) >= limit:
                    return hits
    return hits


def fact(value, doc, quote, note=""):
    return {"value": value, "doc": doc, "quote": quote[:300], "note": note}


def _first_number(line, rx):
    m = re.search(rx, line)
    return float(m.group(1).replace(",", "")) if m else None


def extract_facts():
    """Targeted, cited extraction of the anchors + bases the recipes need.
    Each entry is a receipt; anything not found is simply absent (loud in log)."""
    F = {}

    # ---- ADI: Q3 guidance (the 8-K states it verbatim) + Q2 adj gross margin
    for doc, line in search("ADI", r"forecasting revenue of \$([\d.]+) billion", "filings", 1):
        F["ADI.rev_guide_mid_usdm"] = fact(_first_number(line, r"\$([\d.]+) billion") * 1000, doc, line)
    for doc, line in search("ADI", r"adjusted EPS to be \$([\d.]+)", "filings", 1):
        F["ADI.eps_guide_mid"] = fact(_first_number(line, r"adjusted EPS to be \$([\d.]+)"), doc, line)
    for doc, line in search("ADI", r"Adjusted gross margin percentage[ |]+[\d.]+", "filings", 1):
        F["ADI.adj_gross_margin_last"] = fact(
            _first_number(line, r"percentage[ |]+([\d.]+)"), doc, line,
            "Q2 FY26 actual adjusted gross margin %")

    # ---- HAS: company-published consensus + Q4 LFL + share count
    for doc, line in search("HAS", r"£3?7\.0\s*-\s*46\.0m consensus|top of the £[\d.]+", "filings", 1):
        F["HAS.op_profit_guide_note"] = fact(46.0, doc, line,
                                             "'top of the £37.0–46.0m consensus range'")
    # NB: corpus PDF->md conversion inserts spaces inside digits ("£4 3.5 m")
    for doc, line in search("HAS", r"consensus for FY26 pre ?-exceptional operating profit is £[\d\s.]+m", None, 1):
        m = re.search(r"is £([\d\s.]+)m", line)
        F["HAS.op_profit_consensus"] = fact(
            float(m.group(1).replace(" ", "")), doc, line,
            "company-compiled consensus, 10 analysts, as of 9 Jul 2026")
    for doc, line in search("HAS", r"net fees\s*down\s*5", "filings", 1):
        F["HAS.q4_net_fees_lfl"] = fact(-5.0, doc, line)
    for doc, line in search("HAS", r"issued share capital .* ([\d,]+) Ordinary", "filings", 1):
        F["HAS.shares_issued"] = fact(1600433092 - 30180866, doc, line,
                                      "issued minus treasury (Aug-3 RNS)")

    # ---- DE: FY net income guide + Q2 PPA segment actuals + FY25 Q3 bases
    for doc, line in search("DE", r"fiscal 2026 is forecasted to be in a range of \$([\d.]+) billion to \$([\d.]+)", "filings", 1):
        m = re.search(r"\$([\d.]+) billion to \$([\d.]+)", line)
        F["DE.fy_net_income_guide_usdm"] = fact((float(m.group(1)) + float(m.group(2))) / 2 * 1000, doc, line)
    for doc, line in search("DE", r"Production & Precision Ag(riculture)?.*[Dd]own 5 to 10", None, 1):
        F["DE.ppa_fy_sales_guide"] = fact(-7.5, doc, line, "FY sales down 5-10%, mid -7.5%")

    # ---- HD: FY guidance (reaffirmed) — quarterly phase is Viktor's recipe
    for doc, line in search("HD", r"[Tt]otal sales growth of approximately ([\d.]+)% to ([\d.]+)%", "filings", 1):
        m = re.search(r"([\d.]+)% to ([\d.]+)%", line)
        F["HD.fy_sales_growth_guide"] = fact((float(m.group(1)) + float(m.group(2))) / 2, doc, line)
    for doc, line in search("HD", r"[Cc]omparable sales growth of approximately flat to ([\d.]+)", "filings", 1):
        F["HD.fy_comp_guide_mid"] = fact(1.0, doc, line, "flat to +2.0% -> mid +1.0pp")
    for doc, line in search("HD", r"earnings-per-share to grow approximately flat to ([\d.]+)", "filings", 1):
        F["HD.fy_adj_eps_growth_mid"] = fact(2.0, doc, line, "flat to +4% -> mid +2%")

    # ---- HISTORICAL BASES (prior-year quarters the recipes scale from)
    # HD FY2025 Q2 actuals (Aug-2025 8-K)
    for doc, line in search("HD", r"reported sales of \$([\d.]+) billion for the second quarter of fiscal 2025", "filings", 1):
        F["HD.q2_fy25_net_sales_usdm"] = fact(_first_number(line, r"\$([\d.]+) billion") * 1000, doc, line)
        m = re.search(r"[Cc]omparable sales for the second quarter of fiscal 2025 increased ([\d.]+)%", line)
        if m:
            F["HD.q2_fy25_comp_pct"] = fact(float(m.group(1)), doc, line)
    for doc, line in search("HD", r"Adjusted diluted earnings per share for the second quarter of fiscal 2025 were \$([\d.]+)", "filings", 1):
        F["HD.q2_fy25_adj_eps"] = fact(_first_number(line, r"were \$([\d.]+)"), doc, line)
    # comp is its own search (was buried in the sales-line branch and never fired)
    for doc, line in search("HD", r"Comparable sales for the second quarter of fiscal 2025 increased ([\d.]+)%", "filings", 1):
        F["HD.q2_fy25_comp_pct"] = fact(
            _first_number(line, r"increased ([\d.]+)%"), doc, line,
            "Q2 FY25 total-company comparable sales, base for the comp recipe")

    # DE FY2025 Q3 actuals (Aug-2025 8-K): total revenues, equipment net sales
    # (fin-svcs bridge = revenues - net sales), and ALL THREE segment tables
    for doc, line in search("DE", r"net sales and revenues decreased.*to \$([\d.]+) billion, for the third", "filings", 1):
        F["DE.q3_fy25_revenues_usdm"] = fact(_first_number(line, r"to \$([\d.]+) billion") * 1000, doc, line)
        m = re.search(r"Net sales were \$([\d.]+) billion for the quarter", line)
        if m:
            F["DE.q3_fy25_equip_net_sales_usdm"] = fact(
                float(m.group(1)) * 1000, doc, line,
                "equipment-ops net sales; worldwide minus this = fin-svcs+other revenue bridge")
    de_q3 = [d for d in docs("DE", "filings") if "2025-08-15" in d.name and "q3-8k" in d.name]
    if de_q3:
        lines = de_q3[0].read_text(errors="ignore").splitlines()
        rel = de_q3[0].relative_to(REPO).as_posix()
        SEGMENTS = {"Production & Precision Ag": "ppa",
                    "Small Agriculture & Turf": "sat",
                    "Construction & Forestry": "cf"}
        for header, key in SEGMENTS.items():
            for i, ln in enumerate(lines):
                if header in ln and "Third Quarter" in ln:
                    for ln2 in lines[i:i + 12]:
                        if "Net sales" in ln2 and f"DE.q3_fy25_{key}_net_sales_usdm" not in F:
                            v = _first_number(ln2, r"\$ ?([\d,]+)")
                            if v:
                                F[f"DE.q3_fy25_{key}_net_sales_usdm"] = fact(v, rel, ln2)
                        if "Operating profit" in ln2:
                            v = _first_number(ln2, r"\$ ?([\d,]+)")
                            if v:
                                F[f"DE.q3_fy25_{key}_op_profit_usdm"] = fact(v, rel, ln2)
                            break
                    break

    # HAS FY2025 actuals (Aug-2025 results)
    for doc, line in search("HAS", r"Net fees \(1\)[ |]+([\d,]+\.\d)", "filings", 1):
        F["HAS.fy25_net_fees_gbpm"] = fact(_first_number(line, r"([\d,]+\.\d)"), doc, line)
    has_fy25 = [d for d in docs("HAS", "filings") if d.name.startswith("2025-08-21")]
    for d in has_fy25:
        for line in d.read_text(errors="ignore").splitlines():
            if re.search(r"Operating profit \(before exceptional items\)", line):
                F["HAS.fy25_op_profit_gbpm"] = fact(
                    _first_number(line, r"\|[ ]*([\d.]+)"),
                    d.relative_to(REPO).as_posix(), line,
                    "FY2025 full-year pre-exceptional operating profit")
                break
        if "HAS.fy25_op_profit_gbpm" in F:
            break

    # HAS FY25 income-statement inputs for the EPS derivation (were hardcoded
    # guesses -5m/28% — actuals are 13.4m/35.1%, a ~30% EPS difference)
    for doc, line in search("HAS", r"net finance charge for FY25 was £([\d.\s]+) million", "filings", 1):
        F["HAS.fy25_net_finance_charge_gbpm"] = fact(
            float(re.search(r"£([\d.\s]+) million", line).group(1).replace(" ", "")),
            doc, line)
    for doc, line in search("HAS", r"pre-exceptional effective tax rate \('?ETR'?\) of ([\d.\s]+)%", "filings", 1):
        F["HAS.fy25_pre_exceptional_etr_pct"] = fact(
            float(re.search(r"of ([\d.\s]+)%", line).group(1).replace(" ", "")),
            doc, line)

    # ADI guided-vs-actual revenue PAIRS (beat-prior measured, not assumed).
    # Each 8-K guides the NEXT quarter and reports the CURRENT quarter's actual
    # ("* Third quarter revenue of $X billion"), so guide from filing i pairs
    # with the actual in the next (later) filing.
    events = []  # oldest -> newest: {date, guided_usdm|None, actual_usdm|None}
    for doc in sorted(docs("ADI", "filings"), key=lambda p: p.name):
        e = {"doc": doc.relative_to(REPO).as_posix(), "date": doc.name[:10],
             "guided_usdm": None, "actual_usdm": None}
        for line in doc.read_text(errors="ignore").splitlines():
            m = re.search(r"forecasting revenue of \$([\d.\s]+) billion", line)
            if m and e["guided_usdm"] is None:
                e["guided_usdm"] = float(m.group(1).replace(" ", "")) * 1000
            m = re.search(r"(?:First|Second|Third|Fourth) quarter revenue of \$([\d.\s]+) billion", line)
            if m and e["actual_usdm"] is None:
                e["actual_usdm"] = float(m.group(1).replace(" ", "")) * 1000
        if e["guided_usdm"] or e["actual_usdm"]:
            events.append(e)
    pairs = []
    for a, b in zip(events, events[1:]):
        if a["guided_usdm"] and b["actual_usdm"]:
            pairs.append({"guided": a["guided_usdm"], "actual": b["actual_usdm"],
                          "beat_pct": round(b["actual_usdm"] / a["guided_usdm"] - 1, 4),
                          "guide_doc": a["doc"], "actual_doc": b["doc"]})
    FACTS_DIR.mkdir(exist_ok=True)
    (FACTS_DIR / "adi_guides.json").write_text(json.dumps(pairs, indent=2))
    recent = [p["beat_pct"] for p in pairs[-8:]]
    F["ADI.rev_guide_beat_median_pct"] = fact(
        round(100 * sorted(recent)[len(recent) // 2], 2) if recent else None,
        "cache/adi_guides.json",
        f"{len(pairs)} guided-vs-actual pairs; last 8 beats: {recent}",
        "median % by which ADI actual revenue beats its own guide midpoint")

    FACTS_DIR.mkdir(exist_ok=True)
    (FACTS_DIR / "facts.json").write_text(json.dumps(F, indent=2))
    return F


def load_facts():
    f = FACTS_DIR / "facts.json"
    if f.exists():
        return json.loads(f.read_text())
    legacy = RESEARCH / "facts.json"          # pre-move location fallback
    if legacy.exists():
        return json.loads(legacy.read_text())
    return extract_facts()


if __name__ == "__main__":
    F = extract_facts()
    for k, v in F.items():
        print(f"{k:32s} = {v['value']}\n    {v['doc']}\n    \"{v['quote'][:110]}\"")
    print(f"\n{len(F)} facts extracted with receipts -> cache/facts.json")
