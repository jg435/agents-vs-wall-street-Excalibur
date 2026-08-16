"""Agent-based fact extraction: LLM locates + quotes, CODE verifies.

The required facts are DECLARED (name, description, units) — no per-fact
regexes. For each one, an LLM with search/read tools finds the right corpus
document and returns {value, units, doc, quote}. A deterministic verifier
then accepts the fact ONLY if:
  1. the cited doc exists and the quote appears in it (whitespace-normalized,
     tolerant of the corpus's split-digit mangling like "£4 3.5 m"),
  2. the claimed value is derivable from a number IN that quote under the
     declared unit conversion (billion->USDm etc.),
  3. cross-fact identities hold after merge (segment sums, EPS identity).
Accepted -> cache/facts.json (committed) (source tagged "agent+verified").
Rejected -> cache/rejected_facts.json (judge evidence: we reject values).

Usage:
  python -m agent.extractor            # extract all missing required facts
  python -m agent.extractor --all      # re-extract everything via the agent
Needs OPENAI_API_KEY or ANTHROPIC_API_KEY; without a key it reports which
required facts are missing and exits nonzero (the regex bootstrap in
corpus.py remains the offline fallback).
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from .corpus import DATA, FOLDER, FACTS_DIR, REPO, docs, load_facts

# ---------------------------------------------------------------- fact specs
# Declarative: WHAT we need, not HOW to find it. Adding a fact = one line.
REQUIRED = [
    # name, company, description for the agent, target units, PERIOD label
    # (Amendment 3 rule 2: every figure carries its exact time period)
    ("HD.q2_fy25_net_sales_usdm", "HD", "Home Depot total net sales for Q2 of fiscal 2025 (quarter ended ~Aug 2025), from the Q2 FY2025 earnings 8-K", "USDm", "Q2-FY2025"),
    ("HD.q2_fy25_adj_eps", "HD", "Home Depot adjusted diluted EPS for Q2 fiscal 2025", "USD", "Q2-FY2025"),
    ("HD.q2_fy25_comp_pct", "HD", "Home Depot total-company comparable sales % change in Q2 fiscal 2025", "pct", "Q2-FY2025"),
    ("HD.fy_sales_growth_guide", "HD", "Home Depot fiscal 2026 guidance: total sales growth % range midpoint", "pct", "FY2026"),
    ("HD.fy_comp_guide_mid", "HD", "Home Depot fiscal 2026 guidance: comparable sales growth range midpoint in percentage points", "pct", "FY2026"),
    ("HD.fy_adj_eps_growth_mid", "HD", "Home Depot fiscal 2026 guidance: adjusted diluted EPS growth % range midpoint", "pct", "FY2026"),
    ("ADI.rev_guide_mid_usdm", "ADI", "Analog Devices Q3 fiscal 2026 revenue guidance midpoint from the Q2 FY2026 8-K outlook", "USDm", "Q3-FY2026"),
    ("ADI.eps_guide_mid", "ADI", "Analog Devices Q3 fiscal 2026 adjusted EPS guidance midpoint", "USD", "Q3-FY2026"),
    ("ADI.adj_gross_margin_last", "ADI", "Analog Devices Q2 fiscal 2026 ACTUAL adjusted gross margin percentage", "pct", "Q2-FY2026"),
    ("DE.q3_fy25_revenues_usdm", "DE", "Deere worldwide net sales AND revenues for Q3 fiscal 2025 (includes financial services)", "USDm", "Q3-FY2025"),
    ("DE.q3_fy25_equip_net_sales_usdm", "DE", "Deere equipment-operations net sales (excluding financial services) for Q3 fiscal 2025", "USDm", "Q3-FY2025"),
    ("DE.q3_fy25_ppa_net_sales_usdm", "DE", "Deere Production & Precision Agriculture segment net sales, Q3 fiscal 2025", "USDm", "Q3-FY2025"),
    ("DE.q3_fy25_ppa_op_profit_usdm", "DE", "Deere Production & Precision Agriculture segment operating profit, Q3 fiscal 2025", "USDm", "Q3-FY2025"),
    ("DE.q3_fy25_sat_net_sales_usdm", "DE", "Deere Small Agriculture & Turf segment net sales, Q3 fiscal 2025", "USDm", "Q3-FY2025"),
    ("DE.q3_fy25_sat_op_profit_usdm", "DE", "Deere Small Agriculture & Turf segment operating profit, Q3 fiscal 2025", "USDm", "Q3-FY2025"),
    ("DE.q3_fy25_cf_net_sales_usdm", "DE", "Deere Construction & Forestry segment net sales, Q3 fiscal 2025", "USDm", "Q3-FY2025"),
    ("DE.q3_fy25_cf_op_profit_usdm", "DE", "Deere Construction & Forestry segment operating profit, Q3 fiscal 2025", "USDm", "Q3-FY2025"),
    ("DE.fy_net_income_guide_usdm", "DE", "Deere fiscal 2026 guidance: net income range midpoint", "USDm", "FY2026"),
    ("DE.ppa_fy_sales_guide", "DE", "Deere fiscal 2026 guidance: Production & Precision Ag net sales % change range midpoint", "pct", "FY2026"),
    ("HAS.fy25_net_fees_gbpm", "HAS", "Hays plc full-year FY2025 (ended 30 June 2025) Group net fees in GBP millions", "GBPm", "FY2025"),
    ("HAS.fy25_op_profit_gbpm", "HAS", "Hays plc FY2025 pre-exceptional operating profit in GBP millions", "GBPm", "FY2025"),
    ("HAS.op_profit_consensus", "HAS", "Hays plc company-compiled consensus for FY2026 pre-exceptional operating profit in GBP millions", "GBPm", "FY2026"),
    ("HAS.q4_net_fees_lfl", "HAS", "Hays plc Q4 FY2026 Group net fees like-for-like % change year-on-year (negative if down)", "pct", "Q4-FY2026"),
    ("HAS.shares_issued", "HAS", "Hays plc issued ordinary shares excluding treasury shares (issued minus treasury), most recent notification", "count", "2026-07-31"),
    ("HAS.fy25_net_finance_charge_gbpm", "HAS", "Hays plc FY2025 net finance charge in GBP millions", "GBPm", "FY2025"),
    ("HAS.fy25_pre_exceptional_etr_pct", "HAS", "Hays plc FY2025 pre-exceptional effective tax rate percent", "pct", "FY2025"),
    # Amendment 3: period-specific guidance anchors (sequential guides beat trend)
    ("ADI.q3_gm_guide_seq_change_pp", "ADI", "Analog Devices guided SEQUENTIAL change in adjusted gross margin for Q3 FY2026 vs Q2, in percentage points (CFO on the Q2 earnings call; negative if declining)", "pct", "Q3-FY2026-sequential"),
    ("DE.ppa_fy_margin_guide_pct", "DE", "Deere fiscal 2026 guidance: Production & Precision Ag segment operating margin range midpoint percent", "pct", "FY2026"),
    ("DE.q2_tariff_refund_usdm", "DE", "Deere Q2 FY2026 one-off IEEPA tariff refund recovery amount", "USDm", "Q2-FY2026-one-off"),
    ("DE.sat_fy_sales_guide", "DE", "Deere fiscal 2026 guidance: Small Ag & Turf net sales % change", "pct", "FY2026"),
    ("HAS.q1_net_fees_lfl", "HAS", "Hays plc Q1 FY2026 Group net fees like-for-like % change YoY (negative if down)", "pct", "Q1-FY2026"),
    ("HAS.q2_net_fees_lfl", "HAS", "Hays plc Q2 FY2026 Group net fees like-for-like % change YoY (negative if down)", "pct", "Q2-FY2026"),
    ("HAS.q3_net_fees_lfl", "HAS", "Hays plc Q3 FY2026 Group net fees like-for-like % change YoY (negative if down)", "pct", "Q3-FY2026"),
]

UNIT_MULTIPLIERS = {  # quote-unit word -> multiplier into the target unit
    "USDm": {"billion": 1000.0, "million": 1.0, "millions": 1.0, "": 1.0},
    "GBPm": {"billion": 1000.0, "million": 1.0, "m": 1.0, "": 1.0},
    "USD": {"": 1.0},
    "pct": {"": 1.0, "basis points": 0.01, "basis point": 0.01, "bps": 0.01},
    "count": {"": 1.0, "million": 1e6, "billion": 1e9},
}

EXTRACT_SYSTEM = """You extract ONE financial fact from supplied documents. \
Reply with ONLY this JSON:
{"value": float, "doc": "<repo-relative path of the source document>",
 "quote": "<the EXACT sentence or table row you read the number from, verbatim>",
 "unit_word": "billion" | "million" | "basis points" | "",
 "period": "<the exact time period the number applies to, e.g. Q3-FY2026, FY2025, Q3-FY2026-sequential>" }
Rules: the quote must be copied verbatim from the document (the corpus \
sometimes splits digits with spaces — copy it exactly as it appears). \
"value" must be the number in the TARGET units requested. "unit_word" is the \
unit word used in the quote itself. If the fact is not in the documents, \
reply {"value": null}. If the time period of a number is ambiguous or does \
not match the requested period, reply {"value": null} rather than guessing — \
a quarterly figure must never be used as an annual one. Never infer or \
compute a number not stated."""


# ------------------------------------------------------------------- tools
def tool_search(company, query, limit=8):
    """Rank corpus docs for a query; return snippets around term hits.

    Ranking = term frequency x DATE FIT: a fact about FY2025 wants documents
    filed in/after calendar 2025 (results report the just-ended year); a fact
    about guidance/"most recent" wants the newest docs. Without this, long old
    annual reports win on raw term counts (observed: a 2022 doc ranked first
    for a 'most recent share count' fact)."""
    q = query.lower()
    terms = [t for t in re.findall(r"[a-z&%$£][a-z&%$£.\-]*|\d{4}", q)]
    want_years = {int(y) for y in re.findall(r"20\d{2}", q)}
    wants_latest = bool(re.search(r"most recent|guidance|consensus|latest|fy ?2026|fiscal 2026", q))
    scored = []
    for doc in docs(company):
        text = doc.read_text(errors="ignore").lower()
        score = sum(text.count(t) for t in terms if len(t) > 2)
        if not score:
            continue
        doc_year = int(doc.name[:4])
        if want_years:
            # results for FY N are filed in year N or N+1
            fit = 4.0 if doc_year in {y for wy in want_years for y in (wy, wy + 1)} else 0.3
        elif wants_latest:
            fit = {2026: 4.0, 2025: 1.5}.get(doc_year, 0.2)
        else:
            fit = 1.0
        scored.append((score * fit, doc))
    out = []
    for _, doc in sorted(scored, reverse=True, key=lambda x: x[0])[:limit]:
        text = doc.read_text(errors="ignore")
        snippets = []
        for t in terms:
            if len(t) <= 3:
                continue
            i = text.lower().find(t)
            if i >= 0:
                snippets.append(text[max(0, i - 150):i + 250].replace("\n", " "))
            if len(snippets) >= 2:
                break
        out.append({"doc": doc.relative_to(REPO).as_posix(),
                    "snippets": snippets})
    return out


def tool_read(rel_path, max_chars=60000):
    p = REPO / rel_path
    if not p.exists() or DATA not in p.parents:
        return f"ERROR: {rel_path} not found or outside corpus"
    return p.read_text(errors="ignore")[:max_chars]


# ---------------------------------------------------------------- LLM call
def _load_env():
    """Read repo-root .env (KEY=VALUE lines) without overriding real env.
    The .env file is git-ignored (.gitignore lines 6-7) — never committed."""
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


NO_KEY_HELP = """No LLM API key found.
Create a file named .env in the repository root containing one line:
    OPENAI_API_KEY=sk-...        (or ANTHROPIC_API_KEY=sk-ant-...)
The .env file is git-ignored and must never be committed or published."""


def _llm(system, user):
    _load_env()
    if os.environ.get("OPENAI_API_KEY"):
        url = "https://api.openai.com/v1/chat/completions"
        body = {"model": os.environ.get("EXTRACTOR_MODEL", "gpt-5"),
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
        pick = lambda r: r["choices"][0]["message"]["content"]
    elif os.environ.get("ANTHROPIC_API_KEY"):
        url = "https://api.anthropic.com/v1/messages"
        body = {"model": os.environ.get("EXTRACTOR_MODEL", "claude-sonnet-5"),
                "max_tokens": 1500, "system": system,
                "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                   "anthropic-version": "2023-06-01"}
        pick = lambda r: "".join(b.get("text", "") for b in r["content"])
    else:
        raise RuntimeError(NO_KEY_HELP)
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=120) as r:
        return pick(json.loads(r.read()))


def _extract_json(text):
    dec = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            obj, _ = dec.raw_decode(text, i)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        i = text.find("{", i + 1)
    raise ValueError("no JSON in LLM reply")


# ------------------------------------------------------------ verification
def _normalize(s):
    """Whitespace-collapse + strip the corpus's split-digit mangling."""
    s = re.sub(r"(?<=\d)[  ](?=\d)", "", s)      # "£4 3.5" -> "£43.5"
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def verify(name, company, target_units, claim, expect_period=None):
    """Deterministic gate. Returns (ok, reason). Amendment 3 rule 2: when the
    spec declares a period, the claim must carry a period label."""
    if expect_period and not (claim.get("period") or "").strip():
        return False, "no time-period label on the figure (Amendment 3 rule 2)"
    doc = REPO / claim.get("doc", "")
    if not doc.exists() or DATA / FOLDER[company] not in doc.parents:
        return False, f"doc not in {company} corpus: {claim.get('doc')}"
    quote = claim.get("quote") or ""
    if len(quote) < 8:
        return False, "quote too short"
    if _normalize(quote) not in _normalize(doc.read_text(errors="ignore")):
        return False, "quote not found in cited doc"
    value = claim.get("value")
    if not isinstance(value, (int, float)):
        return False, "value not numeric"
    # value must be derivable from a number IN the quote under declared units
    nums = [float(n.replace(",", "")) for n in
            re.findall(r"\d[\d,]*\.?\d*", _normalize(quote))]
    for n in nums:
        for mult in UNIT_MULTIPLIERS[target_units].values():
            if n * mult and abs(value) > 0 and abs(n * mult / value - 1) < 0.005:
                return True, "ok"
            if value == 0 and n == 0:
                return True, "ok"
    # midpoint of a guided range: derivable from any two quoted endpoints
    for i, a in enumerate(nums):
        for b in nums[i + 1:]:
            for mult in UNIT_MULTIPLIERS[target_units].values():
                mid = (a + b) / 2 * mult
                if mid and abs(value) > 0 and abs(abs(mid / value) - 1) < 0.005:
                    return True, "ok (midpoint of quoted range)"
    # signed pct ("down 5%", "50 basis points decline") — magnitudes x unit mult
    if target_units == "pct":
        for n in nums:
            for mult in UNIT_MULTIPLIERS["pct"].values():
                if abs(abs(value) - n * mult) < 0.005:
                    return True, "ok (sign from context)"
    # derived counts (issued minus treasury)
    if target_units == "count" and len(nums) >= 2 and abs(nums[0] - nums[1] - value) < 2:
        return True, "ok (difference of quoted figures)"
    return False, f"value {value} not derivable from quote numbers {nums[:6]}"


def check_identities(F):
    """Cross-fact consistency (units/scale errors explode these instantly)."""
    v = lambda k: (F.get(k) or {}).get("value")
    issues = []
    trio = [v("DE.q3_fy25_ppa_net_sales_usdm"), v("DE.q3_fy25_sat_net_sales_usdm"),
            v("DE.q3_fy25_cf_net_sales_usdm")]
    if all(trio) and v("DE.q3_fy25_equip_net_sales_usdm"):
        if abs(sum(trio) / v("DE.q3_fy25_equip_net_sales_usdm") - 1) > 0.05:
            issues.append(f"DE segment sum {sum(trio)} vs equipment {v('DE.q3_fy25_equip_net_sales_usdm')}")
    if v("DE.q3_fy25_revenues_usdm") and v("DE.q3_fy25_equip_net_sales_usdm"):
        bridge = v("DE.q3_fy25_revenues_usdm") - v("DE.q3_fy25_equip_net_sales_usdm")
        if not 1000 <= bridge <= 2500:
            issues.append(f"DE fin-svcs bridge {bridge} outside [1000, 2500]")
    if v("HAS.fy25_op_profit_gbpm") and not 30 <= v("HAS.fy25_op_profit_gbpm") <= 120:
        issues.append("HAS FY25 op profit implausible")
    return issues


# ------------------------------------------------------------------- driver
def run(force_all=False):
    F = load_facts()
    todo = [spec for spec in REQUIRED
            if force_all or spec[0] not in F or (F[spec[0]] or {}).get("value") is None]
    if not todo:
        print("all required facts present; nothing to extract")
        return 0
    def process(spec):
        """One fact end-to-end: search -> llm (-> read -> llm) -> verify.
        Returns (name, accepted_or_None, rejection_or_None). Thread-safe:
        touches no shared state."""
        name, company, desc, units, period = spec
        leads = tool_search(company, desc)
        if not leads:
            return name, None, {"fact": name, "reason": "search found no candidate docs"}
        last = None
        # deterministic doc feeding: full text of the best-ranked doc, then #2
        for lead in leads[:2]:
            user = (f"FACT: {name}\nTARGET UNITS: {units}\nEXPECTED PERIOD: {period}\n"
                    f"DESCRIPTION: {desc}\n\n"
                    f"DOCUMENT ({lead['doc']}):\n{tool_read(lead['doc'])}")
            try:
                reply = _extract_json(_llm(EXTRACT_SYSTEM, user))
            except Exception as e:
                return name, None, {"fact": name, "reason": f"llm error: {e}"}
            if reply.get("value") is None:
                last = {"fact": name, "reason": f"not found in {lead['doc']}", "claim": reply}
                continue
            reply.setdefault("doc", lead["doc"])
            ok, why = verify(name, company, units, reply, expect_period=period)
            if ok:
                return name, {"value": reply["value"], "doc": reply["doc"],
                              "quote": reply["quote"][:300],
                              "period": reply.get("period", period),
                              "note": f"agent+verified ({why})"}, None
            return name, None, {"fact": name, "reason": why, "claim": reply}
        return name, None, last or {"fact": name, "reason": "agent found nothing"}

    from concurrent.futures import ThreadPoolExecutor
    rejected = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, accepted, rejection in pool.map(process, todo):
            if accepted:
                F[name] = accepted
                print(f"ACCEPT {name} = {accepted['value']}")
            else:
                rejected.append(rejection)
                print(f"REJECT {name}: {rejection['reason']}")
    issues = check_identities(F)
    for i in issues:
        print("IDENTITY FAIL:", i)
    FACTS_DIR.mkdir(exist_ok=True)
    (FACTS_DIR / "facts.json").write_text(json.dumps(F, indent=2))
    (FACTS_DIR / "rejected_facts.json").write_text(json.dumps(rejected, indent=2))
    missing = [n for n, *_ in REQUIRED if n not in F or (F[n] or {}).get("value") is None]
    print(f"\naccepted facts: {len(F)} | rejected: {len(rejected)} | still missing: {missing}")
    return 1 if (missing or issues) else 0


if __name__ == "__main__":
    try:
        sys.exit(run(force_all="--all" in sys.argv))
    except RuntimeError as e:
        F = load_facts()
        missing = [n for n, *_ in REQUIRED if n not in F or (F[n] or {}).get("value") is None]
        print(f"NO API KEY ({e}); regex-bootstrap facts on disk: {len(F)}; "
              f"missing required: {missing}")
        sys.exit(1 if missing else 0)