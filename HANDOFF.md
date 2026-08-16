# HANDOFF — state of Jayesh's lane (systems/data), for Viktor, David, Larissa

## FINAL RUN PROCEDURE (17:15–18:00) — READ THIS FIRST

THE final command (declared in entry.json; judges verify the log against it):

    ./run_final.sh

What it does: tier1 seasonal-naive baseline -> baseline/ (comparison only),
then the agent pipeline -> submission/ (the four workbooks that get uploaded),
then `npm run check:forecasts`, all teed into logs/final-run-<ts>.log with the
commit hash (this IS the required clear-run log).

Modes:
    ./run_final.sh --fallback     BREAK-GLASS ONLY: tier1 straight into
                                  submission/ if the agent pipeline is down
    ./run_final.sh --with-tier2   also run David's tier2 extraction diff first

Sequence at 17:15:
 1. Refetch consensus (python -m agent.consensus) — the freshness gate
    requires a same-day fetch.
 2. Commit everything; put the commit hash + repo URL in entry.json.
 3. ./run_final.sh   -> confirm "All four forecast workbooks are ready".
 4. From 17:30: upload each submission/*.xlsx manually to its company
    Forecast Model on openstocks.com (Larissa owns uploads).
 5. Submit entry.json + architecture/index.html via the private form at
    openstocks.com/hackathon. ALL before 18:00.
DO NOT run `python -m agent.run` bare for the final run (works, but skips the
baseline + commit-stamped clear-run log), and never run --fallback after the
real run (it would overwrite submission/ with baseline numbers).

Updated: Sun 16 Aug, late afternoon. Status: all 12 numbers computed per
amendments 2/3/4-updated/6 + Viktor's rulings; tests ALL PASS; workbooks PASS.

## VIKTOR — final sign-off needed (§5: you own the final 12)
Current 12 (each with tier/period/basis/receipt in logs/run-*.log):
  HD 47,191 / 4.65 / +0.2 · ADI 3,905 / 3.31 / 72.5
  HAS 881.8 / 1.14p / 46.0 · DE 12,689 / 4.70 / 474
TWO OPEN CALLS (everything else is implemented per your amendments):
1. HAS op profit: your "top of range" 46.0 vs company consensus 43.5 —
   ratify 46.0 or pick 44.5–45.5.
2. DE EPS: deterministic phasing of YOUR FY guide gives target 4.69 (FY25's
   actual Q3-share of H2 = 54.8%, receipted) -> forecast 4.70. Your prose
   estimate was ~4.5 -> ~4.54. Say which; I will not silently override the
   receipted calculation.
Also: amendment4_updated Rulings §3 still says £12m/38% while its own anchors
section says £13m/45% — fix the file so the record is consistent.
Precision option: swap HD Q2-FY25 base 45,300 (prose-rounded) for David's
table-exact 45,277 — moves HD sales ~-8.

## DAVID — LLM lane
- **Corpus numbers are MANGLED by PDF→md conversion**: "£4 3.5 m" (spaces
  inside digits). Your extraction prompts must tolerate split digits; my
  regexes use [\d\s.]+ then strip spaces. Expect the same in transcripts.
- My regex extraction covers the 23 required facts (test 2 enumerates them).
  LLM work most useful on: transcripts tone/evidence (capped signal), any
  guidance my patterns can't reach, and the critic call for Larissa's auditor.

## LARISSA — validation/auditor/HTML
- Validator gate lives in `agent/run.py` validate() — sanity RANGES per metric;
  refine bounds + add your checks there. Tests prove it rejects planted values.
- All-12 seam check + consensus freshness check are in main().
- Cross-check identities available from facts: EPS ⟺ (op profit − finance) ×
  (1−ETR) ÷ shares (HAS); worldwide ⟺ equipment + bridge (DE); segment sum (DE).
- For the HTML honesty section: hardcoded-guess bug (Hays interest/tax, fixed
  by extraction — 30% EPS impact), the mangled-digits corpus quirk, the
  fiscal-basis traps, and adversarial-verification pass are all good material.
- Run log for judges: `logs/run-*.log` — every number with its receipt.

## Known open items (mine)
- ADI/HD/DE consensus refetch before final run (freshness check enforces today).
- entry.json needs teammate emails + repo URL + final commit + everyone's
  email consent (`emailUseConfirmed`).
