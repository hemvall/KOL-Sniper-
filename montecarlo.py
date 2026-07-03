"""
Monte Carlo bankroll projection over N calls.

Modes:
  1) empirical  : bootstrap from real calls.csv (recommended with 30+ logged calls)
  2) parametric : model assumptions while waiting for more data

Common options:
  --start 3 --bet-frac 0.30 --horizons 5,10,20 --sims 50000 --ruin 1.0

Outputs: final balance percentiles, probability below starting capital, ruin probability,
median drawdown, and Kelly fraction for optimal geometric growth.
"""

import csv
import os
import argparse
import numpy as np


def empirical_returns(path):
    rets = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    rets.append(float(row["pnl_pct"]) / 100.0)
                except (ValueError, KeyError, TypeError):
                    pass
    return np.array(rets)


def make_draw(mode, rng, **kw):
    """Return a draw(size) function producing bet returns."""
    if mode == "empirical":
        r = kw["returns"]
        return lambda size: rng.choice(r, size=size, replace=True)
    outcomes = np.array([kw["win"], kw["loss"], kw["tail"]]) / 100.0
    p_loss = max(0.0, 1 - kw["p_win"] - kw["p_tail"])
    probs = np.array([kw["p_win"], p_loss, kw["p_tail"]])
    return lambda size: rng.choice(outcomes, size=size, p=probs), outcomes, probs


def simulate(start, n_calls, bet_frac, draw, sims, ruin):
    bal = np.full(sims, float(start))
    peak = bal.copy()
    mdd = np.zeros(sims)
    ever_ruin = np.zeros(sims, dtype=bool)
    for _ in range(n_calls):
        r = draw(sims)
        bal = bal * (1 + bet_frac * r)
        peak = np.maximum(peak, bal)
        mdd = np.maximum(mdd, 1 - bal / peak)
        ever_ruin |= bal <= ruin
    return bal, mdd, ever_ruin


def kelly(returns, probs):
    """Return the fraction f that maximizes E[ln(1 + f r)]."""
    returns = np.asarray(returns, dtype=float)
    worst = -returns.min()
    fmax = min(0.999, (1 / worst - 1e-6)) if worst > 0 else 0.999
    fs = np.linspace(0.001, max(fmax, 0.001), 5000)
    g = np.array([np.sum(probs * np.log(1 + f * returns)) for f in fs])
    i = int(np.argmax(g))
    return fs[i], g[i]


def pct(a, q):
    return np.percentile(a, q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--empirical", action="store_true")
    ap.add_argument("--csv", default=os.environ.get("CALLS_CSV", "calls.csv"))
    ap.add_argument("--start", type=float, default=3.0)
    ap.add_argument("--bet-frac", type=float, default=0.30)
    ap.add_argument("--horizons", default="5,10,20")
    ap.add_argument("--sims", type=int, default=50000)
    ap.add_argument("--ruin", type=float, default=1.0)
    # parametric assumptions
    ap.add_argument("--p-win", type=float, default=0.85)
    ap.add_argument("--win", type=float, default=50.0)
    ap.add_argument("--loss", type=float, default=-40.0)
    ap.add_argument("--p-tail", type=float, default=0.0)
    ap.add_argument("--tail", type=float, default=-90.0)
    args = ap.parse_args()

    rng = np.random.default_rng()
    horizons = [int(x) for x in args.horizons.split(",")]

    if args.empirical:
        rets = empirical_returns(args.csv)
        if len(rets) < 10:
            print(f"Only {len(rets)} logged calls — too few, wait until 30+. "
                  f"Use parametric mode in the meantime.")
            return
        draw = make_draw("empirical", rng, returns=rets)
        k_ret, k_prob = rets, np.full(len(rets), 1 / len(rets))
        ev = rets.mean()
        print(f"EMPIRICAL MODE — {len(rets)} real calls | avg return per bet {ev*100:+.1f}%")
    else:
        draw, outcomes, probs = make_draw(
            "param", rng, p_win=args.p_win, p_tail=args.p_tail,
            win=args.win, loss=args.loss, tail=args.tail)
        k_ret, k_prob = outcomes, probs
        ev = float(np.sum(probs * outcomes))
        p_loss = 1 - args.p_win - args.p_tail
        print(f"PARAMETRIC MODE | win {args.p_win*100:.0f}%@{args.win:+.0f}  "
              f"loss {p_loss*100:.0f}%@{args.loss:+.0f}  tail {args.p_tail*100:.0f}%@{args.tail:+.0f}")
        print(f"Avg return per bet {ev*100:+.1f}%")

    # Kelly and growth at the chosen bet size
    kf, kg = kelly(k_ret, k_prob)
    g_at_f = float(np.sum(k_prob * np.log(1 + args.bet_frac * np.asarray(k_ret, float))))
    print(f"\nSizing choisi : {args.bet_frac*100:.0f}% | croissance géom./call "
          f"{(np.exp(g_at_f)-1)*100:+.2f}%")
    print(f"Kelly optimal : {kf*100:.0f}% | à Kelly, croissance/call {(np.exp(kg)-1)*100:+.2f}%")
    ratio = args.bet_frac / kf if kf > 0 else float('inf')
    warn = ("  <- OVERBETTING (>2x Kelly: growth collapses)" if ratio > 2
            else "  <- above Kelly" if ratio > 1 else "")
    print(f"Ratio         : {ratio:.2f}x Kelly{warn}")

    # Distributions par horizon
    print(f"\nBankroll (départ {args.start} SOL, {args.sims:,} simulations)")
    print(f"{'calls':>6} | {'p5':>6} {'p25':>6} {'MÉDIANE':>8} {'moy':>6} {'p75':>7} {'p95':>7} "
          f"| {'<capital':>9} {'<'+str(args.ruin)+' SOL':>9} {'dd méd':>7}")
    print("-" * 82)
    for h in horizons:
        bal, mdd, ruin = simulate(args.start, h, args.bet_frac, draw, args.sims, args.ruin)
        print(f"{h:>6} | {pct(bal,5):>6.2f} {pct(bal,25):>6.2f} {pct(bal,50):>8.2f} "
              f"{bal.mean():>6.2f} {pct(bal,75):>7.2f} {pct(bal,95):>7.2f} | "
              f"{(bal<args.start).mean()*100:>8.1f}% {ruin.mean()*100:>8.1f}% "
              f"{np.median(mdd)*100:>6.0f}%")

    print("\nNote: MEDIAN = typical path. mean > median means good runs are pulling the average up. "
          "'<capital' = probability of finishing below the start.")


if __name__ == "__main__":
    main()
