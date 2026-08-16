# Agents vs Wall Street

> ## Team EXCALIBUR — how to run this repo
>
> One-time setup (Python 3.10+, Node):
>
> ```bash
> npm install
> python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
> ```
>
> Produce the four forecast workbooks (the final command):
>
> ```bash
> ./run_final.sh          # baseline -> baseline/, agent forecasts -> submission/, validation, clear-run log
> ```
>
> Useful individual stages:
>
> ```bash
> ./.venv/bin/python -m agent.consensus      # refetch consensus anchors (required same-day)
> ./.venv/bin/python -m agent.extractor      # agent fact extraction (needs .env with OPENAI_API_KEY; see NO-KEY message)
> ./.venv/bin/python -m agent.revision_diff  # stale-guidance check (runs inside agent.run too)
> ./.venv/bin/python -m agent.run            # forecasts only (no baseline/clear-run wrapper)
> ./.venv/bin/python -m agent.backtest       # historical replay + variance
> ./.venv/bin/python -m tests.test_pipeline  # full invariant suite (receipts, periods, basis, workbooks)
> ```
>
> Where things live: facts + receipts in `cache/facts.json`, contracts in
> `cache/contracts/`, run logs in `logs/`, David's baseline in `tier1/`+`tier2/`,
> final workbooks in `submission/`. See `HANDOFF.md` for the 17:15 procedure
> and `Hackathon.md` + amendments for the methodology.

Agents vs Wall Street is a one-day hackathon presented by Primer, OpenStocks, AI Tinkerers and OpenAI. Around 50 people will build 20–25 forecasting agents, working alone or in teams of up to four.

The challenge covers four companies: Home Depot, Analog Devices, Hays plc and Deere & Company. Your agent forecasts three reported figures for each.

The repository includes a frozen historical corpus of 1,139 filings, call-transcript sections and slide documents for the four known companies. Start at [challenge/offline-data/INDEX.md](challenge/offline-data/INDEX.md) or search the Markdown files directly.

Your agent should be able to do the research, make the financial judgements and produce completed OpenStocks workbooks with as little manual help as possible.

## What the day is for

1. **Build something real.** Create a repeatable agent that researches companies, makes financial judgements and produces completed forecast workbooks.
2. **Show what is possible.** Help us learn what works and show how powerful this technology can be when it is assembled properly.

OpenStocks offers ongoing $100 prizes for individual earnings events after the hackathon, so build an agent you can use again.

## The challenge at a glance

- Doors open at 10:00 on Sunday 16 August 2026 at Ground Floor, 33 Johns Mews, London WC1N 2QL. The competition briefing begins at 10:30 and building starts at 11:15.
- Teams can have one to four people.
- Each individual or team enters one agent.
- Each team receives $50 of Codex credit, kindly provided by OpenAI.
- Competition-specific work must be built during the event; evidence of a pre-made entry means disqualification from all prizes.
- Your agent must forecast three figures for each of four companies.
- The final run starts at 17:15 and must finish before the 18:00 deadline.
- OpenStocks opens for challenge uploads at 17:30.
- Your final command must produce all four `.xlsx` workbooks.
- Upload each workbook manually to the matching company Forecast Model on [openstocks.com](https://openstocks.com).
- If you upload more than once, the last valid workbook uploaded for each company before 18:00 is your final forecast.

## What you need to submit

1. A completed private `entry.json` with the agent name, every team member and email address, technical setup and final-run details. Upload it through openstocks.com/hackathon; no account is needed for this private team-entry form.
2. Your code repository and the commit used for the final run.
3. The completed self-contained `architecture/index.html`, uploaded through the same private form. You do not need to host it anywhere.
4. A timestamped log from a clear run of the system.
5. Four completed company workbooks in `submission/`.

Complete [ENTRY.md](ENTRY.md), then read [SUBMISSION.md](SUBMISSION.md) before the final run. The full event rules are in [RULES.md](RULES.md), the day is set out in [SCHEDULE.md](SCHEDULE.md), and the judging process is explained in [JUDGING.md](JUDGING.md).

By submitting the private team entry, your team accepts the hackathon and prize rules in [RULES.md](RULES.md).

## Expected final output

Your final command can use any language or framework, and it can run the four companies one after another or at the same time. It must finish by creating these exact files:

```text
submission/
├── ADI-FY2026Q3.xlsx
├── DE-FY2026Q3.xlsx
├── HAS-FY2026.xlsx
└── HD-FY2026Q2.xlsx
```

Start from the supplied files in `challenge/templates/`. Do not rename the `Summary` sheet, metric labels, units or fiscal-period column.

Run `npm install` and `npm run setup:entry` once. Complete the private `entry.json` and `architecture/index.html`, then use `npm run check:submission` before uploading. It checks the entry record, architecture file and four workbooks. It does not judge whether the forecasts are good.

## Optional document-search helper

[`starter/search.py`](starter/search.py) is a small, dependency-free example of searching the supplied Markdown corpus and producing a cited research note. It does not make forecasts or edit a workbook.

```bash
python3 starter/search.py --company HD
less research/HD.md
```

Use `HD`, `ADI`, `HAS` or `DE` for the four challenge companies. The output contains search leads rather than verified financial history, so check each figure in its cited document. Read [starter/README.md](starter/README.md) for narrower searches and testing instructions.

## Repository map

```text
challenge/                 Companies, metrics, workbooks and historical documents
architecture/index.html    Template for the required architecture explanation
entry.template.json        Template for private team and agent details
submission/                Put the four completed workbooks here
logs/                      Save the final clear-run log here
scripts/                   Local entry and workbook checks
starter/                   Optional historical-document search helper
```

## Licence

The original code and documentation in this repository are available under the [MIT License](LICENSE). The historical company documents under `challenge/offline-data/` are excluded; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Methodology:

An agent that forecasts three metrics for four companies:
* HD (FY2026Q2)
	* Net sales (USDm) · Adjusted diluted EPS (USD/share) · Comparable sales, total company (%)
* ADI (FY2026Q3)
	* Revenue (USDm) · Adjusted diluted EPS (USD/share) · Adjusted gross margin (%)
* DE (FY2026Q3)
	* Worldwide net sales and revenues (USDm) · Diluted EPS (GAAP) (USD/share) · Production & Precision Ag operating profit (USDm)
* HAS (FY2026)
	* Net fees (GBPm) · Pre-exceptional basic EPS (GBp — pence) · Pre-exceptional operating profit (GBPm)

The common shape is top line + earnings per share + one company-specific third metric (a health indicator for retail comps, chip margins, Deere's biggest segment, and Hays' profitability). Those exact label strings and units are what the validator checks against rows 7–9 of each workbook, which is why `history.json` and the Tier 2 extractor use them verbatim.

In total, twelve numbers into four OpenStocks workbooks.

## Tier 1 — model pipeline (`tier1/`):
- **`forecast.py`** — the forecaster. Methods: `growth` (same-period-last-year × blended YoY:
  0.7 recent + 0.3 seasonal; H1 interim pairs drive annual targets) and `pct_blend`
  (0.6 latest + 0.4 prior-year, for mean-reverting % metrics). Supports **`override`** —
  verified company guidance beats the model. Validates labels/units before writing, fails
  loudly on gaps, warns on extreme growth, logs full reasoning to `logs/` (doubles as the
  required clear-run log).
- **`history.json`** — verified figures, every value citing a source document.
- **`find_history.py`** — citation-producing grep helper (superseded by Tier 2 but kept).
- Built via an iterative loop: Claude proposed greps, we ran them, values were transcribed
  with citations. Notable finds: ADI's Q3'25 revenue in a trailing-quarters table, Deere's
  numbers in a transcript with $ garbled to DKK/€, and explicit guidance in ADI's Q2 8-K and
  Hays' July trading update.
- All four workbooks pass the real validator (verified in a sandbox against the actual
  templates and `check-forecasts.mjs`, including a tamper test).

## Tier 2 — LLM extraction (`tier2/`, `run_final.sh`):
- **`extract.py`** — per company: selects documents (anchors-first priority order), prompts
  OpenAI (default `gpt-5`, stdlib only, key from `.env`) to emit history.json-schema JSON
  with verbatim citations and guidance-only overrides; strictly validates output (bad
  extractions save the raw response and never reach the merge); `--diff` compares against the
  hand-built history.json as ground truth; `--merge` backs up then writes.
- **`run_final.sh`** (repo root) — one command: extract → merge → forecast → validate, all
  logged with commit hash. `--no-llm` flag = fallback to the last good history.json if the
  API dies at 17:15.
- **Three debugging rounds, each caught by the diff/validator working as designed**:
  1. Model echoed units into JSON keys → prompt fix + defensive key normalization.
  2. Document selection missed the prior-year anchors and Hays' results decks → event
     dedupe + target-aware anchor selection + slides included.
  3. Anchors were appended last and got truncated at the 220k-char budget → anchors-first
     ordering + stale-slide filter.
- **Final diff: clean.** The extractor reproduces every hand-verified value, found all three
  overrides (ADI $3,900M / $3.30, HAS £46.0M), and extracted numbers never transcribed
  manually (DE FY2024Q3: 13,152 / 6.29 / 1,162; HAS FY2024; ADI FY2024Q3). One value it
  likely got *more* right than the manual pass: HAS H1'25 net fees 496.0 (reported) vs 498.3
  (derived).

## Current forecasts (will shift slightly after merge — richer seasonal pairs)

| Company | Post-merge expectation | Basis |
|---|---|---|
| HD (FY2026Q2) | $47,456M · $4.56 · +0.8% | Model (unchanged) |
| ADI (FY2026Q3) | $3,900M · $3.30 · 71.5% | Guidance ×2, model |
| HAS (FY2026) | ~£877M · 0.65p · £46.0M | Model ×2, guidance |
| DE (FY2026Q3) | ~$12.1B · ~$4.36 · ~$335M | Model |

* Home Depot (FY2026Q2)
	* Net sales (USDm) · Adjusted diluted EPS (USD/share) · Comparable sales, total company (%)
* Analog Devices (FY2026Q3)
	* Revenue (USDm) · Adjusted diluted EPS (USD/share) · Adjusted gross margin (%)
* Hays (FY2026)
	* Net fees (GBPm) · Pre-exceptional basic EPS (GBp — pence) · Pre-exceptional operating profit (GBPm)
* Deere (FY2026Q3)
	* Worldwide net sales and revenues (USDm) · Diluted EPS (GAAP) (USD/share) · Production & Precision Ag operating profit (USDm)

## Status of deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | Four valid workbooks | ✅ (Tier 1 basis; regenerate post-merge) |
| 2 | `entry.json` | ⬜ created via `setup:entry`, needs team details |
| 3 | `architecture/index.html` | ⬜ not started (run logs + this summary are the material) |
| 4 | Clear-run log | ✅ produced automatically by `run_final.sh` |
| 5 | Repo committed with final-run commit hash | ⬜ |
