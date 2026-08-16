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
        return {
            "Revenue": (cons.get("revenue_usdm"), "consensus (already above $3.9bn guide mid)"),
            "Adjusted diluted EPS": (cons.get("eps"), "consensus (above $3.30 guide mid)"),
            "Adjusted gross margin": (v("adj_gross_margin_last"),
                "Q2 FY26 actual adj GM (not guided; trailing anchor)"),
        }
    if tk == "DE":
        return {
            "Worldwide net sales and revenues": (v("q3_fy25_revenues_usdm"),
                "FY25 Q3 base $12,018m flat (consensus is equipment-ops basis — see note)"),
            "Diluted EPS (GAAP)": (cons.get("eps"), "consensus EPS (yfinance)"),
            "Production & Precision Ag operating profit": (v("q3_fy25_ppa_op_profit_usdm"),
                "FY25 Q3 PPA actual $580m flat (guide: sales down 5-10% FY)"),
        }
    if tk == "HAS":
        op = 46.0  # 'top of the £37.0-46.0m consensus range' (Jul-10 update)
        fees = v("fy25_net_fees_gbpm", 972.4) * (1 - 0.05)
        shares_m = v("shares_issued", 1_570_252_226) / 1e6
        eps_pence = (op - 5.0) * (1 - 0.28) / shares_m * 100  # rough interest/tax
        return {
            "Net fees": (round(fees, 1), "FY25 £972.4m x (1 - 5% LFL) [FX bridge pending]"),
            "Pre-exceptional basic EPS": (round(eps_pence, 1),
                "derived: (OP £46m - ~£5m interest) x (1-28% tax) / 1,570m sh"),
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


def main():
    log("EXCALIBUR run start (engine=PROVISIONAL anchors)")
    contract_mod.build()
    for tk in PERIOD:
        c = json.loads((CACHE / "contracts" / f"{tk}.json").read_text())
        forecasts = provisional_engine(c)
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
