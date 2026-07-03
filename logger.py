"""
Trade logger for recording snipes and tracking realized edge.

CLI:
  python logger.py add --mint <CA> --bet 0.3 --pnl 50
  python logger.py add --mint <CA> --bet 0.3 --entry 1.2e-7 --exit 1.9e-7 --ath 2.4e-7
  python logger.py list
  python logger.py stats

Usage from sniper.py:
  from logger import log_call
  log_call(mint=mint, bet_sol=BUY_SOL, entry=entry_price)
  log_call(mint=mint, bet_sol=BUY_SOL, entry=e, exit=x, ath=a)
"""

import os
import csv
import argparse
from datetime import datetime, timezone

CSV_PATH = os.environ.get("CALLS_CSV", "calls.csv")
FIELDS = ["ts", "mint", "channel", "bet_sol", "entry", "exit", "ath", "pnl_pct", "note"]

try:
    from colorama import init as _init_colorama, Fore, Style
    _init_colorama()
    GREEN = Fore.GREEN
    RED = Fore.RED
    RESET = Style.RESET_ALL
except ImportError:
    GREEN = "\033[32m"
    RED = "\033[31m"
    RESET = "\033[0m"


def _color_number(value):
    if value is None or value == "":
        return ""
    try:
        v = float(value)
    except (ValueError, TypeError):
        return str(value)
    text = f"{v:+.2f}%"
    return f"{GREEN}{text}{RESET}" if v >= 0 else f"{RED}{text}{RESET}"


def _read():
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))


def _write(rows):
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def log_call(mint, bet_sol, channel="", entry=None, exit=None, ath=None,
             pnl_pct=None, note=""):
    """Add a row or update the last open trade for the same mint."""
    if pnl_pct is None and entry and exit:
        pnl_pct = (float(exit) / float(entry) - 1.0) * 100.0
    rows = _read()
    # complete the last open trade for the same mint
    for r in reversed(rows):
        if r["mint"] == mint and not r["exit"] and (exit or pnl_pct is not None):
            if exit:
                r["exit"] = exit
            if ath:
                r["ath"] = ath
            if pnl_pct is not None:
                r["pnl_pct"] = round(pnl_pct, 2)
            if note:
                r["note"] = note
            _write(rows)
            return
    rows.append({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mint": mint, "channel": channel, "bet_sol": bet_sol,
        "entry": entry or "", "exit": exit or "", "ath": ath or "",
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else "", "note": note,
    })
    _write(rows)


def stats():
    rows = [r for r in _read() if r["pnl_pct"] not in ("", None)]
    if not rows:
        print("No closed trades yet (pnl_pct missing).")
        return
    pnls = [float(r["pnl_pct"]) for r in rows]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    tails = [p for p in pnls if p <= -70]           # rug / honeypot
    wr = len(wins) / n
    avg_w = sum(wins) / len(wins) if wins else 0
    avg_l = sum(losses) / len(losses) if losses else 0
    f = float(os.environ.get("BET_FRAC", "0.30"))
    import math
    # geometric growth per call for fixed bet fraction
    g = sum(math.log(max(1 + f * (p / 100), 1e-9)) for p in pnls) / n

    print(f"Trades closed    : {n}")
    print(f"Win rate         : {wr*100:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"Avg win          : {_color_number(avg_w)}   Avg loss      : {_color_number(avg_l)}")
    print(f"Rugs/Honeypots   : {len(tails)}  ({len(tails)/n*100:.1f}%)")
    print(f"Best / worst     : {_color_number(max(pnls))} / {_color_number(min(pnls))}")
    print(f"Growth/call      : {_color_number((math.exp(g)-1)*100)} (geom., bet {f*100:.0f}%)")
    print(f"                   {'>0 => compounding' if g>0 else '<0 => shrinking, review sizing/exit'}")
    print(f"\n-> feed these figures into montecarlo.py --empirical")


def show():
    rows = _read()
    if not rows:
        print("Empty.")
        return
    for r in rows:
        pnl = _color_number(r['pnl_pct'])
        print(f"{r['ts'][:16]}  {r['mint'][:8]:8}  bet={r['bet_sol']:>5}  "
              f"pnl={pnl:>11}  {r['note']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--mint", required=True)
    a.add_argument("--bet", required=True)
    a.add_argument("--channel", default="")
    a.add_argument("--entry", type=float)
    a.add_argument("--exit", type=float)
    a.add_argument("--ath", type=float)
    a.add_argument("--pnl", type=float, help="PnL percent of the bet (if no entry/exit provided)")
    a.add_argument("--note", default="")
    sub.add_parser("stats")
    sub.add_parser("list")
    args = ap.parse_args()

    if args.cmd == "add":
        log_call(mint=args.mint, bet_sol=args.bet, channel=args.channel,
                 entry=args.entry, exit=args.exit, ath=args.ath,
                 pnl_pct=args.pnl, note=args.note)
        print("OK")
    elif args.cmd == "stats":
        stats()
    elif args.cmd == "list":
        show()
