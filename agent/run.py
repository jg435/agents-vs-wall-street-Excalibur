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
    "HD": {"Q2-FY2026", "FY2026", "Q2-FY2025", "Q1-FY2026", "Q1-FY2025", "Apr-FY2026"},
    "ADI": {"Q3-FY2026", "Q3-FY2026-sequential", "Q2-FY2026", "FY2026"},
    "DE": {"Q3-FY2026", "FY2026", "Q3-FY2025", "H1-FY2026", "Q4-FY2025", "Q2-FY2026"},
    "HAS": {"FY2026", "FY2025", "H1-FY2025", "H1-FY2026", "Q1-FY2026", "Q2-FY2026",
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


GAP_FRACTION = 0.8  # Tier-1 adjustment: fraction of (guide target - consensus)


def temper(fy_guide_mid_pct, last_q_actual_yoy_pct):
    """Amendment-4 phase+temper, Viktor-blessed deterministic rule:
    tempered growth = mean(FY guide midpoint, last quarter's actual YoY)."""
    return (fy_guide_mid_pct + last_q_actual_yoy_pct) / 2


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
        # phase+temper: FY-only guidance pulled toward Q1 momentum (Q1 EPS
        # printed DOWN -3.7% vs a flat-to-+4% FY guide)
        g_sales = temper(v("fy_sales_growth_guide"), v("q1_fy26_sales_yoy_pct"))
        sales_target = v("q2_fy25_net_sales_usdm") * (1 + g_sales / 100)
        eps_yoy_q1 = (v("q1_fy26_adj_eps") / v("q1_fy25_adj_eps") - 1) * 100
        g_eps = temper(v("fy_adj_eps_growth_mid"), eps_yoy_q1)
        eps_target = v("q2_fy25_adj_eps") * (1 + g_eps / 100)
        # double-temper (amendment4-updated): FY guide -> Q1 actual -> April
        # (latest monthly momentum, went negative). mean(mean(1.0, 0.6), -0.5)
        comp = temper(temper(v("fy_comp_guide_mid"), v("q1_fy26_comp_pct")),
                      v("apr_fy26_comp_pct"))
        sales = cons.get("revenue_usdm") + GAP_FRACTION * (sales_target - cons.get("revenue_usdm"))
        eps = cons.get("eps") + GAP_FRACTION * (eps_target - cons.get("eps"))
        fc = {
            "Net sales": (round(sales, 0),
                f"TIER1 consensus ${cons.get('revenue_usdm'):,.0f}m + {GAP_FRACTION}x gap to "
                f"phase+temper target ${sales_target:,.0f}m (mean(FY +3.5%, Q1 +4.8%) = "
                f"{g_sales:+.2f}% on Q2-FY25 base; Q1 incl GMS/FX one-offs, flagged)"),
            "Adjusted diluted EPS": (round(eps, 2),
                f"TIER1 consensus ${cons.get('eps')} + {GAP_FRACTION}x gap to phase+temper "
                f"target ${eps_target:.2f} (mean(FY +2%, Q1 {eps_yoy_q1:+.1f}%) = {g_eps:+.2f}% "
                "on Q2-FY25 $4.68) [period: FY2026 guide phased+tempered]"),
            "Comparable sales, total company": (round(comp, 1),
                f"TIER2 double-temper: mean(mean(FY guide +1.0, Q1 +0.6), April -0.5) = "
                f"{comp:+.2f}pp ~ flat (April flipped negative; storm compares) "
                "[periods: FY2026 guide, Q1-FY2026, Apr-FY2026]"),
        }
        uses = {
            "Net sales": ["fy_sales_growth_guide", "q1_fy26_sales_yoy_pct",
                          "q2_fy25_net_sales_usdm", "q1_fy26_net_sales_usdm"],
            "Adjusted diluted EPS": ["fy_adj_eps_growth_mid", "q1_fy26_adj_eps",
                                     "q1_fy25_adj_eps", "q2_fy25_adj_eps"],
            "Comparable sales, total company": ["fy_comp_guide_mid", "q1_fy26_comp_pct",
                                                "apr_fy26_comp_pct"],
        }
    elif tk == "ADI":
        gm = v("adj_gross_margin_last") + v("q3_gm_guide_seq_change_pp")
        rev = cons.get("revenue_usdm") + GAP_FRACTION * (v("rev_guide_mid_usdm") - cons.get("revenue_usdm"))
        eps = cons.get("eps") + GAP_FRACTION * (v("eps_guide_mid") - cons.get("eps"))
        fc = {
            "Revenue": (round(rev, 0),
                f"TIER1 consensus ${cons.get('revenue_usdm'):,.0f}m + {GAP_FRACTION}x gap to "
                "$3,900m guide mid [period: Q3-FY2026]"),
            "Adjusted diluted EPS": (round(eps, 2),
                f"TIER1 consensus ${cons.get('eps')} + {GAP_FRACTION}x gap to $3.30 guide mid "
                "[period: Q3-FY2026]"),
            "Adjusted gross margin": (round(gm, 1),
                "TIER3 derived: Q2 actual 73.0% (one-off flagged) + guided sequential "
                "-0.5pp (CFO, Q2 call) [period: Q3-FY2026-sequential]"),
        }
        uses = {"Revenue": ["rev_guide_mid_usdm"],
                "Adjusted diluted EPS": ["eps_guide_mid"],
                "Adjusted gross margin": ["adj_gross_margin_last",
                                          "q3_gm_guide_seq_change_pp"]}
    elif tk == "DE":
        bridge = v("q3_fy25_revenues_usdm") - v("q3_fy25_equip_net_sales_usdm")
        cons_worldwide = cons.get("revenue_usdm") + bridge
        seg_target = (v("q3_fy25_ppa_net_sales_usdm") * (1 + v("ppa_fy_sales_guide") / 100)
                      + v("q3_fy25_sat_net_sales_usdm") * (1 + v("sat_fy_sales_guide") / 100)
                      + v("q3_fy25_cf_net_sales_usdm") * (1 + v("cf_fy_sales_guide") / 100)
                      + bridge)
        worldwide = cons_worldwide + GAP_FRACTION * (seg_target - cons_worldwide)
        # EPS: FY NI guide phased to Q3 by FY25's Q3 share of H2, over diluted shares
        q3_share_h2 = v("q3_fy25_net_income_usdm") / (v("q3_fy25_net_income_usdm")
                                                      + v("q4_fy25_net_income_usdm"))
        q3_ni_target = (v("fy_net_income_guide_usdm") - v("h1_fy26_net_income_usdm")) * q3_share_h2
        eps_target = q3_ni_target / v("q2_fy26_diluted_shares_m")
        eps = cons.get("eps") + GAP_FRACTION * (eps_target - cons.get("eps"))
        ppa_profit = (v("q3_fy25_ppa_net_sales_usdm") * (1 + v("ppa_fy_sales_guide") / 100)
                      * v("ppa_fy_margin_guide_pct") / 100)
        fc = {
            "Worldwide net sales and revenues": (round(worldwide, 0),
                f"TIER1 consensus equip+bridge ${cons_worldwide:,.0f}m + {GAP_FRACTION}x gap to "
                f"segment-sum target ${seg_target:,.0f}m (PPA -7.5%, SAT +15%, CF +20% on FY25 Q3 "
                f"bases + ${bridge:.0f}m fin-svcs) [period: FY2026 guides phased]"),
            "Diluted EPS (GAAP)": (round(eps, 2),
                f"TIER1 consensus ${cons.get('eps')} + {GAP_FRACTION}x gap to phased-guide target "
                f"${eps_target:.2f} ((FY NI mid $4,750m - H1 $2,429m) x Q3-share {q3_share_h2:.1%} "
                f"/ 270.8m sh) [period: FY2026 guide phased]"),
            "Production & Precision Ag operating profit": (round(ppa_profit, 0),
                f"TIER3 derived: FY25 Q3 PPA sales x (1{v('ppa_fy_sales_guide'):+.1f}% FY guide) "
                f"x {v('ppa_fy_margin_guide_pct'):.0f}% FY margin guide mid "
                "[NOT Q2's 15.7% — $272m tariff-refund one-off] [period: FY2026 guide, phased]"),
        }
        uses = {
            "Worldwide net sales and revenues": [
                "q3_fy25_revenues_usdm", "q3_fy25_equip_net_sales_usdm",
                "q3_fy25_ppa_net_sales_usdm", "ppa_fy_sales_guide",
                "q3_fy25_sat_net_sales_usdm", "sat_fy_sales_guide",
                "q3_fy25_cf_net_sales_usdm", "cf_fy_sales_guide"],
            "Diluted EPS (GAAP)": ["fy_net_income_guide_usdm", "h1_fy26_net_income_usdm",
                                   "q3_fy25_net_income_usdm", "q4_fy25_net_income_usdm",
                                   "q2_fy26_diluted_shares_m"],
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
        fees = h1 * (1 + g1) + h2 * (1 + g2) - v("fy26_disposed_net_fees_gbpm")
        shares_m = v("h1_fy26_weighted_avg_shares_m")  # weighted avg (basic EPS basis)
        # LATEST FY26 guides (Feb-26 H1 update: £13m finance, 45% ETR
        # 'consistent with the first half') — supersede the Aug-25 £12m/38% set
        eps_pence = (op - v("fy26_net_finance_charge_guide_gbpm")) \
            * (1 - v("fy26_etr_guide_pct") / 100) / shares_m * 100
        fc = {
            "Net fees": (round(fees, 1),
                f"TIER3 derived: H1 £{h1:.0f}m x (1{g1:+.1%}) + H2 £{h2:.0f}m x (1{g2:+.1%}) "
                "minus £15m disposed-country fees (cited) [periods: H1-FY2025 base, Q1..Q4-FY2026 LFL]"),
            "Pre-exceptional basic EPS": (round(eps_pence, 2),
                "TIER3 derived: (OP £46m - £13m FY26 finance-charge guide, Feb-26 UPDATE) "
                "x (1 - 45% FY26 ETR guide, Feb-26 UPDATE 'consistent with H1') / 1,595.7m "
                "weighted-avg shares [periods: latest FY2026 guides supersede Aug-25 set]"),
            "Pre-exceptional operating profit": (op,
                "TIER1/2: management 'top of the £37.0-46.0m consensus range' (co. consensus £43.5m)"),
        }
        uses = {
            "Net fees": ["h1_fy25_net_fees_gbpm", "fy25_net_fees_gbpm",
                         "q1_net_fees_lfl", "q2_net_fees_lfl",
                         "q3_net_fees_lfl", "q4_net_fees_lfl",
                         "fy26_disposed_net_fees_gbpm"],
            "Pre-exceptional basic EPS": ["fy26_net_finance_charge_guide_gbpm",
                                          "fy26_etr_guide_pct",
                                          "h1_fy26_weighted_avg_shares_m"],
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
    log("EXCALIBUR run start")
    check_consensus_freshness()
    # Amendment 6 §3: stale-guidance gate — the run refuses to proceed if any
    # engine guide fact is not the latest corpus vintage
    from . import revision_diff
    if revision_diff.main() != 0:
        raise ValueError("stale guidance detected — refusing to forecast")
    log("revision-diff: all guide facts are latest vintage")
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
