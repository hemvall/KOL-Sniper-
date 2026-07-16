from kol_sniper.config import Settings
from kol_sniper.domain import Fill, Opportunity, OrderStatus, Side
from kol_sniper.risk import RiskManager
from kol_sniper.storage import Store

from .conftest import MINT


def test_opportunity_dedup_is_durable(store) -> None:
    opportunity = Opportunity("channel", "42", MINT, f"CA: {MINT}")
    first_id, first_created = store.record_opportunity(opportunity)
    second_id, second_created = store.record_opportunity(opportunity)
    assert first_created is True
    assert second_created is False
    assert second_id == first_id


def test_existing_database_reopens_in_wal_mode(store) -> None:
    reopened = Store(store.path)
    with reopened.connection() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_duplicate_fill_does_not_double_position(store) -> None:
    order = store.create_order(MINT, "buy", 0.1)
    fill = Fill("sig-buy", MINT, Side.BUY, token_amount=100, sol_amount=0.1)
    store.record_fill(order, fill)
    store.record_fill(order, fill)
    assert store.get_position(MINT)["token_amount"] == 100


def test_partial_sell_updates_cost_and_realized_pnl(store) -> None:
    buy_order = store.create_order(MINT, "buy", 1)
    store.record_fill(buy_order, Fill("buy", MINT, Side.BUY, 100, 1.0))
    sell_order = store.create_order(MINT, "sell", 25, amount_in_tokens=True)
    store.record_fill(sell_order, Fill("sell", MINT, Side.SELL, 25, 0.5, fee_sol=0.01))
    position = store.get_position(MINT)
    assert position["token_amount"] == 75
    assert position["cost_sol"] == 0.75
    assert position["realized_pnl_sol"] == 0.24
    assert store.risk_snapshot()["daily_pnl_sol"] == 0.24


def test_risk_limits_include_reserved_orders(store, tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "state.db",
        max_pending_orders=1,
        max_open_positions=2,
        max_total_exposure_sol=0.2,
        max_transaction_transfer_sol=0.2,
    )
    risk = RiskManager(settings, store)
    assert risk.allow_buy(0.1).allowed
    store.create_order(MINT, "buy", 0.1)
    decision = risk.allow_buy(0.1)
    assert not decision.allowed
    assert "pending" in decision.reason


def test_atomic_buy_reservation_counts_pending_exposure(store) -> None:
    first, _ = store.record_opportunity(Opportunity("c", "1", MINT, MINT))
    other_mint = "HHi9GXkuBchA2LugrZvTLNhzoChAZFkvQNjeDagcpump"
    second, _ = store.record_opportunity(Opportunity("c", "2", other_mint, other_mint))
    limits = dict(
        slippage_bps=1_500,
        max_pending_orders=1,
        max_open_positions=4,
        max_total_exposure_sol=1.0,
        max_daily_loss_sol=0.25,
        mint_cooldown_seconds=60,
        execution_overhead_sol=0.005,
    )
    order_id, reason = store.reserve_buy(mint=MINT, amount_sol=0.1, opportunity_id=first, **limits)
    assert order_id and not reason
    rejected, reason = store.reserve_buy(mint=other_mint, amount_sol=0.1, opportunity_id=second, **limits)
    assert rejected is None
    assert "pending" in reason


def test_reentry_resets_entry_basis_and_exit_steps(store) -> None:
    first = store.create_order(MINT, "buy", 1)
    store.confirm_order(first, Fill("buy-1", MINT, Side.BUY, 100, 1.0))
    store.ensure_exit_steps(MINT, [(2, 0.5)])
    sell = store.create_order(MINT, "sell", 100, amount_in_tokens=True)
    store.confirm_order(sell, Fill("sell-all", MINT, Side.SELL, 100, 2.0))
    second = store.create_order(MINT, "buy", 0.25)
    store.confirm_order(second, Fill("buy-2", MINT, Side.BUY, 50, 0.25, fee_sol=0.001))
    position = store.get_position(MINT)
    assert position["token_amount"] == 50
    assert position["entry_token_amount"] == 50
    assert position["entry_cost_sol"] == 0.251
    assert store.exit_steps(MINT) == []


def test_unknown_exit_is_not_reserved_twice(store) -> None:
    buy = store.create_order(MINT, "buy", 1)
    store.confirm_order(buy, Fill("buy", MINT, Side.BUY, 100, 1.0))
    first = store.reserve_exit(mint=MINT, step_key="stop", target_multiple=0, fraction=1, token_amount=100)
    assert first
    store.update_order(first, OrderStatus.UNKNOWN, signature="sig")
    store.finish_exit_attempt(first, OrderStatus.UNKNOWN)
    assert (
        store.reserve_exit(mint=MINT, step_key="stop", target_multiple=0, fraction=1, token_amount=100)
        is None
    )
