# CLAUDE WORK — HANDOFF
# Written Sat 15 Aug 2026 (night before the hackathon, Sun 16 Aug, London).
# Upload this to a new chat to restore full context.

Everything in this folder was produced by Claude Code in one session on
2026-08-15. Nothing outside this folder was modified. Viktor's existing
Research files and the GitHub repo were read only.

===============================================================================
0. WHAT WAS ASKED / WHAT WAS DONE
===============================================================================
Viktor asked for (a) familiarisation with ~/Research (FinRobot, earnings_agent,
hackathon_filings, all .md files, the EXCALIBUR Research Brief PDF), then
(b) a review of the live build at https://github.com/jg435/Excalibur, then
(c) a design for the REVENUE forecasting path, which was the open gap.

The EPS findings (section 1) were reported and Viktor confirmed he resolved
them. They are kept here as reproducible evidence, not as open items.
The revenue work (sections 2-4) is the live deliverable.

Viktor then asked for the guidance-history builder and the fetch_gaap fix
(explicitly deferring the HD/LOW/MRVL guidance-shape question). Both are done
and TESTED AGAINST LIVE DATA — see sections 4 and 4b. One new blocker surfaced
while testing: the filing cache is too thin for the guide-beat feed to
activate. See section 6F — it is the single thing to fix first.

===============================================================================
1. EPS FINDINGS — REPORTED, VIKTOR SAYS RESOLVED (kept for the record)
===============================================================================
The repo was cloned to a scratch dir and the backtest RUN. It reproduces
exactly: 28/40 firm-quarters, |err| 2.6336 vs Street 3.6800.

Findings raised (all reproducible via eps_diagnostics/):
 1. auditor.audit() is never called by anything; app.py calls apply_hooks()
    directly. analyst_range is never populated and no analyst low/high is
    fetched anywhere -> the SOFT-CLAMP path (the designated honest trigger for
    the on-stage auditor moment) was unreachable dead code.
 2. params.py had LAM=0.6 / REFERENCE_STD=0.05, so the demo ran lambda=0.6,
    not the lambda=0.8 the docs said was locked.
 3. The headline "28/40, -28%" is the lambda=0.6 run. At the shipped
    lambda=0.8 + empirical ref 0.0473 it is 31/40, 2.5239 vs 3.6800 (-31.4%).
    NEXT_STEPS had merged two different runs into one sentence.
 4. Backtest caveat was wrong about live rows. Rows 2, 4 and 5 are IDENTICALLY
    ZERO in replay (guidance_midpoint=None, shares_trend={},
    qualitative_signal=0.0). Row 3 damp DOES fire, in 4/40 quarters, via the
    monster-beat branch. Correct wording: "Row 1 alone, plus the
    mean-reversion damp in 4 of 40 quarters."
 5. Reading-B interval fix was never applied — interval_from_surprises still
    took consensus, so HD, TJX and MRVL forecasts sat OUTSIDE their own
    published intervals.
 6. lambda=0.8 is a CORNER of the specified {0.4..0.8} grid, not an interior
    optimum. Extended sweep: 0.9 -> 2.4715, 1.0 -> 2.4669, 1.2 -> 2.5984.
    Argmin is ~1.0 (i.e. drop the sector term), but 0.8 vs 1.0 differ by 2% of
    total error with an identical 31/40 win count — the sample cannot separate
    them. Recommendation was KEEP 0.8 on shrinkage discipline and say why.
 7. Row 4 miscalibrated: steady_repurchaser fires on "shares fell in >= half of
    periods" then credits a flat +1.00%. Real per-period drift: ADI -0.46%,
    INTU -0.43%, TJX -0.24%, NVDA -0.17%, WMT -0.08%, MRVL +0.38% (share count
    RISING, still flagged). Six of ten credited +1.00%, i.e. 2-6x the true
    effect. Row 4 is inert in the backtest so the -31% claim never tested it.
 8. Reliability floor (0.25) binds in 0/40 quarters. Range 0.26-0.83, median
    0.56. That is Larissa's D.4 answer.
 9. fetch_gaap.quarterly_series returns the FIRST revenue tag with any data
    instead of merging across tags -> NVDA's revenue history is 2017-2020 and
    TJX's is 2013-2015. This also silently breaks the auditor's
    margin-vs-history check on those two names. STILL RELEVANT TO REVENUE —
    see section 4.

Hostile-judge question, pre-answered ("isn't this just a flat uplift?"):
on the same 40 firm-quarters the ledger at lambda=0.8 scores |err| 2.5239 vs
best flat uplift +2% at 2.7216, +4% at 2.8744, +7% at 3.9426. The ledger beats
every flat uplift. BUT the sample is hot — 33/40 quarters beat consensus (82%
vs the 75-78% long-run base rate), mean surprise +4.36%. Say that out loud.

===============================================================================
2. THE REVENUE PROBLEM (the reason this folder exists)
===============================================================================
EXCALIBUR_NEXT_STEPS.md section 7 plans Revenue as a clone of the EPS engine:
Row1_rev built from "revenue surprise history, actual vs estimate, street
basis, 8 quarters". THAT CANNOT BE BUILT FROM THE CURRENT STACK.

Verified against the cache:
  earnings_dates.csv    EPS Estimate, Reported EPS, Surprise(%)   -> EPS ONLY
  earnings_history.csv  epsActual/epsEstimate/surprisePercent     -> EPS ONLY
  eps_trend.csv         consensus 7/30/60/90d                     -> EPS ONLY
  gaap.json             EDGAR XBRL                                -> actual revenue only
  revenue_estimate      NEVER FETCHED — not in cache at all

yfinance has no revenue equivalent of earnings_dates: revenue_estimate is
forward-only (0q/+1q/0y/+1y), with no historical actual-vs-estimate.

IMPORTANT CORRECTION MADE IN SESSION: this is a yfinance/cache limitation, NOT
a universal one. Revenue surprise history exists at FMP (believed:
historical/earning_calendar carries revenue + revenueEstimated — VERIFY),
Primer (the sponsor, handing out data + API credits at 09:30), Benzinga,
Zacks/Nasdaq/StockAnalysis (public pages), and all the commercial feeds.
fmp_probe.py exists to settle this in one run.

===============================================================================
3. THE DESIGN — GUIDANCE-FIRST, NOT AN EPS CLONE
===============================================================================
Cloning the EPS engine is wrong on the merits, independent of data:

  The analyst walk-down is an EPS phenomenon. Management sandbags EPS guidance,
  analysts step just under the bar, the company beats. That is a behavioural,
  persistent, firm-level bias — exactly what a "beat habit" prior captures.
  On the TOP LINE that game barely exists: revenue beats ~60% at ~+1% versus
  EPS 75-78% at +2-5% (the team's own brief). Meanwhile revenue is guided
  explicitly and narrowly — NVDA says "$91.0 billion plus or minus 2%".

  So: keep the ledger ARCHITECTURE (one code path, same glass-box story) but
  INVERT the weights. Row 2 (guidance) is the workhorse; Row 1 is a residual.

    forecast_Rev = consensus_rev x (1 + A_rev)
    A_rev = (Row1_rev + Row2_rev + Row5_rev) x Row3_rev    # NO Row 4

  Row 4 is correctly dropped — buybacks lift EPS by shrinking the share count
  and do not touch revenue.

THE TWO-FEED ROW 1 (the adapter seam, so tomorrow's data question is not a
fork in the road). Same maths, swapped input, feed name logged to the ledger:

  "revenue_surprise"  (actual - point_in_time_estimate)/estimate    PREFERRED
                      cache/raw/<T>/revenue_surprises.json
                      [{"period_end","actual","estimate"}, ...]
                      source: Primer adapter or FMP

  "guide_beat"        (actual - guided_midpoint)/guided_midpoint    OFFLINE
                      cache/raw/<T>/guidance_history.json
                      [{"period_end","guided_midpoint"}, ...]
                      built from the already-cached 8-K exhibits

  The guide_beat feed is not a consolation prize. It measures the sandbag at
  its SOURCE rather than through the analyst intermediary. Quotable line:
  "for revenue we don't measure how much they beat the Street, we measure how
  much they beat themselves — that's where the sandbag actually lives."

row1_rev() calls the EXISTING engine.row1_firm_prior() verbatim — same
reliability, same lambda, same shrinkage. Only the series changes.

THE GUIDANCE NORMALISER (the piece not to skip). Guidance in this book comes in
five incompatible shapes. The LLM extracts into a typed spec and NEVER
computes; to_quarterly_dollars() does the arithmetic in plain auditable code.
Verified working on all five:

  NVDA  DOLLARS/QUARTER      -> $91.00bn   direct
  WMT   GROWTH_PCT/QUARTER   -> $175.56bn  +4.5% on year-ago $168.00bn
  TGT   GROWTH_PCT/YEAR      -> $26.17bn   FY +4.0% x seasonal share 25.2%
  TJX   COMP_PCT/QUARTER     -> $7.26bn    comp +3.5% + measured spread +1.5%
  CRWD  ARR                  -> None       REFUSES rather than guessing (Row2=0)

  (grepped from the cached 8-Ks: HD, LOW, MRVL returned 0 hits on the quick
  regex — MRVL and ADI do guide quarterly revenue in dollars, the regex just
  missed them; HD and LOW guide annually. Re-check those three by hand.)

Row 2 uses GUIDANCE_GAP_FRACTION_REV = 0.8 (vs 0.5 for EPS — revenue guides
bind harder) and is SIGNED BOTH WAYS, so the U1 fix is already correct here.
Verified: a guide-down produces A_total -5.63% where the EPS Row 2 returns 0.

The interval centres on OUR forecast (Reading B) by applying the DISPERSION of
the series around the point rather than re-applying the level, so the forecast
cannot fall outside its own interval by construction.

P(rev beat) base rate is 0.60, not 0.77.

===============================================================================
4. FILES IN THIS FOLDER
===============================================================================
revenue_prior.py     Drop in as excalibur/revenue_prior.py. Contains:
                       GuidanceSpec           typed schema the LLM emits
                       to_quarterly_dollars() deterministic normaliser
                       revenue_actuals()      loader (revenue_actuals.json,
                                              falls back to gaap.json)
                       year_ago_quarter(), seasonal_share()
                       revenue_surprise_series()  feed A
                       guide_beat_series()        feed B
                       build_feed(), sector_feed_median()
                       row1_rev()             reuses engine.row1_firm_prior
                       forecast_revenue()     full revenue ledger
                       GUIDANCE_EXTRACT_SYSTEM  the LLM prompt
                     Compiles clean; smoke-tested against the real cache.

fmp_probe.py         Settles whether a revenue surprise history is obtainable.
                     Stdlib only, read-only.
                       FMP_API_KEY=xxx python fmp_probe.py
                       FMP_API_KEY=xxx FINNHUB_API_KEY=yyy python fmp_probe.py NVDA WMT TJX
                     Probes 5 FMP + 2 Finnhub endpoints, reports how many
                     quarters carry BOTH an actual revenue and an estimate,
                     flags 8+ as USABLE. Critically, it labels which endpoints
                     are POINT-IN-TIME: historical/earning_calendar's
                     revenueEstimated is legitimate; analyst-estimates returns
                     TODAY'S estimates for past periods and using it
                     historically is lookahead — the exact sin that got the
                     RFS 2023 paper flagged. Do not let anyone grab the wrong
                     one at 11am.

smoke_rev.py         Test harness for revenue_prior. Run from the repo root
                     with PYTHONPATH set to the repo:
                       PYTHONPATH=. python smoke_rev.py
                     Exercises all five guidance shapes, the seasonality and
                     year-ago lookups, feed availability, an end-to-end
                     guidance-only forecast, and the guide-down sign check.

guidance_history.py  Drop in as excalibur/guidance_history.py. THE BUILDER.
                     Runs the guidance extractor over the cached 8-K exhibits
                     and emits per ticker:
                       cache/raw/<T>/guidance_history.json  -> feed B (Row 1)
                       cache/raw/<T>/guidance_current.json  -> Row 2, live
                     THE MAPPING THAT MATTERS: an 8-K filed 2026-05-20 REPORTS
                     the quarter that just ended and GUIDES the next one, so a
                     filing's guidance belongs to the quarter AFTER the one it
                     reports. Resolved from the actuals calendar, not by date
                     arithmetic. If the guided quarter has an actual it becomes
                     a guide_beat observation; if not, it is the LIVE guide.
                     Exhibits filed the same day are bundled (NVDA's guidance
                     is in the CFO commentary, not the press release).
                     Modes:
                       python -m excalibur.guidance_history --inspect
                         No API key. Regex-locates candidate guidance
                         sentences, prints the filing->guided-quarter mapping
                         and the coverage you would get. Use it to eyeball or
                         to hand-enter.
                       python -m excalibur.guidance_history
                         LLM extraction, cached per (ticker, filing date).
                       cache/manual_guidance.json
                         {"NVDA": {"2026-07-26": 91.0e9}} in DOLLARS, merged
                         last, wins over the LLM.
                     VERIFIED in --inspect against the real cache. Mapping is
                     correct: NVDA filed 2026-05-20 -> reports 2026-04-26 ->
                     guides 2026-07-26 (live). WMT's 2026-01-16 press release
                     is correctly rejected as not an earnings 8-K.

fetch_gaap_FIXED.py  REPLACES excalibur/fetch_gaap.py. Four bugs fixed —
                     see 4b below. Tested against live EDGAR: all ten names
                     now current through 2026.

test_gaap_fix.py     Standalone OLD-vs-NEW proof against live EDGAR.
                       python test_gaap_fix.py NVDA TJX WMT

eps_diagnostics/     Reproduce the section-1 findings. Run from the repo root
                     with PYTHONPATH set to the repo.
                       diag.py   extended lambda sweep, headline-claim
                                 provenance, which rows are live in replay,
                                 reliability floor, sector coverage, direction
                       diag2.py  flat-uplift baselines, beat regime, where the
                                 ledger adds over a flat uplift, interval check
                       diag3.py  live forecast table for all 10 names,
                                 fiscal-label check, Row 4 flag vs real drift

===============================================================================
4b. THE fetch_gaap FIX — FOUR BUGS, TESTED AGAINST LIVE EDGAR
===============================================================================
 1. TAG SHADOWING (the one that bit). quarterly_series() returned the FIRST
    revenue tag with ANY data and never looked at the rest. Filers switch tags
    over time (ASC 606 moved most from SalesRevenueNet / Revenues to
    RevenueFromContractWithCustomer*), so a filer whose OLD data sat under the
    first-listed tag was stranded there.
    FIX: merge across ALL tags, lowest priority first so the preferred tag
    overwrites on overlap.
    PROVEN:  NVDA  OLD 12q 2017-04-30..2020-01-26  ->  NEW 66q ..2026-04-26
             TJX   OLD 32q 2017-04-29..2026-05-02  ->  NEW 66q ..2026-05-02
    NVDA's latest quarter now reads $81.61bn, matching the cached CFO
    commentary ($81,615m) exactly.

 2. QUARTER DETECTION BY MONTH ARITHMETIC. (month(end)-month(start))%12 in
    2..4 also admits 4-month stubs and mishandles 52/53-week retail calendars.
    FIX: real day count, 75..115 days.

 3. RESTATEMENTS RESOLVED BY ITERATION ORDER. companyfacts unit arrays are not
    guaranteed filing-ordered.
    FIX: keep the observation with the latest `filed` date explicitly.

 4. MISSING Q4 — surfaced only after fixing 1-3. Filers report Q1-Q3 as
    discrete durations in 10-Qs; Q4 exists only inside the 10-K's ANNUAL
    figure, so every fiscal year had a hole (NVDA had no 2026-01-25).
    Holes are worse than they look: revenue_prior's year_ago_quarter() and
    seasonal_share() originally walked the series BY INDEX, so stepping back
    4 indexes across a hole silently returned the WRONG quarter.
    FIX (two-sided):
      a) derive Q4 = FY - (Q1+Q2+Q3) where the annual duration and all three
         interior quarters exist; derived rows carry "derived_q4": true.
      b) revenue_prior's lookups are now DATE-matched with tolerance, not
         index-matched, so a residual hole drops that year instead of
         corrupting the answer.
    The fixed loader also prints GAPS per name and refuses to let them pass
    silently.

 RESULT after the fix (live run, all ten names):
   HD LOW WMT TGT TJX ADI NVDA  12q each, contiguous, 3 Q4s derived
   MRVL INTU CRWD              12q each, ONE GAP each (a quarter where
                               revenue and net income do not both exist)
 The three gapped names are flagged by the loader. The date-based lookups
 handle them correctly; the auditor's margin check should still be treated
 with care there.

 IMPACT: these corrections moved real numbers. WMT's year-ago quarter went
 $168.00bn -> $163.98bn (it had been reading the wrong quarter) and TGT's
 seasonal share went 25.2% -> 29.0%.

===============================================================================
5. BUILD ORDER (was proposed for the night of 15 Aug)
===============================================================================
  1  Fetch Ticker.revenue_estimate for the 10 names       ~15 min
     -> consensus_rev + analyst low/high. Nothing works without it.
        Grab Ticker.earnings_estimate in the same pass — that also fixes the
        EPS soft-clamp's missing analyst range (finding 1.1).
  2  Fetch quarterly_income_stmt -> TotalRevenue          ~15 min
     -> cache/raw/<T>/revenue_actuals.json. Fresher than EDGAR and sidesteps
        the XBRL tag trap.
  3  Revenue ledger, GUIDANCE-ONLY (Row1=0, Row3=1.0)     ~45 min
     -> a defensible glass-box revenue forecast that ships. STOP HERE IF SHORT.
  4  Typed guidance schema + conversion                   ~45 min
  5  Guide-beat prior -> Row1_rev                         ~45 min
  6  fetch_gaap.py tag merge                              ~15 min
     -> also un-breaks the auditor's margin check on NVDA and TJX.

REVISED after the 15 Aug follow-up (steps 4-6 are now written, not just specced):
  0  Raise fetch_text n=3 -> n=12, re-run fetch_text      ~10 min  DO FIRST
     -> without this, feed B cannot activate (section 6F).
  1  Copy fetch_gaap_FIXED.py over excalibur/fetch_gaap.py, re-run it   ~5 min
  2  Copy in revenue_prior.py and guidance_history.py                   ~2 min
  3  python -m excalibur.guidance_history --inspect       ~2 min
     -> confirm coverage cleared 4+ per name before spending an API key
  4  python -m excalibur.guidance_history                 ~10 min (LLM, cached)
  5  Fetch revenue_estimate + earnings_estimate           ~15 min
     -> consensus_rev, analyst ranges, and the EPS soft-clamp's missing range
  6  Wire forecast_revenue() into app.py                  ~30 min

===============================================================================
6. OPEN DECISIONS
===============================================================================
 A. NO FEED => NO INTERVAL. With guidance-only there is no surprise
    distribution, so the interval collapses to a point (visible in the smoke
    test). Proposed fix: use MANAGEMENT'S OWN GUIDED RANGE as the interval —
    NVDA hands you +/-2%. Arguably a better revenue interval than a historical
    one, and a good line for the judges. NOT YET IMPLEMENTED.

 B. REVENUE BACKTEST. Originally advised against — with no historical revenue
    consensus there is nothing to replay against. RETRACTED CONDITIONALLY: if
    the probe finds a point-in-time source, a revenue replay becomes possible
    and should be run (same backtest.py structure, swap the series). Skip it
    only if both FMP and Primer come up empty. Never substitute
    analyst-estimates retro-applied to past quarters.

 C. RESOLVED. fetch_gaap_FIXED.py replaces the broken loader; all ten names
    now run through 2026. See section 4b. Still to do: copy it over the repo
    file and re-run `python -m excalibur.fetch_gaap`.

 D. HD, LOW, MRVL guidance shapes unconfirmed. VIKTOR EXPLICITLY DEFERRED
    THIS — not chased. MRVL and ADI almost certainly guide quarterly revenue
    in dollars; HD and LOW guide annually. Check by hand before relying on
    Row 2 for those names.

 E. RESOLVED. guidance_history.py is written and verified in --inspect mode.

 F. *** NEW BLOCKER, FIX THIS FIRST ***
    THE FILING CACHE IS TOO THIN FOR FEED B TO ACTIVATE.
    fetch_text.fetch_8k_press_releases defaults to n=3 filings per name.
    Three filings yield at most TWO usable guide_beat observations, because
    the newest filing's guided quarter has not reported yet (it is the live
    Row 2 guide, not a history point).
    Measured with --inspect on the real cache:
        NVDA 2    WMT 1    TJX 2    TGT 2      (need 4 for a firm feed,
                                                8 for the sector median)
    So revenue_prior.guide_beat_series() returns None for every name and
    Row1_rev falls to 0.0 — the ledger runs on guidance alone.
    FIX: raise n from 3 to 12 in fetch_text.fetch_8k_press_releases and re-run
    `python -m excalibur.fetch_text`. That yields ~11 usable observations per
    name, which clears both thresholds. It is a one-character change plus a
    fetch; do it before anything else in the revenue path.
    FALLBACK: hand-enter into cache/manual_guidance.json (the plan already
    sanctions manual entry for ~10 numbers).
    NOTE: guidance-only revenue still works today without this. Feed B is the
    upgrade, not the baseline.

===============================================================================
7. THE PAYOFF NOT BEING COUNTED
===============================================================================
Once a revenue forecast exists, AUDITOR RULE #2 COMES ALIVE. Implied net margin
= (forecast_EPS x shares) / forecast_Revenue, checked against history. That
rule is currently dead code because there is no revenue to divide by. The two
forecasts start auditing each other, and a disagreement there is a GENUINE
auditor trigger on real inputs — which is exactly the on-stage moment the demo
was still missing (NEXT_STEPS section 5, Viktor checklist #10).

===============================================================================
8. ENVIRONMENT NOTES
===============================================================================
- Research lives in WSL Ubuntu at /home/viktorsebek1/Research, reachable from
  Windows at \\wsl.localhost\Ubuntu\home\viktorsebek1\Research (there is no
  separate Linux partition; disk 0 is entirely Windows).
- The Excalibur repo was cloned to a Windows scratch dir, not into Research.
- Backtests above were run with C:\Users\vikto\AppData\Local\Python\bin\
  python.exe (3.14.3, pandas 3.0.1). The repo also expects pydantic and
  streamlit.
- Viktor's own venv with pandas/numpy/yfinance/openai/pymupdf is at
  ~/Research/FinRobot/.venv (WSL side).
