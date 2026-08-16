"""Live forecasts for the 10 names, exactly as app.py would render them."""
import json, pathlib
from excalibur.engine import forecast
from excalibur.universe import forecast_tickers

CACHE = pathlib.Path("cache")
print(f"{'tkr':5s} {'consens':>8} {'fcst':>8} {'A_tot':>7} {'damp':>5} "
      f"{'interval':>17} {'fcst in ivl?':>12} {'P(beat)':>7} {'flags'}")
for t in forecast_tickers():
    c = json.loads((CACHE / "contracts" / f"{t}.json").read_text())
    fc = forecast(c, lam=0.8, reference_std=0.0473)
    lo, hi = fc.interval
    inside = "yes" if lo <= fc.eps <= hi else "** NO **"
    flags = []
    if c["consensus_90d_ago"] is None:
        flags.append("no-90d")
    if c["n_quarters"] < 8:
        flags.append(f"{c['n_quarters']}q")
    if c["fiscal_label_mismatch"]:
        flags.append("FISCAL-MISMATCH")
    if not c.get("shares_trend"):
        flags.append("no-shares")
    print(f"{t:5s} {fc.consensus:>8.3f} {fc.eps:>8.3f} {fc.a_total:>+7.2%} "
          f"{fc.damp:>5.2f} [{lo:>7.3f},{hi:>7.3f}] {inside:>12} "
          f"{fc.p_beat:>6.0%}  {','.join(flags)}")

print("\nnext_period_end per name (fiscal-label check, Viktor checklist #6):")
for t in forecast_tickers():
    c = json.loads((CACHE / "contracts" / f"{t}.json").read_text())
    print(f"  {t:5s} next_period_end={c['next_period_end']}  "
          f"consensus={c['consensus_eps']}  eps_trend0q={c['consensus_eps_trend0q']}  "
          f"mismatch={c['fiscal_label_mismatch']}")

print("\nRow 4 buyback flag (steady_repurchaser) per name:")
from excalibur.engine import steady_repurchaser
for t in forecast_tickers():
    c = json.loads((CACHE / "contracts" / f"{t}.json").read_text())
    st = c.get("shares_trend") or {}
    vals = [v for _, v in sorted(st.items())]
    drift = (vals[-1] / vals[0]) ** (1 / max(len(vals) - 1, 1)) - 1 if len(vals) > 1 else None
    print(f"  {t:5s} flag={str(steady_repurchaser(st)):5s} n={len(vals)} "
          f"actual share drift/period={'n/a' if drift is None else format(drift, '+.2%')} "
          f"(engine credits +1.00% EPS if flag)")
