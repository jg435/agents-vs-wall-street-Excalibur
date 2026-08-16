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


def provisional_engine(c):
    """{metric_label: (value, source_note)} — anchors only, all PROVISIONAL."""
    f, cons, tk = c["facts"], c.get("consensus", {}), c["ticker"]
    v = lambda key, d=None: (f.get(key) or {}).get("value", d)

    if tk == "HD":
        return {
            "Net sales": (cons.get("revenue_usdm"), "consensus revenue (yfinance)"),
            "Adjusted diluted EPS": (cons.get("eps"), "consensus EPS (yfinance)"),
            "Comparable sales, total company": (v("fy_comp_guide_mid"),
                "FY comp guide mid (flat to +2% -> +1.0pp), Q1-8K"),
        }
    if tk == "ADI":
        # Amendment 3 rule 1: the SEQUENTIAL guide ("~50bps decline") beats the
        # YoY trend; rule 3: Q2's 73.0% held a one-off channel-repricing benefit
        gm = (v("adj_gross_margin_last", 73.0) + v("q3_gm_guide_seq_change_pp", -0.5))
        return {
            "Revenue": (cons.get("revenue_usdm"), "consensus (already above $3.9bn guide mid)"),
            "Adjusted diluted EPS": (cons.get("eps"), "consensus (above $3.30 guide mid)"),
            "Adjusted gross margin": (round(gm, 1),
                "Q2 actual 73.0% + guided sequential -0.5pp (CFO, Q2 call) "
                "[period: Q3-FY2026-sequential]"),
        }
    if tk == "DE":
        # Amendment 3 rule 3: Q2 PPA margin 15.7% contains the $272m IEEPA
        # tariff refund one-off — anchor on the FY margin GUIDE (11-13%), and
        # DERIVE segment profit = guided sales x guided margin (profit family)
        ppa_sales_fy26q3 = v("q3_fy25_ppa_net_sales_usdm", 4503.0) * (1 + v("ppa_fy_sales_guide", -7.5) / 100)
        ppa_profit = ppa_sales_fy26q3 * v("ppa_fy_margin_guide_pct", 12.0) / 100
        return {
            "Worldwide net sales and revenues": (v("q3_fy25_revenues_usdm"),
                "FY25 Q3 base $12,018m flat (consensus is equipment-ops basis — see note)"),
            "Diluted EPS (GAAP)": (cons.get("eps"), "consensus EPS (yfinance)"),
            "Production & Precision Ag operating profit": (round(ppa_profit, 0),
                f"DERIVED: FY25 Q3 PPA sales $4,503m x (1{v('ppa_fy_sales_guide', -7.5):+.1f}% FY guide) "
                f"x {v('ppa_fy_margin_guide_pct', 12.0):.0f}% FY margin guide mid "
                "[NOT Q2's 15.7% margin — $272m tariff-refund one-off] [period: FY2026 guide]"),
        }
    if tk == "HAS":
        op = 46.0  # 'top of the £37.0-46.0m consensus range' (Jul-10 update)
        # Amendment 3 rule 2: -5% is Q4 ONLY. Build FY26 from the four
        # quarterly LFL rates (equal-weight; disposal adj pending a receipt)
        lfls = [v("q1_net_fees_lfl", -8.0), v("q2_net_fees_lfl", -10.0),
                v("q3_net_fees_lfl", -8.0), v("q4_net_fees_lfl", -5.0)]
        fy_growth = sum(lfls) / len(lfls) / 100
        fees = v("fy25_net_fees_gbpm", 972.4) * (1 + fy_growth)
        log(f"HAS note: quarterly LFL build-up {lfls} -> FY {fy_growth:+.2%}; "
            "£15m disposal adj NOT applied (no corpus receipt found)")
        shares_m = v("shares_issued", 1_570_252_226) / 1e6
        finance = v("fy25_net_finance_charge_gbpm")
        etr = v("fy25_pre_exceptional_etr_pct")
        if finance is None or etr is None:
            log("HAS WARNING: finance/tax facts missing — using FY25-guess fallback")
            finance, etr = 13.4, 35.1
        eps_pence = (op - finance) * (1 - etr / 100) / shares_m * 100
        return {
            "Net fees": (round(fees, 1),
                "FY25 £972.4m x quarterly LFL build-up (-8/-10/-8/-5 -> ~-7.75% FY) "
                "[periods: Q1..Q4-FY2026; FX + disposal bridge pending receipt]"),
            "Pre-exceptional basic EPS": (round(eps_pence, 2),
                f"derived: (OP £{op}m - £{finance}m net finance charge, FY25 actual) "
                f"x (1 - {etr}% pre-exceptional ETR, FY25 actual) / {shares_m:.0f}m shares"),
            "Pre-exceptional operating profit": (op,
                "'top of the £37.0-46.0m consensus range' — company's own words"),
        }


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
