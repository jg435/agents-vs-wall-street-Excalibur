# FOR JAYESH — pre-deadline forecast revisions
# From Viktor, 16 Aug. Everything here is reproducible; nothing needs an API key.

===============================================================================
THE DECISION IN ONE TABLE
===============================================================================

  company  metric                  submitted   ->  revised   evidence
  -------  ----------------------  ---------      -------    ------------------
  ADI      Adjusted diluted EPS       3.31    ->    3.52     STRONG   change
  ADI      Revenue (USDm)            3,905    ->    4,000    MODERATE change
  DE       Diluted EPS (GAAP)         4.70         KEEP      alpha is CONTAMINATED
  HD       everything                  —            —        KEEP — evidence says no
  HAS      everything                  —            —        KEEP — no data exists

Two changes I would make without hesitating (ADI x2), one that is a judgement
call (DE), and one deliberate no-change that is a real finding, not laziness.

===============================================================================
WHY — THE SHORT VERSION
===============================================================================
Our engine anchors on consensus and moves 0.8 of the way toward guidance. I
estimated that weight properly against 29 quarters of ADI history. It does not
survive: the fitted weight is negative, 0.8 sits outside its confidence
interval, and out of sample the rule is WORSE than leaving consensus alone.

The reason is a specification error, not a tuning error. Our model has no
intercept — it can only slide between consensus and guidance. It cannot
express "the actual comes in systematically above BOTH", which is exactly what
these names do. Add an intercept and the guidance gap contributes ~nothing
while the intercept alone cuts out-of-sample error by 30%.

So the fix is not a different weight. It is adding the term we were missing:

        forecast = consensus x (1 + alpha)      alpha = the persistent beat

===============================================================================
THE NUMBERS, PER NAME
===============================================================================
Last 24 quarters, alpha fitted on the first 16, scored on the last 8. Median
(robust) not mean. Reproduce with:  python alpha_recent.py

  ADI   median alpha +5.60%   beats consensus 22/24   OOS -65.4%  ✅
        last 4 beats: +5.1%, +1.3%, +6.5%, +6.2%   — consistent
        3.33 x 1.056 = 3.52
        Corroborated twice over: the full-history fit gives +4.6% (-> 3.48),
        and Viktor's band study gives mean band position 1.17 (-> ~3.50).
        Three different routes, same answer. Our submitted 3.31 is BELOW
        consensus — the one direction the evidence rules out.

  DE    *** DO NOT APPLY ALPHA — IT IS CONTAMINATED BY A ONE-OFF ***
        Raw median alpha looked like +15.51% (22/24, OOS -10.9%), which would
        have implied 4.72 x 1.155 = 5.45. That number is WRONG. Here is why:

        Deere's Q2 FY26 8-K: "recorded a recovery of $272 million for refund
        claims related to IEEPA tariffs". At ~22.5% tax over 270.8m shares
        that is $0.78/share. The Q2 beat was 6.55 - 5.70 = $0.85.
        => 92% of that quarter's beat is a NON-RECURRING tariff refund.
        Ex-one-off, Q2 beat +1.3%, not +14.9%.

        Checked Q1 FY26 separately: it discusses the IEEPA court decision but
        records no recovery, so the refund lands in Q2 only. Q1's +15.2% beat
        is NOT explained by this and has no identified cause — treat it as
        unexplained rather than repeatable.

        Cleaned, the last four quarters are roughly:
              +1.9%, +2.6%, +15.2% (unexplained), +1.3% (ex-refund)
        i.e. a low-single-digit underlying beat, nothing like +15%.

        ACTION: KEEP 4.70. If Viktor wants any uplift at all, cap it around
        +2% (-> 4.81). Do not use 5.45 or 5.29.

        NOTE — this is our own auditor rule working. The engine already
        excluded this same $272m refund from the PPA operating-profit recipe
        ("NOT Q2's 15.7% — $272m tariff-refund one-off"). The alpha approach
        reintroduced it through the back door via the EPS beat history. The
        one-off companion gate exists for exactly this.

        BASIS was checked and is clean: Deere's Q2 8-K says "$6.55 per share"
        and yfinance reports 6.55 — yfinance IS the GAAP figure for DE.

  HD    median alpha +1.57%   beats consensus 20/24   OOS +113.6%  ❌
        last 4 beats: -0.2%, -2.3%, +7.9%, +0.6%
        DO NOT APPLY AN UPLIFT. HD's beat habit has decayed to noise, and
        applying alpha MORE THAN DOUBLES out-of-sample error. Our 4.65,
        slightly below consensus, is the right shape — Q1 EPS printed down
        3.7% YoY. This is the phase+temper rule working. Leave it alone.

  ADI revenue — guide-relative, because no historical revenue consensus exists
        anywhere on free data. From Viktor's band study (band_hit_study.py in
        ~/Research), ADI's actual revenue vs its own guide MIDPOINT:
          +3.8, +3.5, +6.1, +3.2, -0.8, +1.8, +5.6, +4.7, +1.9, +3.5  (%)
          median +3.5%, 9 of 10 above the midpoint
        3,900 x 1.035 = 4,037; the band-position route gives 3,994. Use 4,000.
        n=10 and it is guide-relative not consensus-relative, hence MODERATE
        rather than STRONG.

===============================================================================
WHAT I COULD NOT ESTIMATE — and did not fake
===============================================================================
No historical consensus series exists for any of these, so there is nothing to
fit and nothing to test:

  HD  Net sales · HD Comparable sales %
  DE  Worldwide net sales and revenues · DE PPA operating profit
  ADI Adjusted gross margin
  HAS Net fees · Pre-exceptional basic EPS · Pre-exceptional operating profit
      (yfinance has zero UK coverage; HAS.L returns 0 quarters)

The shipped rule stands for all of them. Inventing a weight in the last hour
would be worse than keeping the one we can at least explain.

===============================================================================
HOW TO VERIFY BEFORE YOU CHANGE ANYTHING  (~2 minutes)
===============================================================================
    python alpha_recent.py          # the numbers above; needs yfinance+network
    cat alpha_recent_output.txt     # my captured run, if the network is down

Deeper, if you want it:
    python weight_study.py          # the 0.8 estimation + OOS test, ADI, n=29
    cat weight_study_output.txt     # captured run
    cat WEIGHT_STUDY_FINDINGS.md    # the full write-up

===============================================================================
IMPLEMENTATION — where the numbers come from in the code
===============================================================================
The engine computes these in agent/run.py provisional_engine():

  ADI EPS      eps = cons["eps"] + GAP_FRACTION * (v("eps_guide_mid") - cons["eps"])
  ADI revenue  rev = cons["revenue_usdm"] + GAP_FRACTION * (v("rev_guide_mid_usdm") - ...)
  DE  EPS      eps = cons["eps"] + GAP_FRACTION * (eps_target - cons["eps"])

CLEANEST CHANGE given the clock — do NOT refactor the engine. Add an explicit,
named per-metric alpha and apply it to the consensus anchor, so the receipt
still explains itself:

    ALPHA = {                      # measured, see README_FOR_JAYESH.md
        ("ADI", "Adjusted diluted EPS"): 0.0560,
        ("ADI", "Revenue"):              0.0350,   # guide-relative, see note
        # DE deliberately absent: its raw alpha is 92% one-off tariff refund.
        # HD deliberately absent: alpha doubles out-of-sample error.
    }

and put the justification in the note string so the receipt stays honest, e.g.
  "consensus $3.33 x (1 + 5.60% measured beat prior, 22/24 quarters,
   out-of-sample MAE -65%) = $3.52"

IMPORTANT: ADI revenue's alpha is measured against the GUIDE midpoint, not
consensus. Either apply it as 3,900 x 1.035, or just hard-set 4,000 with the
note. Do not apply it to the consensus anchor — that would be the wrong base.

Sanity ranges in validate() may reject the new values — check:
  ADI Revenue 3300-4600 (4,000 ok) · ADI EPS 2.5-4.2 (3.52 ok)
  DE EPS 3.0-7.5 (5.45 ok)
All three pass. No range edits needed.

===============================================================================
DEADLINE CHECKLIST
===============================================================================
  [ ] DE: KEEP 4.70 — no action needed (alpha contaminated, see above)
  [ ] Edit the engine for ADI only, re-run ./run_final.sh
  [ ] Confirm "All four forecast workbooks are ready"
  [ ] npm run check:submission
  [ ] Commit; put the NEW commit hash in entry.json
  [ ] Re-upload the CHANGED workbooks to OpenStocks (ADI, and DE if changed).
      HD and HAS are unchanged — no need to re-upload, but re-uploading is
      harmless: last valid file per company before 18:00 wins.
  [ ] Re-submit entry.json + architecture/index.html via the private form
      (newest valid entry is final)

===============================================================================
FILES IN THIS FOLDER
===============================================================================
USE THESE — this task:
  README_FOR_JAYESH.md      this file
  alpha_recent.py           the recommendation's numbers (RUN THIS)
  alpha_recent_output.txt   captured run
  weight_study.py           the 0.8 estimation + OOS test
  weight_study_output.txt   captured run
  adi_triples.json          the 29 (consensus, guidance, actual) triples
  WEIGHT_STUDY_FINDINGS.md  full write-up. Section 7 is the answer to give a
                            judge who asks how 0.8 was validated.
  per_metric_study.py       full-history version. Its split trains on
  per_metric_output.txt     2001-2016 — kept for completeness, but
                            alpha_recent.py is the decision-relevant one.
  excalibur-explained.html  plain-English explainer of the whole system

IGNORE THESE — different project (last night's revenue-path work, not the
hackathon submission):
  revenue_prior.py · guidance_history.py · fetch_gaap_FIXED.py
  fmp_probe.py · smoke_rev.py · test_gaap_fix.py · HANDOFF.md
  eps_diagnostics/

===============================================================================
IF A JUDGE ASKS ABOUT THE 0.8
===============================================================================
Do not defend it. Say this:

"We fixed the weight at 0.8 by judgement. Afterwards we estimated it properly:
on 29 quarters of ADI the fitted weight is negative, 0.8 is outside its
confidence interval, and out of sample the rule loses to leaving consensus
alone. The reason is a specification error, not a tuning error — our model had
no intercept, and what actually predicts this name is a persistent +5% beat
that neither consensus nor guidance captures. Modelling that instead cuts
out-of-sample error by 30%. That is the change we made."

The check we built to audit ourselves is the thing that found this. That is a
stronger story than a defended constant.
