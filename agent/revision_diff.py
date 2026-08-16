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
}


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
    stale = []
    for fact_name, (company, pattern, transform) in GUIDE_PATTERNS.items():
        series = vintage_series(company, pattern, transform)
        if not series:
            print(f"{fact_name}: no vintages found (pattern miss) — SKIP")
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
