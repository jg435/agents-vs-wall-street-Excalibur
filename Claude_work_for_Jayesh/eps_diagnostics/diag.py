"""Read-only diagnostics on the Excalibur backtest. Writes nothing."""
import statistics
from excalibur import backtest as B
from excalibur import params as P
from excalibur.engine import forecast, row3_damp
from excalibur.universe import forecast_tickers, COMPS, SECTOR_BASKET

ref = B.empirical_reference_std()

print("=== 1. lambda sweep EXTENDED (is 0.8 an interior optimum?) ===")
print(f"{'lam':>5} {'our|err|':>9} {'wins/40':>8} {'vs cons':>8}")
for lam in [0.0, 0.4, 0.6, 0.8, 0.9, 1.0, 1.2]:
    df = B.run(4, lam=lam, reference_std=ref)
    print(f"{lam:>5} {df.our_err.sum():>9.4f} {int(df.win.sum()):>5}/{len(df)} "
          f"{df.our_err.sum()/df.cons_err.sum()-1:>7.1%}")

print("\n=== 2. headline claim provenance ===")
for lam, rs, label in [(0.6, 0.05, "params defaults (LAM=0.6, REF=0.05)"),
                       (0.8, ref, "shipped per NEXT_STEPS (lam=0.8, empirical ref)")]:
    df = B.run(4, lam=lam, reference_std=rs)
    print(f"  {label:48s} -> {int(df.win.sum())}/{len(df)}  "
          f"|err| {df.our_err.sum():.4f} vs {df.cons_err.sum():.4f} "
          f"({df.our_err.sum()/df.cons_err.sum()-1:+.1%})")

print("\n=== 3. which rows are actually alive in the replay? ===")
damp_fires = 0
total = 0
for t in forecast_tickers():
    qs = B.quarters(t)
    for date, est, act, _ in qs[-4:]:
        hist = [B.winsor(s) for d, _, _, s in qs if d < date][-8:]
        if len(hist) < 4:
            continue
        total += 1
        if row3_damp(None, hist[-1]) < 1.0:
            damp_fires += 1
print(f"  Row2 guidance gap : 0.0 in every quarter (guidance_midpoint=None)")
print(f"  Row4 buyback      : 0.0 in every quarter (shares_trend={{}})")
print(f"  Row5 evidence     : 0.0 in every quarter (qualitative_signal=0.0)")
print(f"  Row3 damp         : fires in {damp_fires}/{total} quarters (monster-beat branch only)")
print("  -> the -28% is attributable to Row 1 alone (+ the monster-beat damp).")

print("\n=== 4. does the reliability floor bind? ===")
binds = 0
vals = []
for t in forecast_tickers():
    qs = B.quarters(t)
    for date, est, act, _ in qs[-4:]:
        hist = [B.winsor(s) for d, _, _, s in qs if d < date][-8:]
        if len(hist) < 4:
            continue
        rel = max(P.RELIABILITY_FLOOR, 1.0 / (1.0 + statistics.stdev(hist) / ref))
        vals.append(rel)
        if rel <= P.RELIABILITY_FLOOR + 1e-9:
            binds += 1
print(f"  reliability range {min(vals):.2f}-{max(vals):.2f}, median {statistics.median(vals):.2f}")
print(f"  floor (0.25) binds in {binds}/{len(vals)} quarters")

print("\n=== 5. sector_med coverage per basket ===")
for t in forecast_tickers():
    b = SECTOR_BASKET[t]
    meds = []
    for p in COMPS[b]:
        ph = [B.winsor(s) for _, _, _, s in B.quarters(p)][-8:]
        if len(ph) >= 8:
            meds.append(statistics.median(ph))
    sm = statistics.median(meds) if meds else None
    print(f"  {t:5s} basket={b:17s} comps_used={len(meds):2d}/{len(COMPS[b]):2d} "
          f"sector_med={sm if sm is None else round(sm, 4)}")

print("\n=== 6. per-name direction: are we systematically long? ===")
df = B.run(4, lam=0.8, reference_std=ref)
df["bias"] = df.ours - df.consensus
df["cons_signed"] = df.actual - df.consensus
print(f"  our avg uplift vs consensus : {df.bias.mean()/df.consensus.mean():+.2%}")
print(f"  actual avg surprise         : {df.cons_signed.mean()/df.consensus.mean():+.2%}")
print(f"  quarters where actual MISSED consensus: "
      f"{int((df.cons_signed < 0).sum())}/{len(df)}")
losers = df[~df.win].groupby("ticker").size().sort_values(ascending=False)
print(f"  losses by name: {dict(losers)}")
