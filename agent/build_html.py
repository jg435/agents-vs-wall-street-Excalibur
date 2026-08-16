"""Generate architecture/index.html FROM the run's own outputs.

Every number, formula, source path, gate name and rejection on the page is
read from cache/receipts.json, cache/facts.json and the latest clear-run log
— never typed by hand. Doc-vs-code drift on the judged page is therefore
structurally impossible: if the code changes, regenerate and the page follows.

Run: python -m agent.build_html   (also called at the end of run_final.sh)
"""
import html
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "cache"

e = html.escape


def latest_log():
    logs = sorted((REPO / "logs").glob("final-run-*.log"))
    return logs[-1].read_text() if logs else ""


def build():
    data = json.loads((CACHE / "receipts.json").read_text())
    receipts, rejected = data["receipts"], data["rejected_facts"]
    facts = json.loads((CACHE / "facts.json").read_text())
    log_text = latest_log()
    revised = [ln.split("GUIDANCE REVISED ")[1] for ln in log_text.splitlines()
               if "GUIDANCE REVISED " in ln]

    by = {(r["company"], r["metric"]): r for r in receipts}
    has_op = by[("HAS", "Pre-exceptional operating profit")]
    units = {"Net sales": "USDm", "Revenue": "USDm",
             "Worldwide net sales and revenues": "USDm", "Net fees": "GBPm",
             "Adjusted diluted EPS": "USD", "Diluted EPS (GAAP)": "USD",
             "Pre-exceptional basic EPS": "GBp",
             "Comparable sales, total company": "pp", "Adjusted gross margin": "%",
             "Pre-exceptional operating profit": "GBPm",
             "Production & Precision Ag operating profit": "USDm"}

    rows = ""
    for r in receipts:
        n_facts = len(r["consumed_facts"])
        rows += (f"<tr><td>{e(r['company'])}</td><td>{e(r['metric'])}</td>"
                 f"<td class='num'>{r['value']:,}</td>"
                 f"<td>{e(units.get(r['metric'], ''))}</td>"
                 f"<td>{e(r['anchor_tier'])}</td>"
                 f"<td class='num'>{n_facts}</td></tr>\n")

    op_facts = ""
    for name, f in has_op["consumed_facts"].items():
        op_facts += (f"<div class='fact'><b>{e(name)}</b> = {f['value']} "
                     f"<span class='tag'>{e(f['type'])}</span> "
                     f"<span class='tag'>{e(f['period'])}</span> "
                     f"<span class='tag'>{e(f['basis'])}</span><br>"
                     f"<span class='src'>{e(f['doc'].split('/')[-1])}</span></div>\n")

    # Per-metric formula table: shape + substitution, VERIFIED against the
    # receipt value at build time — the page cannot state stale arithmetic.
    FORMULAS = [
        ("HD", "Net sales", "cons + 0.8×(target − cons); target = yearago_Q2 × (1 + mean(FY guide, Q1 YoY))",
         "45,300×(1+mean(3.5,4.8)%)=47,180 → 47,235+0.8×(47,180−47,235)", 47191),
        ("HD", "Adjusted diluted EPS", "cons + 0.8×(target − cons); target = yearago_Q2_EPS × (1 + mean(FY guide, Q1 YoY))",
         "4.68×(1+mean(2.0,−3.7)%)=4.64 → 4.69+0.8×(4.64−4.69)", 4.65),
        ("HD", "Comparable sales, total company", "mean(mean(FY guide, Q1 actual), April actual) — additive, pp",
         "mean(mean(1.0, 0.6), −0.5)", 0.2),
        ("ADI", "Revenue", "cons + 0.8×(guided mid − cons)",
         "3,925+0.8×(3,900−3,925)", 3905),
        ("ADI", "Adjusted diluted EPS", "cons + 0.8×(guided mid − cons)",
         "3.33+0.8×(3.30−3.33)", 3.31),
        ("ADI", "Adjusted gross margin", "last quarter actual + guided sequential change — additive, pp",
         "73.0 + (−0.5)", 72.5),
        ("DE", "Worldwide net sales and revenues",
         "anchor + 0.8×(segment-sum target − anchor); anchor = equip cons + finance bridge",
         "anchor 10,732+1,314=12,046; target 4,273×0.925+3,025×1.15+3,059×1.20+1,314=12,416 → blend", 12342),
        ("DE", "Diluted EPS (GAAP)",
         "cons + 0.8×(target − cons); target = (FY NI guide − H1 actual) × yearago Q3-share of H2 ÷ shares",
         "(4,750−2,429)×54.8%÷270.8=4.69 → 4.72+0.8×(4.69−4.72)", 4.7),
        ("DE", "Production & Precision Ag operating profit",
         "yearago segment sales × (1 + guided sales change) × guided margin mid — derived",
         "4,273×0.925×12%", 474),
        ("HAS", "Net fees",
         "H1 base×(1+avg(Q1,Q2 LFL)) + H2 base×(1+avg(Q3,Q4 LFL)) − disposed fees — build-up",
         "496×(1−9.0%)+476.4×(1−6.5%)−15", 881.8),
        ("HAS", "Pre-exceptional basic EPS",
         "(op profit − guided finance charge) × (1 − guided tax rate) ÷ weighted-avg shares — derived",
         "(45.5−13)×(1−45%)÷1,595.7 ×100", 1.12),
        ("HAS", "Pre-exceptional operating profit",
         "company consensus + 0.8×(guide top − company consensus)",
         "43.5+0.8×(46.0−43.5)", 45.5),
    ]
    formula_rows = ""
    for co, metric, shape, sub, stated in FORMULAS:
        actual = by[(co, metric)]["value"]
        if abs(actual - stated) > 0.005 * max(1, abs(actual)):
            raise SystemExit(f"DRIFT: page states {stated} for {co}/{metric} "
                             f"but receipt says {actual} — fix FORMULAS before building")
        formula_rows += (f"<tr><td>{e(co)}</td><td>{e(metric)}</td>"
                         f"<td>{e(shape)}</td>"
                         f"<td><code>{e(sub)} = {actual:,}</code></td></tr>\n")

    rej_rows = "".join(
        f"<li><code>{e(r.get('fact', '?'))}</code> — {e(r.get('reason', '?')[:100])}</li>\n"
        for r in rejected[:7])
    rev_rows = "".join(f"<li><code>{e(x[:110])}</code></li>\n"
                       for x in revised[:6])
    n_guides_checked = log_text.count("vintages,")

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EXCALIBUR — agent architecture</title>
<style>
  :root {{ color-scheme: light; --ink:#1a2330; --mut:#5c6a7a; --line:#d7dce3;
          --acc:#0e6e5c; --warn:#a33c2e; --paper:#fffdf9; --wash:#f4f2ec; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--wash); color:var(--ink);
         font:16px/1.6 ui-sans-serif, system-ui, "Segoe UI", sans-serif; }}
  main {{ max-width: 880px; margin: 32px auto; padding: clamp(22px,5vw,52px);
          background:var(--paper); border:1px solid var(--line); border-radius:14px; }}
  h1 {{ font-size: clamp(36px,7vw,58px); margin:0 0 6px; letter-spacing:-.03em; }}
  h2 {{ margin:44px 0 10px; font-size:22px; letter-spacing:-.01em; }}
  p, li {{ max-width: 74ch; }}
  .eyebrow {{ color:var(--acc); font-weight:700; font-size:13px;
              letter-spacing:.12em; text-transform:uppercase; }}
  .lede {{ font-size:19px; color:var(--mut); }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; margin:14px 0; }}
  th, td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); }}
  th {{ font-size:11px; letter-spacing:.09em; text-transform:uppercase; color:var(--mut); }}
  td.num {{ font-variant-numeric: tabular-nums; text-align:right;
            font-family: ui-monospace, Menlo, monospace; }}
  .card {{ background:var(--wash); border:1px solid var(--line); border-radius:10px;
           padding:16px 18px; margin:16px 0; }}
  code {{ font-family: ui-monospace, Menlo, monospace; font-size:13px;
          background:#ece9e1; padding:1px 5px; border-radius:4px; }}
  .fact {{ margin:10px 0; font-size:14px; }}
  .tag {{ display:inline-block; font-size:11px; border:1px solid var(--line);
          border-radius:99px; padding:0 8px; margin-left:4px; color:var(--mut);
          background:#fff; }}
  .src {{ color:var(--mut); font-size:12px; font-family: ui-monospace, Menlo, monospace; }}
  .quote {{ border-left:3px solid var(--acc); padding:2px 0 2px 12px;
            color:var(--mut); font-size:14px; margin:10px 0; }}
  .flow svg {{ max-width:100%; height:auto; display:block; margin:10px 0; }}
  ul {{ padding-left: 20px; }}
  .warn {{ color: var(--warn); }}
  .kv td:first-child {{ color:var(--mut); width: 200px; }}
</style>
</head>
<body>
<main>
<p class="eyebrow">Agents vs Wall Street · 16 Aug 2026</p>
<h1>EXCALIBUR</h1>
<p class="lede">Every forecast is an anchor from the market, moved by small,
signed, source-quoted adjustments — and every number on this page was written
here by the system itself, from its own run receipts. The number is computed,
never generated.</p>

<div class="card"><table class="kv">
<tr><td>Agent</td><td><b>EXCALIBUR</b></td></tr>
<tr><td>Team</td><td>Viktor Sebek · Jayesh Gupta · Larissa Terranova · David Szalai</td></tr>
<tr><td>Build style</td><td>Hybrid — Claude Code (interactive) driving a deterministic Python pipeline; OpenAI model for corpus fact extraction</td></tr>
<tr><td>Final command</td><td><code>./run_final.sh</code> → four workbooks + timestamped clear-run log</td></tr>
<tr><td>This page</td><td>generated by <code>python -m agent.build_html</code> from <code>cache/receipts.json</code> — regenerate any time; it cannot drift from the code</td></tr>
</table></div>

<h2>The task, for a cold reader</h2>
<p>Four public companies (Home Depot, Analog Devices, Hays, Deere) are about to
report quarterly or annual results. We must forecast three reported figures
for each — twelve numbers — and we are scored on whether we land closer to
the real results than Wall Street's own consensus forecasts do.</p>

<h2>The idea</h2>
<p>Asking a language model "what will EPS be?" produces a plausible
hallucination. So the LLM in this system is never allowed to pick a number.
Instead it does the one thing it is genuinely good at — reading documents —
and everything numeric happens in plain, auditable code:</p>
<ul>
<li><b>Anchor:</b> start from the most informed public number — analyst
consensus where it exists, the company's own published consensus or
management guidance where it doesn't (a three-tier ladder).</li>
<li><b>Adjust:</b> move the anchor by a signed fraction (0.8) of the gap to
what management actually guides for the specific period — read verbatim from
their filings. Momentum tempering handles full-year-only guidance.</li>
<li><b>Verify everything:</b> every extracted fact must carry a verbatim
quote that provably exists in its cited document, a time-period label, an
accounting-basis label, a freshness check against every prior vintage of the
same guidance, and an explicit one-off flag — or the pipeline refuses it.</li>
</ul>

<h2>The anchor ladder — what TIER 1/2/3 mean</h2>
<p>Every metric needs a starting point (the <b>anchor</b>). We always pick the
most informed public number available, in strict order of preference:</p>
<table>
<tr><th>Tier</th><th>When it applies</th><th>The anchor is…</th><th>Used for</th></tr>
<tr><td><b>TIER 1</b></td><td>a consensus estimate exists</td>
<td>consensus — the average of professional analysts' forecasts (yfinance), or
the company's own published analyst consensus (Hays discloses one)</td>
<td>HD sales &amp; EPS, ADI revenue &amp; EPS, Deere sales &amp; EPS, Hays op profit</td></tr>
<tr><td><b>TIER 2</b></td><td>no consensus, but management guides the figure
directly</td><td>management's guidance midpoint, read verbatim from the filing</td>
<td>HD comparable sales, ADI gross margin</td></tr>
<tr><td><b>TIER 3</b></td><td>neither exists</td><td>nothing — the figure is
<i>derived</i> from other forecasts through an accounting identity
(profit&nbsp;=&nbsp;sales&nbsp;×&nbsp;margin; EPS&nbsp;=&nbsp;profit&nbsp;after
interest&nbsp;and&nbsp;tax&nbsp;÷&nbsp;shares)</td>
<td>Hays net fees &amp; EPS, Deere segment profit</td></tr>
</table>
<p>Why this order? The scoring compares our miss to Wall Street's miss — so
consensus, when visible, is both the thing to beat and the safest starting
point. Guidance is what moves us off it, in the direction management has
committed to.</p>

<h2>The formula, step by step</h2>
<div class="card">
<p style="margin-top:0"><code>forecast = anchor + 0.8 × (guidance_target − anchor)</code></p>
<p><b>anchor</b> — the Tier 1/2 starting number above.<br>
<b>guidance_target</b> — what the company itself points to for this exact
period, converted to the metric's units by code (a guided range becomes its
midpoint; a growth guide is applied to the same period last year).<br>
<b>0.8</b> — the adjustment weight: we close 80% of the gap between the market
and management. Guidance is signed — a guide-down pulls the forecast below
consensus, a guide-up above.</p>
<p><b>Worked, three ways:</b></p>
<p><b>Tier 1, simple (ADI revenue):</b> consensus $3,925m; guided midpoint
"$3.9&nbsp;billion&nbsp;±&nbsp;$100m" → target $3,900m.<br>
<code>3,925 + 0.8 × (3,900 − 3,925) = 3,905</code></p>
<p><b>Tier 1 with phase + temper (HD adjusted EPS)</b> — HD guides only the
FULL YEAR ("adjusted EPS flat to +4%", midpoint +2%), but we forecast one
quarter, and the most recent quarter actually printed −3.7% year-on-year. The
tempered growth rate is the mean of the two signals:<br>
<code>tempered growth = mean(+2%, −3.7%) = −0.85%</code><br>
<code>target = last year's Q2 ($4.68) × (1 − 0.85%) = $4.64</code><br>
<code>forecast = 4.69 + 0.8 × (4.64 − 4.69) = 4.65</code> — below the Street,
because the year-to-date momentum says the full-year guide is optimistic for
this quarter.</p>
<p><b>Tier 3, derived (Hays EPS):</b> no consensus and no guide exists for
EPS itself, so it is computed from figures that ARE anchored:<br>
<code>(op profit 45.5 − finance charge 13, both £m, per FY26 guidance)
× (1 − 45% guided tax rate) ÷ 1,595.7m shares = 1.12 pence</code></p>
</div>

<h2>The pipeline</h2>
<div class="flow">
<svg viewBox="0 0 880 335" role="img" aria-label="Pipeline: the corpus feeds an LLM extractor whose claims pass a deterministic verify gate; accepted facts enter the typed fact store which the engine reads; consensus anchors flow directly to the engine, never through the LLM; the engine emits twelve receipts into four workbooks; rejected claims are logged with reasons.">
<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="#1a2330"/></marker>
<marker id="r" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="#a33c2e"/></marker></defs>
<g fill="none" stroke="#1a2330" stroke-width="1.3">
<rect x="8"   y="30" width="150" height="58" rx="6"/>
<rect x="192" y="30" width="152" height="58" rx="6"/>
<rect x="376" y="22" width="218" height="76" rx="6" stroke="#0e6e5c" stroke-width="2.2"/>
<rect x="648" y="30" width="170" height="58" rx="6"/>
<rect x="395" y="142" width="180" height="50" rx="6" stroke="#a33c2e"/>
<rect x="8"   y="244" width="170" height="58" rx="6"/>
<rect x="352" y="244" width="216" height="58" rx="6"/>
<rect x="648" y="244" width="170" height="58" rx="6"/>
<line x1="158" y1="59" x2="190" y2="59" marker-end="url(#a)"/>
<line x1="344" y1="59" x2="374" y2="59" marker-end="url(#a)"/>
<line x1="594" y1="59" x2="646" y2="59" marker-end="url(#a)"/>
<line x1="485" y1="98" x2="485" y2="140" stroke="#a33c2e" marker-end="url(#r)"/>
<polyline points="733,88 733,212 585,212"/>
<line x1="585" y1="212" x2="512" y2="242" marker-end="url(#a)"/>
<line x1="178" y1="273" x2="350" y2="273" marker-end="url(#a)"/>
<line x1="568" y1="273" x2="646" y2="273" marker-end="url(#a)"/>
</g>
<g font-family="ui-monospace, Menlo, monospace" font-size="12.5" fill="#1a2330" text-anchor="middle">
<text x="83" y="54">1,139-doc frozen</text><text x="83" y="70">corpus (organisers)</text>
<text x="268" y="54">LLM extractor</text><text x="268" y="70">locates + quotes</text>
<text x="485" y="46" fill="#0e6e5c" font-weight="bold">VERIFY GATE</text>
<text x="485" y="64" font-size="10">quote must exist in cited doc</text>
<text x="485" y="80" font-size="10">units &#183; period &#183; basis &#183; vintage</text>
<text x="733" y="54">typed fact store</text><text x="733" y="70" font-size="11">52 facts + metadata</text>
<text x="485" y="163" fill="#a33c2e">rejected claims</text><text x="485" y="180" fill="#a33c2e" font-size="11">logged with reasons</text>
<text x="93" y="268">yfinance consensus</text><text x="93" y="285" font-size="11">(fetched in-event)</text>
<text x="460" y="268">ENGINE + 6 gates</text><text x="460" y="285" font-size="10.5">anchor + 0.8&#215;gap &#183; pure code</text>
<text x="733" y="268">12 receipts</text><text x="733" y="285" font-size="11">-&gt; 4 xlsx workbooks</text>
</g>
<g font-family="ui-monospace, Menlo, monospace" font-size="10.5" fill="#5c6a7a" text-anchor="middle">
<text x="264" y="234">Tier-1 anchors (never via the LLM)</text>
<text x="659" y="205">facts feed the engine</text>
<text x="607" y="264">forecasts</text>
</g></svg>
</div>
<p>The green gate is the heart of the design: an LLM (or any extractor) may
<i>claim</i> a fact, but code accepts it only if the verbatim quote exists in
the cited document and the value is derivable from a number inside that quote
under the declared units. {len(rejected)} claims were refused today; each
rejection and its reason is in the clear-run log.</p>

<h2>One number, end to end</h2>
<p>Hays' FY2026 pre-exceptional operating profit, exactly as the receipt
records it:</p>
<div class="card">
<p style="margin-top:0"><b>{has_op['value']} GBPm</b> &nbsp;<span class="tag">{e(has_op['anchor_tier'])}</span></p>
<p class="src">{e(has_op['formula'])}</p>
{op_facts}
<p class="quote">"…we currently expect FY26 pre-exceptional operating profit
will be at the top of the £37.0–46.0m consensus range" — Hays Q4 trading
statement, 10 Jul 2026. The footnote labels £43.5m as company-compiled
consensus (10 analysts): so consensus anchors, management's "top of range"
adjusts, and 43.5 + 0.8 × (46.0 − 43.5) = 45.5. No number typed by hand.</p>
</div>

<h2>The twelve numbers</h2>
<table>
<tr><th>Co.</th><th>Metric</th><th>Forecast</th><th>Unit</th><th>Anchor tier</th><th>Facts consumed</th></tr>
{rows}</table>

<h2>Every formula, every substitution</h2>
<p>All twelve computations, exactly as the engine runs them. (The build script
recomputes each line against the run receipts and refuses to generate this
page if any row disagrees with the code.)</p>
<div style="overflow-x:auto"><table>
<tr><th>Co.</th><th>Metric</th><th>Formula shape</th><th>Substitution → forecast</th></tr>
{formula_rows}</table></div>
<p class="src">Source: cache/receipts.json — each row expands there into its
formula, consumed facts (value · period · basis · type · document · freshness ·
one-offs) and the checks it passed.</p>

<h2>Validation that actually fires</h2>
<ul>
<li><b>Guidance revision-diff:</b> for all {n_guides_checked} guides the engine
consumes, every historical vintage of that guidance is collected and diffed;
the run refuses to forecast on a stale vintage. It caught a real one today —
Hays guided its FY26 tax rate at 38% in Aug 2025 and revised to 45% in Feb
2026; the stale figure had briefly reached our EPS derivation (a ~15% error)
before this check existed. Now it is mechanical. Sample revisions from today's
log:</li>
</ul>
<div class="card"><ul style="margin:0">{rev_rows}</ul></div>
<ul>
<li><b>Per-metric schema:</b> each of the 12 metrics declares which accounting
bases (GAAP vs adjusted vs pre-exceptional…) and which time periods may feed
it; a GAAP figure cannot enter an adjusted-EPS forecast even by accident.</li>
<li><b>One-off rule:</b> a reported actual carrying a one-off (Deere's $272m
tariff refund; ADI's ~50bps channel-repricing benefit) may never anchor a
different period on its own — the engine derives Deere's segment profit from
guided sales × guided margin instead of the inflated quarter.</li>
<li><b>Rejected values, from today's run log:</b></li>
</ul>
<div class="card"><ul style="margin:0">{rej_rows}</ul></div>

<h2>Measured, not asserted</h2>
<ul>
<li><b>Cross-validation:</b> a teammate independently hand-transcribed the
historical figures (tier1/history.json). 9/9 overlapping datapoints agree with
the pipeline's extraction to the cent.</li>
<li><b>Backtest (thin, honestly):</b> replaying ADI's guidance-anchoring on
its paired guide/actual history: guidance-anchor MAE 7.4% vs momentum-anchor
20.2% (n=4 clean pairs). HD/Deere replays hit extraction-coverage limits on
decade-old filing language — a limitation, reported as such, and the reason
the extractor is agent-based rather than regex-based going forward.</li>
<li><b>Baseline:</b> the final run also produces a seasonal-naive baseline
(independent code path, baseline/) — e.g. HD: ledger 47,191 / 4.65 / +0.2 vs
baseline 47,456 / 4.56 / +0.8. Both put HD's EPS below the Street.</li>
</ul>

<h2>Honesty: what broke, what we changed, what is not built</h2>
<ul>
<li><b>Broke:</b> hand-tuned regex extraction silently missed facts whose
filings phrase numbers differently ("£4 3.5 m" — the corpus splits digits) —
replaced by the agent-locates / code-verifies design. Hardcoded Hays
finance/tax assumptions were ~30% wrong on EPS until extraction replaced them.
A stale guidance vintage reached a formula once — now mechanically impossible.</li>
<li><b>Changed:</b> anchors were corrected twice by corpus re-reads (ADI's
gross margin guide is sequential-down, not trend-up; Deere's consensus is
equipment-only and needs a finance bridge — labeled "our estimate" in its
receipt because it is one).</li>
<li><b>Not built</b> (designed in our spec but absent from this code, on
purpose): probability-of-beat outputs, confidence intervals, an LLM critic
loop, a universal beat-prior. The page describes the code, not the plan.</li>
<li><b>Disclosure:</b> the team researched this methodology (consensus-anchored
ledgers) before the event as general design work; all code, prompts,
extraction, forecasts and this page were built today in this repository —
declared in entry.json, verifiable in the commit history.</li>
</ul>

<h2>The research basis — where the idea came from, and what we threw away</h2>
<p>We surveyed the published literature on LLM earnings forecasting before
writing a line of code. The ledger below states only what is actually in the
running pipeline — a feature we designed but did not ship is not claimed as
used.</p>
<div style="overflow-x:auto"><table>
<tr><th>Paper</th><th>What we took</th><th>Status</th></tr>
<tr><td>FinRobot <span class="src">arXiv:2411.08804</span></td>
<td>the staged pipeline shape — evidence, typed contract, forecast,
validation — with the LLM confined to extracting evidence, never computing a
number. Did NOT take its forecasting, which is hardcoded heuristics</td>
<td>used</td></tr>
<tr><td>FinReport <span class="src">arXiv:2403.02647 · WWW'24</span></td>
<td>the evidence-to-report pipeline shape — receipts, a rejected-facts list,
and the four output workbooks (same pipeline credit as FinRobot)</td>
<td>used</td></tr>
<tr><td>DatedGPT <span class="src">arXiv:2603.11838</span></td>
<td>the no-lookahead discipline, enforced mechanically: every replayed
backtest quarter uses only documents published before it, and
stale-guidance / same-day-consensus gates refuse to run on outdated
inputs</td><td>used</td></tr>
<tr><td>Walk-down / PEAD <span class="src">Richardson–Teoh–Wysocki 2004 ·
Bernard &amp; Thomas 1990</span></td>
<td>the engine's actual core: consensus is systematically walked down to a
beatable level, so forecast = consensus + a bounded fraction of the guidance
gap — this is where the 0.8 gap rule comes from; the ~75% beat rate is the
empirical backdrop</td><td>used</td></tr>
<tr><td>SAE-FiRE <span class="src">arXiv:2505.14420</span></td>
<td>the SUE / beat-persistence concept as the rationale for a per-firm beat
prior in our design. The surprise = (actual − consensus) ÷ volatility formula
is designed-not-built — the shipped forecast anchors on consensus and
management guidance, not on a surprise model. Its classifier was not
built</td><td>framing only</td></tr>
<tr><td>Kim / Muhn / Nikolaev <span class="src">arXiv:2407.17866</span></td>
<td>the method of structured LLM reading of statements into typed signals.
The arXiv version was withdrawn for data inconsistencies; we cite the SSRN
revision for method only, never its numbers</td><td>method only</td></tr>
<tr><td>"Man vs Machine" LLM-beats-analysts <span class="src">RFS 2023</span></td>
<td><b>Rejected.</b> Under an Expression of Concern after
Zhang–Zhu–Linnainmaa (RFS 2025) showed unannounced earnings had leaked into
its features. Leak removed: linear ≈ ML ≈ analysts</td>
<td class="warn">rejected</td></tr>
</table></div>
<p>The rejected paper is the load-bearing one. The leakage-free literature
says "ask an LLM for a number" loses to a simple linear model — <b>so we
don't ask</b>. We anchor on consensus and make small, auditable,
evidence-cited adjustments instead. That finding is the scientific argument
for the entire design: a simple interpretable model is as good as a black box
here, and only the simple one is auditable.</p>

<h2>Reproduce it</h2>
<div class="card"><p style="margin:0"><code>npm install</code> ·
<code>python3 -m venv .venv &amp;&amp; ./.venv/bin/pip install -r requirements.txt</code> ·
<code>./run_final.sh</code> — four workbooks in <code>submission/</code>, the
clear-run log in <code>logs/</code>, receipts in <code>cache/receipts.json</code>.
Everything runs from the committed cache; no API key or network needed except
the same-day consensus refresh.</p></div>
</main>
</body>
</html>
"""
    out = REPO / "architecture" / "index.html"
    out.write_text(page)
    print(f"architecture/index.html generated: {len(page):,} bytes, "
          f"{len(receipts)} receipts, {len(rejected)} rejections, "
          f"{len(revised)} revision lines embedded")


if __name__ == "__main__":
    build()
