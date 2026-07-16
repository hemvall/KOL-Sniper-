from __future__ import annotations

from typing import TypedDict

from .storage import Store


class PerformanceSnapshot(TypedDict):
    realized_pnl_sol: float
    gross_profit_sol: float
    gross_loss_sol: float
    profit_factor: float | None
    profitable_exit_rate: float | None
    max_realized_drawdown_sol: float
    exit_fills: int
    confirmed_buys: int
    total_chain_fees_sol: float


def performance_snapshot(store: Store) -> PerformanceSnapshot:
    """Aggregate only confirmed on-chain economics; no mark-to-market guesses."""
    with store.connection() as db:
        pnl_rows = [
            float(row["pnl_sol"])
            for row in db.execute("SELECT pnl_sol FROM pnl_events ORDER BY created_at, id")
        ]
        fee_row = db.execute("SELECT COALESCE(SUM(fee_sol),0) AS fees FROM fills").fetchone()
        buy_row = db.execute("SELECT COUNT(*) AS n FROM fills WHERE side='buy'").fetchone()
    gross_profit = sum(value for value in pnl_rows if value > 0)
    gross_loss = -sum(value for value in pnl_rows if value < 0)
    equity = peak = max_drawdown = 0.0
    for pnl in pnl_rows:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "realized_pnl_sol": sum(pnl_rows),
        "gross_profit_sol": gross_profit,
        "gross_loss_sol": gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "profitable_exit_rate": (sum(value > 0 for value in pnl_rows) / len(pnl_rows) if pnl_rows else None),
        "max_realized_drawdown_sol": max_drawdown,
        "exit_fills": len(pnl_rows),
        "confirmed_buys": int(buy_row["n"]),
        "total_chain_fees_sol": float(fee_row["fees"]),
    }
