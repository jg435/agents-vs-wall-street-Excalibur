"""FINAL COMMAND: python -m agent.run

Pipeline: corpus facts -> consensus -> contracts -> engine -> validate ->
4 workbooks in submission/ + timestamped log in logs/.

Engine status: PROVISIONAL anchor passthrough (consensus / guidance mid /
prior-year base). Viktor's 12 recipes replace provisional_engine() only —
the plumbing on either side stays fixed. Design rule: any failure falls back
to the anchor (expected accuracy score ~1.0), NEVER a blank (scores 5.0).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import contract as contract_mod
from . import workbook
from .contract import METRICS, OUTPUT, PERIOD

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "cache"
LOGS = REPO / "logs"
LOG_LINES = []


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    LOG_LINES.append(line)
    print(line)


ALLOWED_ANCHOR_PERIODS = {
    # forecast period + anchor classes allowed to touch it (Amendment 3 rule 2,
    # enforced as a real comparison): same-period guide (incl. -sequential),
    # FY guide (phased), prior-year same-quarter base, dated share counts.
    "HD": {"Q2-FY2026", "FY2026", "Q2-FY2025"},
    "ADI": {"Q3-FY2026", "Q3-FY2026-sequential", "Q2-FY2026", "FY2026"},
    "DE": {"Q3-FY2026", "FY2026", "Q3-FY2025"},
    "HAS": {"FY2026", "FY2025", "H1-FY2025", "Q1-FY2026", "Q2-FY2026",
            "Q3-FY2026", "Q4-FY2026", "2026-07-31"},
}


def validate_anchor_periods(tk, facts, uses):
    """uses: {metric: [fact names consumed]}. Every used fact's period must be
    an allowed anchor class for this forecast; a one-off-bearing actual may
    only be used WITH a same/sequential-period guide companion (rule 3)."""
    for metric, names in uses.items():
        for n in names:
            f = facts.get(n) or {}
            per = f.get("period", "")
            if per not in ALLOWED_ANCHOR_PERIODS[tk] and per != "derived/history":
                raise ValueError(f"{tk}/{metric}: fact {n} period '{per}' not an "
                                 f"allowed anchor class {ALLOWED_ANCHOR_PERIODS[tk]}")
            if f.get("one_offs"):
                companions = [facts.get(m, {}).get("period", "") for m in names if m != n]
                if not any("sequential" in c or c.startswith(("Q", "FY2026")) for c in companions):
                    raise ValueError(f"{tk}/{metric}: {n} carries one-offs "
                                     f"{[o['name'] for o in f['one_offs']]} and may not "
                                     "anchor alone (needs a period-specific guide companion)")


def provisional_engine(c):
    """{metric: (value, note)}, plus a uses-map of fact names per metric.
    NO silent defaults on guide/base inputs (Amendment 3 rule: a missing guide
    must fail loudly, never become a guessed forecast)."""
    f, cons, tk = c["facts"], c.get("consensus", {}), c["ticker"]

    def v(key):
        val = (f.get(key) or {}).get("value")
        if val is None:
            raise ValueError(f"{tk}: required fact '{key}' missing — refusing to "
                             "guess (rerun extraction or use an explicit lower tier)")
        return val

    if tk == "HD":
        fc = {
            "Net sales": (cons.get("revenue_usdm"),
                "TIER1 consensus revenue (yfinance)"),
            "Adjusted diluted EPS": (cons.get("eps"), "TIER1 consensus EPS (yfinance)"),
            "Comparable sales, total company": (v("fy_comp_guide_mid"),
                "TIER2 guidance mid (flat to +2% -> +1.0pp) [period: FY2026, phased]"),
        }
        uses = {"Comparable sales, total company": ["fy_comp_guide_mid"]}
    elif tk == "ADI":
        gm = v("adj_gross_margin_last") + v("q3_gm_guide_seq_change_pp")
        fc = {
            "Revenue": (cons.get("revenue_usdm"),
                "TIER1 consensus (already above $3.9bn guide mid)"),
            "Adjusted diluted EPS": (cons.get("eps"),
                "TIER1 consensus (above $3.30 guide mid)"),
            "Adjusted gross margin": (round(gm, 1),
                "TIER3 derived: Q2 actual 73.0% (one-off flagged) + guided sequential "
                "-0.5pp (CFO, Q2 call) [period: Q3-FY2026-sequential]"),
        }
        uses = {"Adjusted gross margin": ["adj_gross_margin_last",
                                          "q3_gm_guide_seq_change_pp"]}
    elif tk == "DE":
        bridge = v("q3_fy25_revenues_usdm") - v("q3_fy25_equip_net_sales_usdm")
        worldwide = cons.get("revenue_usdm") + bridge if cons.get("revenue_usdm") else None
        ppa_profit = (v("q3_fy25_ppa_net_sales_usdm")
                      * (1 + v("ppa_fy_sales_guide") / 100)
                      * v("ppa_fy_margin_guide_pct") / 100)
        fc = {
            "Worldwide net sales and revenues": (round(worldwide, 0) if worldwide else None,
                f"TIER1 consensus equipment net sales (yfinance) + fin-svcs bridge "
                f"${bridge:.0f}m (FY25 Q3 worldwide minus equipment) [period: Q3-FY2026]"),
            "Diluted EPS (GAAP)": (cons.get("eps"), "TIER1 consensus EPS (yfinance)"),
            "Production & Precision Ag operating profit": (round(ppa_profit, 0),
                f"TIER3 derived: FY25 Q3 PPA sales x (1{v('ppa_fy_sales_guide'):+.1f}% FY guide) "
                f"x {v('ppa_fy_margin_guide_pct'):.0f}% FY margin guide mid "
                "[NOT Q2's 15.7% — $272m tariff-refund one-off] [period: FY2026 guide, phased]"),
        }
        uses = {
            "Worldwide net sales and revenues": ["q3_fy25_revenues_usdm",
                                                 "q3_fy25_equip_net_sales_usdm"],
            "Production & Precision Ag operating profit": [
                "q3_fy25_ppa_net_sales_usdm", "ppa_fy_sales_guide",
                "ppa_fy_margin_guide_pct"],
        }
    elif tk == "HAS":
        op = 46.0  # 'top of the £37.0-46.0m consensus range' — Viktor to ratify vs £43.5m
        # WEIGHTED build-up (H1/H2 bases; quarterly bases not disclosed):
        # FY26 = H1_25 x (1 + avg(Q1,Q2 LFL)) + H2_25 x (1 + avg(Q3,Q4 LFL)).
        # Disposal (6 countries, 16 Jun 2026) NOT quantified in corpus -> no adj.
        h1 = v("h1_fy25_net_fees_gbpm")
        h2 = v("fy25_net_fees_gbpm") - h1
        g1 = (v("q1_net_fees_lfl") + v("q2_net_fees_lfl")) / 2 / 100
        g2 = (v("q3_net_fees_lfl") + v("q4_net_fees_lfl")) / 2 / 100
        fees = h1 * (1 + g1) + h2 * (1 + g2)
        shares_m = v("shares_issued") / 1e6
        eps_pence = (op - v("fy25_net_finance_charge_gbpm")) \
            * (1 - v("fy25_pre_exceptional_etr_pct") / 100) / shares_m * 100
        fc = {
            "Net fees": (round(fees, 1),
                f"TIER3 derived: H1 £{h1:.0f}m x (1{g1:+.1%}) + H2 £{h2:.0f}m x (1{g2:+.1%}) "
                "[periods: H1-FY2025 base, Q1..Q4-FY2026 LFL; disposal unquantified in corpus -> no adj]"),
            "Pre-exceptional basic EPS": (round(eps_pence, 2),
                "TIER3 derived: (OP - FY25 finance charge) x (1 - FY25 pre-exceptional ETR) / shares"),
            "Pre-exceptional operating profit": (op,
                "TIER1/2: management 'top of the £37.0-46.0m consensus range' (co. consensus £43.5m)"),
        }
        uses = {
            "Net fees": ["h1_fy25_net_fees_gbpm", "fy25_net_fees_gbpm",
                         "q1_net_fees_lfl", "q2_net_fees_lfl",
                         "q3_net_fees_lfl", "q4_net_fees_lfl"],
            "Pre-exceptional basic EPS": ["fy25_net_finance_charge_gbpm",
                                          "fy25_pre_exceptional_etr_pct", "shares_issued"],
        }
    validate_anchor_periods(tk, f, uses)
    return fc


def validate(tk, forecasts):
    """Loud gate: numeric, present, plausible ranges. Extend per Larissa's spec."""
    RANGES = {  # (metric substring, lo, hi) — sanity bounds, not forecasts
        "HD": [("Net sales", 40000, 55000), ("EPS", 3.5, 6.0), ("Comparable", -5, 8)],
        "ADI": [("Revenue", 3300, 4600), ("EPS", 2.5, 4.2), ("gross margin", 60, 80)],
        "DE": [("net sales", 9000, 15000), ("EPS", 3.0, 7.5), ("Precision", 300, 1200)],
        "HAS": [("Net fees", 800, 1050), ("EPS", 0.5, 5.0), ("operating profit", 30, 55)],
    }
    for label, (value, note) in forecasts.items():
        if value is None or not isinstance(value, (int, float)):
            raise ValueError(f"{tk}/{label}: missing/non-numeric ({note})")
        for sub, lo, hi in RANGES[tk]:
            if sub.lower() in label.lower() and not (lo <= value <= hi):
                raise ValueError(f"{tk}/{label}: {value} outside sanity range [{lo},{hi}]")


def check_consensus_freshness():
    """Estimates were fetched during the event; warn if stale, fail if not today."""
    C = json.loads((CACHE / "consensus.json").read_text())
    fetched = datetime.fromisoformat(C["fetched_at"])
    age_h = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
    if fetched.date() != datetime.now(timezone.utc).date():
        raise ValueError(f"consensus cache is from {fetched.date()} — refetch: python -m agent.consensus")
    if age_h > 2:
        log(f"WARNING: consensus cache is {age_h:.1f}h old (markets closed today; acceptable)")


def main():
    log("EXCALIBUR run start (engine=PROVISIONAL anchors)")
    check_consensus_freshness()
    contract_mod.build()
    for tk in PERIOD:
        c = json.loads((CACHE / "contracts" / f"{tk}.json").read_text())
        forecasts = provisional_engine(c)
        missing = set(METRICS[tk]) - set(forecasts)  # all-12 seam check: an
        if missing:                                  # engine gap fails HERE, by name
            raise ValueError(f"{tk}: engine produced no forecast for {missing}")
        validate(tk, forecasts)
        for label, (value, note) in forecasts.items():
            log(f"{tk} | {label} = {value}  [{note}] PROVISIONAL")
        out = workbook.fill(OUTPUT[tk], PERIOD[tk],
                            {k: v for k, (v, _) in forecasts.items()})
        log(f"{tk} -> {out.relative_to(REPO)}")
    LOGS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (LOGS / f"run-{stamp}.log").write_text("\n".join(LOG_LINES) + "\n")
    log(f"run complete — log saved logs/run-{stamp}.log")


if __name__ == "__main__":
    main()
