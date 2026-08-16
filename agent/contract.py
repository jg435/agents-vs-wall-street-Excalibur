"""Layer-1 typed contract (Hackathon.md §4): one JSON per company feeding the
engine. Assembled from research/facts.json (corpus, with receipts) +
cache/consensus.json (public, fetched today). NaN/None are cleaned to null;
every gap is explicit, never silent.

Usage: python -m agent.contract   -> cache/contracts/<TICKER>.json
"""
import json
import math
from pathlib import Path

from .corpus import load_facts

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "cache"

PERIOD = {"HD": "FY2026Q2", "ADI": "FY2026Q3", "HAS": "FY2026", "DE": "FY2026Q3"}
OUTPUT = {"HD": "HD-FY2026Q2.xlsx", "ADI": "ADI-FY2026Q3.xlsx",
          "HAS": "HAS-FY2026.xlsx", "DE": "DE-FY2026Q3.xlsx"}
METRICS = {
    "HD": ["Net sales", "Adjusted diluted EPS", "Comparable sales, total company"],
    "ADI": ["Revenue", "Adjusted diluted EPS", "Adjusted gross margin"],
    "HAS": ["Net fees", "Pre-exceptional basic EPS", "Pre-exceptional operating profit"],
    "DE": ["Worldwide net sales and revenues", "Diluted EPS (GAAP)",
           "Production & Precision Ag operating profit"],
}


# Amendment 6 §2 metric schema: which fact BASES and PERIODS may feed each
# forecast metric. validate_anchor_periods() enforces this mechanically.
METRIC_SCHEMA = {
    "HD:Net sales": {"bases": {"GAAP-REPORTED"},
                     "periods": {"Q2-FY2026", "FY2026", "Q2-FY2025", "Q1-FY2026"}},
    "HD:Adjusted diluted EPS": {"bases": {"ADJUSTED"},
                                "periods": {"Q2-FY2026", "FY2026", "Q2-FY2025", "Q1-FY2026", "Q1-FY2025"}},
    "HD:Comparable sales, total company": {"bases": {"COMPARABLE-SALES"},
                                           "periods": {"FY2026", "Q1-FY2026", "Apr-FY2026"}},
    "ADI:Revenue": {"bases": {"GAAP-REPORTED"}, "periods": {"Q3-FY2026"}},
    "ADI:Adjusted diluted EPS": {"bases": {"ADJUSTED"}, "periods": {"Q3-FY2026"}},
    "ADI:Adjusted gross margin": {"bases": {"ADJUSTED"},
                                  "periods": {"Q2-FY2026", "Q3-FY2026-sequential"}},
    "DE:Worldwide net sales and revenues": {"bases": {"GAAP-REPORTED", "SEGMENT"},
                                            # Q2-FY2026 admitted deliberately: the finance
                                            # bridge uses the most recent ACTUAL quarter
                                            # (Viktor ruling, 16 Aug)
                                            "periods": {"Q3-FY2025", "FY2026", "Q2-FY2026"}},
    "DE:Diluted EPS (GAAP)": {"bases": {"GAAP", "SHARE-COUNT"},
                              "periods": {"FY2026", "H1-FY2026", "Q3-FY2025", "Q4-FY2025", "Q2-FY2026"}},
    "DE:Production & Precision Ag operating profit": {"bases": {"SEGMENT"},
                                                      "periods": {"Q3-FY2025", "FY2026"}},
    "HAS:Net fees": {"bases": {"NET-FEES"},
                     "periods": {"FY2025", "H1-FY2025", "Q1-FY2026", "Q2-FY2026",
                                 "Q3-FY2026", "Q4-FY2026", "FY2026"}},
    "HAS:Pre-exceptional basic EPS": {"bases": {"PRE-EXCEPTIONAL", "SHARE-COUNT"},
                                      "periods": {"FY2026", "H1-FY2026"}},
    "HAS:Pre-exceptional operating profit": {"bases": {"PRE-EXCEPTIONAL"},
                                             "periods": {"FY2026"}},
}


def _clean(x):
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def build():
    facts = load_facts()
    consensus = json.loads((CACHE / "consensus.json").read_text())
    out_dir = CACHE / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    for tk in PERIOD:
        contract = {
            "ticker": tk,
            "period": PERIOD[tk],
            "output_file": OUTPUT[tk],
            "metrics": METRICS[tk],
            "consensus": _clean(consensus.get(tk, {})),
            "consensus_gaps": {k: v for k, v in
                               consensus.get("no_public_consensus", {}).items()
                               if k.startswith(tk + ".")},
            "facts": {k.split(".", 1)[1]: v for k, v in facts.items()
                      if k.startswith(tk + ".")},
            "notes": [],
        }
        if tk == "DE":
            contract["notes"].append(
                "BASIS TRAP: yfinance revenue consensus (~$10.7bn) is equipment-ops "
                "net sales; the metric is WORLDWIDE net sales AND revenues "
                "(FY25 Q3 = $12.018bn incl ~$1.6bn financial services). "
                "Engine must add fin-svcs revenue or anchor on the FY25 base.")
        if tk == "ADI":
            contract["notes"].append(
                "Consensus ($3.33/$3,925m) already sits ABOVE guide mid "
                "($3.30/$3,900m): the Street has priced ADI's beat habit — "
                "tilt from consensus, don't re-add the guide gap on top.")
        (out_dir / f"{tk}.json").write_text(json.dumps(contract, indent=2))
        print(f"{tk:4s} contract: {len(contract['facts'])} facts, "
              f"consensus keys {sorted(contract['consensus'])}")


if __name__ == "__main__":
    build()
