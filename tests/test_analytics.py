import pytest

from kol_sniper.analytics import performance_snapshot
from kol_sniper.domain import Fill, Side

from .conftest import MINT


def test_performance_uses_confirmed_realized_fills(store) -> None:
    buy = store.create_order(MINT, "buy", 1)
    store.confirm_order(buy, Fill("buy", MINT, Side.BUY, 100, 1, fee_sol=0.01))
    sell = store.create_order(MINT, "sell", 50, amount_in_tokens=True)
    store.confirm_order(sell, Fill("sell", MINT, Side.SELL, 50, 0.75, fee_sol=0.01))
    report = performance_snapshot(store)
    assert report["confirmed_buys"] == 1
    assert report["realized_pnl_sol"] == pytest.approx(0.235)
    assert report["exit_fills"] == 1
    assert report["total_chain_fees_sol"] == pytest.approx(0.02)
