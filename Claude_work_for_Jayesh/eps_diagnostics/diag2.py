"""The hostile-judge question: does a dumb flat uplift beat the ledger on this sample?"""
from excalibur import backtest as B

ref = B.empirical_reference_std()
df = B.run(4, lam=0.8, reference_std=ref)

print("=== A. naive baselines on the SAME 40 firm-quarters ===")
print(f"{'model':38s} {'|err|':>8} {'vs cons':>8} {'wins':>7}")
print(f"{'consensus (the Street)':38s} {df.cons_err.sum():>8.4f} {'--':>8} {'--':>7}")
print(f"{'EXCALIBUR ledger (lam=0.8)':38s} {df.our_err.sum():>8.4f} "
      f"{df.our_err.sum()/df.cons_err.sum()-1:>7.1%} {int(df.win.sum()):>4}/40")
for up in [0.01, 0.02, 0.0276, 0.03, 0.04, 0.05, 0.07]:
    e = (df.consensus * (1 + up) - df.actual).abs()
    w = (e < df.cons_err).sum()
    print(f"{'flat uplift +' + format(up, '.2%'):38s} {e.sum():>8.4f} "
          f"{e.sum()/df.cons_err.sum()-1:>7.1%} {int(w):>4}/40")

print("\n=== B. the sample's beat regime ===")
srp = (df.actual / df.consensus - 1)
print(f"  quarters where actual BEAT consensus : {int((srp > 0).sum())}/40 "
      f"({(srp > 0).mean():.0%})  [brief's long-run base rate: 75-78%]")
print(f"  mean surprise {srp.mean():+.2%}, median {srp.median():+.2%}")
print("  -> an unusually hot sample; any positive constant wins here.")

print("\n=== C. where the ledger genuinely adds over a flat uplift ===")
best_flat = 0.04
flat_err = (df.consensus * (1 + best_flat) - df.actual).abs()
df2 = df.assign(flat_err=flat_err, beats_flat=df.our_err < flat_err)
per = df2.groupby("ticker").agg(ours=("our_err", "sum"), flat=("flat_err", "sum"),
                                beats_flat=("beats_flat", "sum"))
per["delta"] = per.ours - per.flat
print(per.sort_values("delta").to_string(float_format="%.4f"))
print(f"\n  ledger beats flat+4% in {int(df2.beats_flat.sum())}/40 quarters; "
      f"total {df2.our_err.sum():.4f} vs {flat_err.sum():.4f}")

print("\n=== D. interval sanity (engine centers on CONSENSUS, not our forecast) ===")
from excalibur.engine import interval_from_surprises
import json, pathlib
CACHE = pathlib.Path("cache")
for t in ["NVDA", "HD", "CRWD"]:
    c = json.loads((CACHE / "contracts" / f"{t}.json").read_text())
    lo, hi = interval_from_surprises(c["consensus_eps"], c["surprises"])
    print(f"  {t:5s} consensus={c['consensus_eps']:.3f} "
          f"interval=[{lo:.3f}, {hi:.3f}] centred on consensus "
          f"(NEXT_STEPS item 3 wanted it centred on our forecast)")
