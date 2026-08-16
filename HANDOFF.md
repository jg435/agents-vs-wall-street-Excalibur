# HANDOFF — state of Jayesh's lane (systems/data), for Viktor, David, Larissa

Updated: Sun 16 Aug, afternoon. Pipeline: `python -m agent.run` (from repo root,
venv: `./.venv/bin/python`). Tests: `./.venv/bin/python -m tests.test_pipeline`.

## VIKTOR — engine recipes (your slot: `provisional_engine()` in agent/run.py)
Everything you need is in `cache/contracts/<T>.json` (facts with receipts +
consensus + notes). Current numbers are ANCHOR PASSTHROUGH. Decisions waiting:
1. **ADI double-count warning**: consensus ($3.33 / $3,925m) already sits ABOVE
   guide mid ($3.30 / $3,900m) — the Street has priced the beat. Measured
   guide-beat median is in `ADI.rev_guide_beat_median_pct` (from ~30 paired
   quarters, receipts in research/adi_guides.json). Tilt from consensus.
2. **DE basis trap**: yfinance revenue consensus (~$10.7bn) is EQUIPMENT-OPS
   net sales; the metric is WORLDWIDE net sales AND revenues (FY25 Q3 =
   $12,018m; equipment $10,357m; bridge = $1,661m fin-svcs+other). All three
   segment Q3-FY25 bases extracted (PPA/SAT/CF sales + op profit).
3. **HAS op profit call**: company consensus £43.5m (10 analysts) vs management
   "top of £37–46m range". Current number 46.0 — consider 44.5–46.
4. **HAS net fees**: FY25 £972.4m × (1−5%) applies Q4's LFL to the whole year —
   the roughest anchor in the set. Quarterly LFL path + FX bridge is your call.
5. **HD phasing**: FY guides only (sales +2.5–4.5%, comp flat–+2%, adj EPS
   flat–+4% from $14.69). Q1 ran +4.8% sales / +0.6% comp. Q2 FY25 bases
   extracted ($45,300m / $4.68 / +1.0comp).
6. HAS EPS now derived with FY25 ACTUAL finance charge (£13.4m) and
   pre-exceptional ETR (35.1%) → ~1.35p (was 1.9p on my guessed inputs).

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
