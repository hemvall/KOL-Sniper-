from __future__ import annotations

from dataclasses import replace

from kol_sniper.domain import Fill, OrderStatus, Side
from kol_sniper.runtime import create_runtime

from .conftest import MINT, WALLET
from .test_rpc import transaction_fixture


async def test_dry_run_signal_is_deduplicated(settings) -> None:
    runtime = create_runtime(settings)
    try:
        first = await runtime.service.handle_signal(
            source="channel", message_id="1", text=f"pump.fun/coin/{MINT}"
        )
        second = await runtime.service.handle_signal(
            source="channel", message_id="1", text=f"pump.fun/coin/{MINT}"
        )
        assert first is not None
        assert first.status is OrderStatus.DRY_RUN
        assert second is None
        assert runtime.store.risk_snapshot()["pending_orders"] == 0
    finally:
        await runtime.close()


async def test_non_mint_message_does_nothing(settings) -> None:
    runtime = create_runtime(settings)
    try:
        assert (
            await runtime.service.handle_signal(source="channel", message_id="2", text="hello world") is None
        )
        assert runtime.store.recent_orders() == []
    finally:
        await runtime.close()


async def test_dry_run_start_does_not_recover_live_exits(settings) -> None:
    runtime = create_runtime(settings)
    order = runtime.store.create_order(MINT, "buy", 0.1)
    runtime.store.confirm_order(order, Fill("sig", MINT, Side.BUY, 100, 0.1))
    try:
        await runtime.service.start()
        assert runtime.service.exits._tasks == {}
    finally:
        await runtime.close()


async def test_reconciliation_confirms_fill_atomically(settings) -> None:
    live = replace(settings, dry_run=False, private_key="unused")
    runtime = create_runtime(live)
    order = runtime.store.create_order(MINT, "buy", 0.1)
    runtime.store.update_order(order, OrderStatus.UNKNOWN, signature="sig")

    class Confirmation:
        def signature_status(self, signature):
            return {"confirmationStatus": "confirmed", "err": None}

        def transaction(self, signature):
            return transaction_fixture()

    runtime.service.executor.confirmation_client = Confirmation()  # type: ignore[assignment]
    runtime.service.executor._keypair = type("Key", (), {"pubkey": lambda self: WALLET})()
    try:
        await runtime.service.reconcile_pending()
        assert runtime.store.recent_orders(1)[0]["status"] == "confirmed"
        position = runtime.store.get_position(MINT)
        assert position is not None
        assert position["token_amount"] == 125
    finally:
        await runtime.close()
