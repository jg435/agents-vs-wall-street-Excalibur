"""Guidance revision-diff (Amendment 6 §3): the mechanical stale-guidance catch.

For each guided metric, sweep EVERY corpus doc for that guide's statement,
build the (date, value) vintage series, and:
  1. flag "GUIDANCE REVISED: old -> new" whenever consecutive vintages differ;
  2. verify the fact the engine uses equals the LATEST vintage (hard fail if
     stale — this is the check that would have caught ETR 38% -> 45%);
  3. stamp is_latest / revised_since_prior on the fact.

Run: python -m agent.revision_diff        (exit 1 if any engine fact is stale)
"""
import json
import re
import sys

from .corpus import FACTS_DIR, docs

# fact name -> (company, regex over doc text, value transform)
GUIDE_PATTERNS = {
    "HAS.fy26_net_finance_charge_guide_gbpm": (
        "HAS", r"net finance charge for FY26 to be c\.?£([\d.\s]+) ?million",
        lambda m: float(m.group(1).replace(" ", ""))),
    "HAS.fy26_etr_guide_pct": (
        "HAS", r"ETR in FY26 to be c\.?([\d.\s]+)%",
        lambda m: float(m.group(1).replace(" ", ""))),
    "DE.fy_net_income_guide_usdm": (
        "DE", r"for fiscal 2026 is (?:now )?forecast(?:ed)? to be in a range of \$([\d.]+) billion to \$([\d.]+)",
        lambda m: (float(m.group(1)) + float(m.group(2))) / 2 * 1000),
    "DE.ppa_fy_margin_guide_pct": (
        "DE", r"segment(?:'s)? operating margin[\s\S]{0,60}?(?:remains |forecasted )?between ([\d.]+)%[\s\S]{0,5}?(?:and |-)([\d.]+)%",
        lambda m: (float(m.group(1)) + float(m.group(2))) / 2),
    "HD.fy_sales_growth_guide": (
        "HD", r"[Tt]otal sales growth of approximately ([\d.]+)% to ([\d.]+)%",
        lambda m: (float(m.group(1)) + float(m.group(2))) / 2),
    "ADI.rev_guide_mid_usdm": (
        "ADI", r"forecasting revenue of \$([\d.]+) billion",
        lambda m: float(m.group(1)) * 1000),
    "ADI.eps_guide_mid": (
        "ADI", r"adjusted EPS to be \$([\d.]+)",
        lambda m: float(m.group(1))),
    "ADI.q3_gm_guide_seq_change_pp": (
        "ADI", r"([\d]+) basis points decline in gross margin",
        lambda m: -float(m.group(1)) / 100),
    "HD.fy_comp_guide_mid": (
        "HD", r"[Cc]omparable sales growth of approximately flat to ([\d.]+)",
        lambda m: float(m.group(1)) / 2),
    "HD.fy_adj_eps_growth_mid": (
        "HD", r"[Aa]djusted[^.]{0,40}earnings-per-share to grow approximately flat to ([\d.]+)",
        lambda m: float(m.group(1)) / 2),
    "DE.ppa_fy_sales_guide": (
        "DE", r"(?:Production and [Pp]recision [Aa]g|Production & Precision Ag)[\s\S]{0,120}?down (?:between )?([\d.]+)%?\s*(?:-|to|%-)\s*([\d.]+)%",
        lambda m: -(float(m.group(1)) + float(m.group(2))) / 2),
    "DE.sat_fy_sales_guide": (
        "DE", r"(?:[Ss]mall [Aa]g[\s\S]{0,120}?net sales to be up|net sales to be up) approximately ([\d.]+)% for the full year",
        lambda m: float(m.group(1))),
    "DE.cf_fy_sales_guide": (
        "DE", r"Construction & Forestry[^|\n]{0,40}\|[^|\n]{0,10}\| Up ~([\d.]+)%",
        lambda m: float(m.group(1))),
    "HAS.op_profit_guide_gbpm": (
        "HAS", r"top of the £[\d\s.]+-\s*([\d\s.]+)m consensus range",
        lambda m: float(m.group(1).replace(" ", ""))),
    "HAS.op_profit_consensus": (
        "HAS", r"consensus for FY26 pre ?-exceptional operating profit is £([\d\s.]+)m",
        lambda m: float(m.group(1).replace(" ", ""))),
}

# Amendment 6 §4: EVERY guide-class fact must be registered here. A guide fact
# without a diff pattern is a hard failure, not a skip.
def unregistered_guides(F):
    return [k for k, f in F.items()
            if "guide" in k.lower() and not k.endswith("_note")
            and not f.get("doc", "").startswith(("cache/", "research/"))  # derived stats aren't guidance
            and k not in GUIDE_PATTERNS]


def vintage_series(company, pattern, transform):
    """[(doc_date, value, doc)] oldest -> newest, one per doc."""
    rx = re.compile(pattern)
    out = []
    for doc in sorted(docs(company), key=lambda d: d.name):
        m = rx.search(doc.read_text(errors="ignore"))
        if m:
            out.append((doc.name[:10], transform(m),
                        doc.relative_to(doc.parents[3]).as_posix()))
    return out


def main():
    F = json.loads((FACTS_DIR / "facts.json").read_text())
    missing = unregistered_guides(F)
    if missing:
        print(f"FAIL: guide facts with NO revision-diff pattern: {missing}")
        return 1
    stale = []
    for fact_name, (company, pattern, transform) in GUIDE_PATTERNS.items():
        series = vintage_series(company, pattern, transform)
        if not series:
            print(f"FAIL {fact_name}: pattern found NO vintages — cannot verify freshness")
            stale.append(fact_name)
            continue
        revisions = [(a, b) for a, b in zip(series, series[1:]) if a[1] != b[1]]
        latest = series[-1]
        for (d1, v1, _), (d2, v2, _) in revisions:
            print(f"GUIDANCE REVISED {fact_name}: {v1} ({d1}) -> {v2} ({d2})")
        fact = F.get(fact_name)
        if fact is None:
            print(f"{fact_name}: not in facts store — SKIP")
            continue
        uses_latest = abs(fact["value"] - latest[1]) < 0.005 * max(1, abs(latest[1]))
        fact["is_latest"] = uses_latest
        fact["revised_since_prior"] = bool(revisions)
        if revisions:
            fact["revision_trace"] = [f"{v} @ {d}" for d, v, _ in series]
        status = "LATEST" if uses_latest else f"STALE (engine {fact['value']} vs latest {latest[1]} @ {latest[0]})"
        print(f"{fact_name}: {len(series)} vintages, {len(revisions)} revisions -> {status}")
        if not uses_latest:
            stale.append(fact_name)
    (FACTS_DIR / "facts.json").write_text(json.dumps(F, indent=2))
    if stale:
        print(f"\nFAIL: engine uses STALE guidance for {stale}")
        return 1
    print("\nall engine guide facts are the latest vintage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
