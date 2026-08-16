"""Build the guidance history — drop in as excalibur/guidance_history.py

Runs the guidance extractor over the cached 8-K exhibits and emits, per ticker:

  cache/raw/<T>/guidance_history.json   [{"period_end","guided_midpoint",...}]
       -> feeds revenue_prior.guide_beat_series()  (Row 1, feed B)

  cache/raw/<T>/guidance_current.json   the guidance for the NEXT, unreported
       quarter -> feeds Row 2, the revenue ledger's workhorse row

THE MAPPING THAT MATTERS. An 8-K filed 2026-05-20 REPORTS the quarter that
just ended (2026-04-26) and GUIDES the next one (~2026-07-26). So a filing's
guidance belongs to the quarter AFTER the one it reports. We resolve that from
the actuals calendar rather than by date arithmetic:

    reported quarter = latest actual period_end strictly before the filing date
    guided quarter   = the next period_end after that (~+91 days)

If the guided quarter has an actual, it becomes a guide_beat observation.
If it has not reported yet, it is the LIVE guidance -> guidance_current.json.

MODES
  python -m excalibur.guidance_history --inspect
      No API key. Regex-locates candidate guidance sentences in each filing,
      prints the filing -> guided-quarter mapping and the coverage you would
      get. Use this to eyeball what is there, or to hand-enter (the plan
      sanctions manual entry: "10 numbers by hand is a fine hackathon fallback").

  python -m excalibur.guidance_history
      LLM extraction (OPENAI_API_KEY or ANTHROPIC_API_KEY), cached per filing
      date under cache/llm/ so re-runs are free.

  cache/manual_guidance.json  {"NVDA": {"2026-07-26": 91.0e9}, ...}
      Hand-entered midpoints in DOLLARS. Merged last, wins over the LLM.

COVERAGE WARNING. fetch_text.fetch_8k_press_releases defaults to n=3 filings
per name. Three filings yield at most TWO usable guide_beat observations (the
newest filing's guided quarter has not reported yet). revenue_prior requires
>=4 for a firm feed and >=8 for the sector median, so feed B WILL NOT ACTIVATE
on a 3-filing cache. Re-run the text fetch with n=12 first:
    python -m excalibur.fetch_text        # after raising n to 12
"""
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from .llm import call_json, filing_narrative
from .revenue_prior import (GuidanceSpec, revenue_actuals, to_quarterly_dollars,
                            GUIDANCE_EXTRACT_SYSTEM)
from .universe import forecast_tickers

CACHE = Path(__file__).resolve().parent.parent / "cache"
RAW = CACHE / "raw"
LLM_CACHE = CACHE / "llm"
MANUAL = CACHE / "manual_guidance.json"

MIN_FIRM_OBS = 4      # revenue_prior.guide_beat_series threshold
MIN_SECTOR_OBS = 8    # revenue_prior.sector_feed_median threshold

# Sentences that plausibly carry revenue guidance — used by --inspect only.
CANDIDATE = re.compile(
    r"[^.\n]{0,200}?\b(?:expect|guid\w*|outlook|anticipat\w*|forecast|plan)\b"
    r"[^.\n]{0,240}?\b(?:revenue|net sales|comparable sales|comp sales|ARR|"
    r"annual recurring revenue)\b[^.\n]{0,240}", re.I)
CANDIDATE_REV = re.compile(
    r"[^.\n]{0,200}?\b(?:revenue|net sales|comparable sales|comp sales)\b"
    r"[^.\n]{0,240}?\b(?:expect|guid\w*|outlook|anticipat\w*)\b[^.\n]{0,240}", re.I)


def _d(s):
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def filings_by_date(ticker):
    """{filing_date: [paths]} — exhibits filed the same day belong together
    (NVDA files the press release AND the CFO commentary; guidance lives in
    the latter)."""
    out = defaultdict(list)
    for f in sorted((RAW / ticker / "filings").glob("8K_*.txt")):
        parts = f.name.split("_")
        if len(parts) >= 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]):
            out[parts[1]].append(f)
    return dict(sorted(out.items()))


def guided_quarter(actuals, filing_date, tol_days=45):
    """(reported_end, guided_end). guided_end may be beyond the actuals series
    — that means the guided quarter has not reported yet."""
    prior = [k for k in actuals if k < filing_date]
    if not prior:
        return None, None
    reported = max(prior)
    # a filing reports a quarter that ended within ~60 days
    if (_d(filing_date).toordinal() - _d(reported).toordinal()) > 75:
        return None, None
    later = [k for k in actuals if k > reported]
    if later:
        target = _d(reported).toordinal() + 91
        nxt = min(later, key=lambda k: abs(_d(k).toordinal() - target))
        if abs(_d(nxt).toordinal() - target) <= tol_days:
            return reported, nxt
    # not yet reported: synthesise the expected end date for the live guide
    return reported, date.fromordinal(_d(reported).toordinal() + 91).isoformat()


def bundle_text(paths, max_chars=14000):
    parts = []
    for p in paths:
        parts.append(f"=== {p.name} ===\n"
                     f"{filing_narrative(p.read_text(encoding='utf-8', errors='ignore'), 7000)}")
    return "\n\n".join(parts)[:max_chars]


def extract_spec(ticker, filing_date, paths, use_cache=True):
    """LLM -> GuidanceSpec, cached per (ticker, filing_date)."""
    LLM_CACHE.mkdir(parents=True, exist_ok=True)
    out = LLM_CACHE / f"{ticker}_guidance_{filing_date}.json"
    if use_cache and out.exists():
        raw = json.loads(out.read_text())
    else:
        raw = call_json(GUIDANCE_EXTRACT_SYSTEM,
                        f"TICKER: {ticker}\nFILED: {filing_date}\n\n"
                        f"{bundle_text(paths)}")
        out.write_text(json.dumps(raw, indent=2))
    if not raw or raw.get("kind") in (None, "NONE"):
        return None, raw.get("quote", "") if raw else ""
    return GuidanceSpec(kind=raw["kind"], period=raw.get("period") or "QUARTER",
                        low=raw.get("low"), high=raw.get("high"),
                        basis=raw.get("basis", "reported"),
                        source=f"8-K {filing_date}"), raw.get("quote", "")


def build(ticker, use_cache=True, comp_spread=None):
    actuals = revenue_actuals(ticker)
    if not actuals:
        return [], None, ["no revenue actuals — run fetch_gaap (fixed) first"]
    manual = json.loads(MANUAL.read_text()).get(ticker, {}) if MANUAL.exists() else {}

    history, current, notes = [], None, []
    for fdate, paths in filings_by_date(ticker).items():
        reported, guided = guided_quarter(actuals, fdate)
        if not guided:
            notes.append(f"{fdate}: could not map to a guided quarter")
            continue
        try:
            spec, quote = extract_spec(ticker, fdate, paths, use_cache)
        except Exception as e:
            notes.append(f"{fdate}: extract failed ({str(e)[:60]})")
            continue
        mid, how = to_quarterly_dollars(spec, ticker, guided, comp_spread)
        if guided in manual:                      # hand-entry wins
            mid, how = float(manual[guided]), "MANUAL entry"
        if mid is None:
            notes.append(f"{fdate}: guidance not convertible ({how})")
            continue
        rec = {"period_end": guided, "guided_midpoint": mid,
               "kind": spec.kind if spec else "MANUAL",
               "filed": fdate, "how": how, "quote": (quote or "")[:200]}
        if guided in actuals:
            rec["actual"] = actuals[guided]
            rec["guide_beat"] = actuals[guided] / mid - 1
            history.append(rec)
        else:
            current = rec                          # the live guide -> Row 2
    return history, current, notes


def inspect(ticker):
    """No API key: show the mapping and what a human/LLM would have to read."""
    actuals = revenue_actuals(ticker)
    fb = filings_by_date(ticker)
    print(f"\n{'='*74}\n{ticker}   actuals {min(actuals) if actuals else '-'} .. "
          f"{max(actuals) if actuals else '-'}   filings cached: {len(fb)}\n{'='*74}")
    usable = 0
    for fdate, paths in fb.items():
        reported, guided = guided_quarter(actuals, fdate)
        if not guided:
            print(f"  {fdate}  -> UNMAPPED"); continue
        has = guided in actuals
        usable += has
        print(f"  filed {fdate}  reports {reported}  guides {guided}  "
              f"{'ACTUAL KNOWN -> usable' if has else 'not yet reported -> LIVE Row 2'}")
        for p in paths:
            txt = filing_narrative(p.read_text(encoding="utf-8", errors="ignore"), 9000)
            hits = [" ".join(m.group(0).split())
                    for m in list(CANDIDATE.finditer(txt)) + list(CANDIDATE_REV.finditer(txt))]
            hits = [h for h in hits if re.search(r"\d", h)][:2]
            for h in hits:
                print(f"        [{p.name[:34]}] {h[:180]}")
    print(f"  -> {usable} usable guide_beat observation(s); "
          f"need {MIN_FIRM_OBS} for a firm feed")
    return usable


def main():
    tickers = [a for a in sys.argv[1:] if not a.startswith("-")] or forecast_tickers()
    if "--inspect" in sys.argv:
        counts = {t: inspect(t) for t in tickers}
        print(f"\n{'='*74}\nCOVERAGE\n{'='*74}")
        for t, c in counts.items():
            print(f"  {t:5s} {c} usable  {'OK' if c >= MIN_FIRM_OBS else '** SHORT **'}")
        short = [t for t, c in counts.items() if c < MIN_FIRM_OBS]
        if short:
            print(f"\n{len(short)} name(s) below the {MIN_FIRM_OBS}-observation "
                  f"threshold: {', '.join(short)}")
            print("Raise fetch_text.fetch_8k_press_releases(n=3) to n=12 and "
                  "re-run the text fetch, or hand-enter into "
                  "cache/manual_guidance.json.")
        return

    total = 0
    for t in tickers:
        hist, cur, notes = build(t)
        (RAW / t / "guidance_history.json").write_text(json.dumps(hist, indent=2))
        if cur:
            (RAW / t / "guidance_current.json").write_text(json.dumps(cur, indent=2))
        total += len(hist)
        beats = [f"{h['guide_beat']:+.1%}" for h in hist]
        print(f"{t:5s} {len(hist)} obs {beats}  live={'yes' if cur else 'NO'}"
              + (f"  ({len(notes)} notes)" if notes else ""))
        for n in notes:
            print(f"        - {n}")
    print(f"\n{total} guide_beat observations across {len(tickers)} names.")
    if total < MIN_FIRM_OBS * len(tickers):
        print("Feed B will not activate everywhere — see the coverage warning "
              "in this module's docstring.")


if __name__ == "__main__":
    main()
