"""Pipeline invariants. Run: ./.venv/bin/python -m tests.test_pipeline

Property assertions across the WHOLE fact set and all 4 companies — never
spot-checks. Exit 0 = safe to run/freeze.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import workbook                      # noqa: E402
from agent.contract import METRICS, OUTPUT, PERIOD  # noqa: E402
from agent.run import provisional_engine, validate  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f" — {detail}" if not cond else ""))
    if not cond:
        FAILS.append(name)


# 1. RECEIPTS SELF-VERIFY: every fact's quote appears in its cited doc
# (normalized like the extractor's verify gate; research/-derived facts are
# aggregates whose receipt is the derived file itself — existence checked)
from agent.extractor import _normalize, check_identities  # noqa: E402
facts = json.loads((REPO / "research" / "facts.json").read_text())
print(f"1. receipts ({len(facts)} facts)")
for k, f in facts.items():
    doc = REPO / f["doc"]
    if f["doc"].startswith("research/") or f["doc"] == "multiple":
        check(f"receipt {k} (derived)", (REPO / f["doc"]).exists() or f["doc"] == "multiple")
        continue
    if not doc.exists():
        check(f"receipt {k}", False, f"missing doc {f['doc']}")
        continue
    check(f"receipt {k}",
          _normalize(f["quote"][:120]) in _normalize(doc.read_text(errors="ignore")),
          "quote not found in doc")

# 1b. CROSS-FACT IDENTITIES (unit/scale errors explode these)
issues = check_identities(facts)
check("cross-fact identities", not issues, str(issues))

# 2. REQUIRED-FACTS COVERAGE: everything the engine consumes exists BY NAME
REQUIRED = [
    "HD.q2_fy25_net_sales_usdm", "HD.q2_fy25_adj_eps", "HD.q2_fy25_comp_pct",
    "HD.fy_sales_growth_guide", "HD.fy_comp_guide_mid", "HD.fy_adj_eps_growth_mid",
    "ADI.rev_guide_mid_usdm", "ADI.eps_guide_mid", "ADI.adj_gross_margin_last",
    "ADI.rev_guide_beat_median_pct",
    "DE.q3_fy25_revenues_usdm", "DE.q3_fy25_equip_net_sales_usdm",
    "DE.q3_fy25_ppa_op_profit_usdm", "DE.q3_fy25_ppa_net_sales_usdm",
    "DE.fy_net_income_guide_usdm", "DE.ppa_fy_sales_guide",
    "HAS.fy25_net_fees_gbpm", "HAS.fy25_op_profit_gbpm", "HAS.op_profit_consensus",
    "HAS.q4_net_fees_lfl", "HAS.shares_issued",
    "HAS.fy25_net_finance_charge_gbpm", "HAS.fy25_pre_exceptional_etr_pct",
]
print("2. required-fact coverage")
for k in REQUIRED:
    check(f"fact {k}", k in facts and facts[k]["value"] is not None)

# 3. ENGINE: all 12 metrics, numeric, pass validate()
print("3. engine coverage + validation")
for tk in PERIOD:
    c = json.loads((REPO / "cache" / "contracts" / f"{tk}.json").read_text())
    fc = provisional_engine(c)
    check(f"{tk} all metrics", set(fc) == set(METRICS[tk]))
    try:
        validate(tk, fc)
        check(f"{tk} validate", True)
    except ValueError as e:
        check(f"{tk} validate", False, str(e))

# 4. VALIDATOR REJECTS a planted bad value (loud gate proven live)
print("4. validator rejection")
try:
    validate("HD", {"Net sales": (999999, "planted"), "Adjusted diluted EPS": (4.7, ""),
                    "Comparable sales, total company": (1.0, "")})
    check("planted out-of-range rejected", False, "validator accepted 999999")
except ValueError:
    check("planted out-of-range rejected", True)

# 5. WORKBOOK ROUNDTRIP into a temp dir, cell-exact
print("5. workbook roundtrip")
import openpyxl  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    workbook.SUBMISSION = Path(td)
    vals = {m: 10.0 + i for i, m in enumerate(METRICS["ADI"])}
    out = workbook.fill(OUTPUT["ADI"], PERIOD["ADI"], vals)
    ws = openpyxl.load_workbook(out)["Summary"]
    found = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value in vals:
                found[cell.value] = ws.cell(row=cell.row,
                                            column=cell.column + 2).value
    check("roundtrip cells", all(found.get(m) == vals[m] for m in vals), str(found))
workbook.SUBMISSION = REPO / "submission"

# 6. STRICT JSON caches
print("6. strict-JSON caches")
for name in ["cache/consensus.json", "research/facts.json"]:
    try:
        json.loads((REPO / name).read_text(),
                   parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        check(name, True)
    except ValueError as e:
        check(name, False, str(e))

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: {FAILS}"))
sys.exit(1 if FAILS else 0)
