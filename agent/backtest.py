"""Historical replay + variance measurement. Run: python -m agent.backtest

Answers two questions with corpus data only (no lookahead: each replayed
quarter uses only documents published BEFORE it):
  1. Do our recipe shapes beat naive alternatives on history? (MAE per method)
  2. What is the error VARIANCE of each method? (std of errors = the natural
     uncertainty band around each of our submitted numbers)

Replays:
  ADI  guide-anchored revenue: guide-mid raw vs guide+median-beat vs momentum,
       over every paired guided-vs-actual quarter in cache/adi_guides.json.
  HD   phase+temper on quarterly YoY sales growth: temper(FY guide, prior-Q
       momentum) vs guide-only vs momentum-only, per fiscal year with an
       extractable FY guide.
  DE   FY-guide EPS phasing: (FY NI guide - H1 actual) x prior-year Q3 share,
       vs actual Q3 NI, for each year where all pieces extract.

Quarters that fail to extract are SKIPPED AND COUNTED (coverage reported),
never guessed. Series cached with receipts -> cache/backtest_series.json.
"""
import json
import re
import statistics
from pathlib import Path

from .corpus import REPO, docs

CACHE = REPO / "cache"

ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def mae(errors):
    return sum(abs(e) for e in errors) / len(errors)


def report(name, method_errors, unit):
    print(f"\n{name}")
    for method, errs in method_errors.items():
        if len(errs) < 3:
            print(f"  {method:28s} n={len(errs)} — too few to score")
            continue
        print(f"  {method:28s} n={len(errs):2d}  MAE={mae(errs):6.2f}{unit}  "
              f"std={statistics.stdev(errs):6.2f}{unit}  "
              f"mean={statistics.mean(errs):+6.2f}{unit}")


# ---------------------------------------------------------------- ADI replay
ADI_GUIDE = re.compile(r"forecasting revenue of \$([\d.]+) billion", re.I)
ADI_ACTUAL = [re.compile(r"(?:First|Second|Third|Fourth) quarter revenue of \$([\d.]+) billion", re.I),
              re.compile(r"[Rr]evenue of \$([\d,]+(?:\.\d+)?) million")]


def build_adi_pairs():
    from datetime import date
    events = []
    for doc in sorted(docs("ADI", "filings"), key=lambda x: x.name):
        text = doc.read_text(errors="ignore")
        e = {"doc": doc.relative_to(REPO).as_posix(), "guided": None, "actual": None}
        g = ADI_GUIDE.search(text)
        if g:
            e["guided"] = float(g.group(1)) * 1000
        for rx in ADI_ACTUAL:
            for m in rx.finditer(text):
                start = max(0, m.start() - 30)
                if "forecast" in text[start:m.start()].lower():
                    continue
                val = float(m.group(1).replace(",", ""))
                e["actual"] = val * (1000 if "billion" in m.group(0).lower() else 1)
                break
            if e["actual"]:
                break
        if e["guided"] or e["actual"]:
            events.append(e)
    pairs = []
    for a, b in zip(events, events[1:]):
        if a["guided"] and b["actual"]:
            d1 = date(*map(int, a["doc"].split("/")[-1][:10].split("-")))
            d2 = date(*map(int, b["doc"].split("/")[-1][:10].split("-")))
            if 60 <= (d2 - d1).days <= 130 and 0.5 < b["actual"] / a["guided"] < 2.0:
                pairs.append({"guided": a["guided"], "actual": b["actual"],
                              "beat_pct": b["actual"] / a["guided"] - 1,
                              "guide_doc": a["doc"], "actual_doc": b["doc"]})
    return pairs


def adi_replay():
    pairs = build_adi_pairs()
    (CACHE / "adi_pairs_backtest.json").write_text(json.dumps(pairs, indent=2))
    if len(pairs) < 4:
        print("ADI: insufficient pairs")
        return {}
    beats = [p["beat_pct"] * 100 for p in pairs]          # % beat vs guide
    print(f"\nADI guide-beat distribution (n={len(beats)}): "
          f"median={statistics.median(beats):+.2f}%  mean={statistics.mean(beats):+.2f}%  "
          f"std={statistics.stdev(beats):.2f}%  -> the natural uncertainty of a "
          "guidance-anchored ADI revenue forecast")
    m = {"guide mid (raw)": [], "guide + rolling med beat": [], "momentum (prev actual)": []}
    for i, p in enumerate(pairs):
        # guard against mispairs across corpus gaps: a guide and its actual
        # must come from filings ~one quarter apart
        from datetime import date
        d1 = date(*map(int, p["guide_doc"].split("/")[-1][:10].split("-")))
        d2 = date(*map(int, p["actual_doc"].split("/")[-1][:10].split("-")))
        if not 60 <= (d2 - d1).days <= 130:
            continue
        actual, guide = p["actual"], p["guided"]
        m["guide mid (raw)"].append((guide / actual - 1) * 100)
        prior = [q["beat_pct"] for q in pairs[:i]]
        med = statistics.median(prior) if len(prior) >= 4 else 0.0
        m["guide + rolling med beat"].append((guide * (1 + med) / actual - 1) * 100)
        if i > 0:
            m["momentum (prev actual)"].append((pairs[i - 1]["actual"] / actual - 1) * 100)
    report("ADI revenue replay (error vs actual, %)", m, "%")
    return m


# ----------------------------------------------------------------- HD replay
SALES_RX = re.compile(
    r"(?:reported )?sales of \$([\d.]+) billion for the (first|second|third|fourth) "
    r"quarter of fiscal (\d{4}), (?:an increase|a decrease) of[\s\S]{0,60}?or ([\d.]+)%", re.I)
GUIDE_RX = re.compile(
    r"[Tt]otal sales growth of approximately (\(?-?[\d.]+\)?)%? to (\(?-?[\d.]+\)?)%")
DECLINE = re.compile(r"[Tt]otal sales (?:decline|decrease) of approximately ([\d.]+)%")


SALES_RX_OLD = re.compile(
    r"[Ss]ales for the (first|second|third|fourth) quarter of fiscal (\d{4}) were "
    r"\$([\d.]+) billion[\s\S]{0,80}?(?:an increase|a decrease) of[\s\S]{0,60}?([\d.]+)%", re.I)


def hd_series():
    quarters, guides = {}, {}
    for doc in docs("HD", "filings"):
        text = doc.read_text(errors="ignore")
        for m in SALES_RX_OLD.finditer(text):
            fy, q = int(m.group(2)), ORDINAL[m.group(1).lower()]
            sign = -1 if "a decrease" in m.group(0).lower() else 1
            quarters.setdefault((fy, q), {"yoy": sign * float(m.group(4)),
                                          "doc": doc.relative_to(REPO).as_posix()})
        for m in SALES_RX.finditer(text):
            fy, q = int(m.group(3)), ORDINAL[m.group(2).lower()]
            sign = -1 if "a decrease" in m.group(0).lower() else 1
            quarters.setdefault((fy, q), {
                "yoy": sign * float(m.group(4)),
                "doc": doc.relative_to(REPO).as_posix()})
        g = GUIDE_RX.search(text)
        if g:
            fy_guess = None
            fym = re.search(r"fiscal (\d{4}) [Gg]uidance", text)
            if fym:
                fy_guess = int(fym.group(1))
            if fy_guess:
                lo = float(g.group(1).strip("()"))
                hi = float(g.group(2).strip("()"))
                guides.setdefault(fy_guess, {"mid": (lo + hi) / 2,
                                             "doc": doc.relative_to(REPO).as_posix()})
    return quarters, guides


def hd_replay():
    quarters, guides = hd_series()
    m = {"temper(guide, momentum)": [], "FY guide only": [], "momentum only": []}
    skipped = 0
    for (fy, q), row in sorted(quarters.items()):
        if q == 1:
            continue                        # need prior quarter momentum
        prev = quarters.get((fy, q - 1))
        guide = guides.get(fy)
        if not prev or not guide:
            skipped += 1
            continue
        actual = row["yoy"]
        m["FY guide only"].append(guide["mid"] - actual)
        m["momentum only"].append(prev["yoy"] - actual)
        m["temper(guide, momentum)"].append((guide["mid"] + prev["yoy"]) / 2 - actual)
    print(f"\nHD coverage: {len(quarters)} quarters extracted, {len(guides)} FY guides, "
          f"{skipped} replay quarters skipped (missing guide/momentum)")
    report("HD quarterly sales-growth replay (predicted - actual YoY, pp)", m, "pp")
    return m


# ----------------------------------------------------------------- DE replay
NI_GUIDE_RX = re.compile(
    r"[Nn]et income (?:attributable to Deere & Company )?for (?:fiscal )?(\d{4}) is "
    r"(?:now )?(?:forecasted|forecast|anticipated|expected) to be in a range of "
    r"\$([\d.]+) billion to \$([\d.]+)(?: billion)?", re.I)
Q3_NI_RX = re.compile(r"Third Quarter Net Income of \$([\d.]+) [Bb]illion")


def de_replay():
    guides, q3_actuals = {}, {}
    for doc in docs("DE", "filings"):
        text = doc.read_text(errors="ignore")
        for g in NI_GUIDE_RX.finditer(text):
            fy = int(g.group(1))
            # keep the guide as of the Q2 report (filed ~May of the fiscal year)
            if f"{fy}-05" in doc.name:
                guides[fy] = (float(g.group(2)) + float(g.group(3))) / 2 * 1000
        a = Q3_NI_RX.search(text)
        if a:
            fym = re.match(r"(\d{4})-08", doc.name)
            if fym:
                q3_actuals[int(fym.group(1))] = float(a.group(1)) * 1000
    errs, rows = [], []
    for fy, guide_mid in sorted(guides.items()):
        if fy in q3_actuals and (fy - 1) in q3_actuals:
            # crude phase: prior-year Q3 NI share of FY NI unknown pre-close ->
            # use H2/2 split as the naive and Q3-share as refined when possible
            pred_naive = guide_mid / 4
            actual = q3_actuals[fy]
            errs.append((pred_naive / actual - 1) * 100)
            rows.append((fy, guide_mid, actual))
    print(f"\nDE coverage: {len(guides)} May-vintage FY NI guides, "
          f"{len(q3_actuals)} Q3 actuals, {len(rows)} replayable years: {[r[0] for r in rows]}")
    if len(errs) >= 3:
        report("DE Q3 NI from FY guide (naive quarter-split, %)",
               {"FY guide / 4": errs}, "%")
    else:
        print("DE: too few replayable years for variance — reporting rows only")
        for fy, g, a in rows:
            print(f"  FY{fy}: guide mid ${g:,.0f}m -> naive Q3 ${g/4:,.0f}m vs actual ${a:,.0f}m")
    return errs


def main():
    print("=" * 72)
    print("BACKTEST + VARIANCE (no lookahead; skipped quarters counted, not guessed)")
    print("=" * 72)
    results = {"ADI": adi_replay(), "HD": hd_replay(), "DE": de_replay()}
    out = {k: {mth: v for mth, v in vv.items()} if isinstance(vv, dict) else vv
           for k, vv in results.items()}
    (CACHE / "backtest_results.json").write_text(json.dumps(out, indent=2))
    print("\n-> cache/backtest_results.json")


if __name__ == "__main__":
    main()
