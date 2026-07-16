from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .config import Settings
from .domain import ExecutionResult, Opportunity, OrderStatus, Side
from .errors import safe_error
from .executor import TradeExecutor
from .parser import extract_mint
from .risk import RiskManager
from .rpc import extract_fill
from .storage import Store
from .strategy import ExitManager

logger = logging.getLogger(__name__)
NotificationCallback = Callable[[str], Awaitable[None]]


class SniperService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        executor: TradeExecutor,
        risk: RiskManager,
        exits: ExitManager,
        notify: NotificationCallback | None = None,
    ):
        self.settings = settings
        self.store = store
        self.executor = executor
        self.risk = risk
        self.exits = exits
        self.notify = notify
        self._semaphore = asyncio.Semaphore(min(settings.signal_concurrency, settings.max_pending_orders))
        self._reconcile_task: asyncio.Task[None] | None = None
        self._metrics_task: asyncio.Task[None] | None = None
        self._metric_values: dict[str, float] = {}
        self._metric_deltas: defaultdict[str, float] = defaultdict(float)

    def _ensure_metrics_loop(self) -> None:
        if not self._metrics_task or self._metrics_task.done():
            self._metrics_task = asyncio.create_task(self._metrics_loop(), name="metrics-flush")

    def _set_metric(self, key: str, value: float) -> None:
        self._metric_values[key] = value
        self._ensure_metrics_loop()

    def _increment_metric(self, key: str, amount: float = 1.0) -> None:
        self._metric_deltas[key] += amount
        self._ensure_metrics_loop()

    async def _flush_metrics(self) -> None:
        if not self._metric_values and not self._metric_deltas:
            return
        values = self._metric_values
        deltas = dict(self._metric_deltas)
        self._metric_values = {}
        self._metric_deltas = defaultdict(float)
        try:
            await asyncio.to_thread(self.store.write_metrics, values, deltas)
        except Exception as exc:
            for key, value in values.items():
                self._metric_values.setdefault(key, value)
            for key, amount in deltas.items():
                self._metric_deltas[key] += amount
            logger.warning("metrics flush deferred: %s", type(exc).__name__)

    async def _metrics_loop(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            await self._flush_metrics()

    async def _notify(self, message: str) -> None:
        if not self.notify:
            return
        try:
            await self.notify(message)
        except Exception as exc:
            logger.error("notification failed: %s", type(exc).__name__)

    async def handle_signal(
        self,
        *,
        source: str,
        message_id: str,
        text: str,
        message_at: datetime | None = None,
    ) -> ExecutionResult | None:
        started = time.perf_counter()
        self._set_metric("last_signal_at", time.time())
        self._increment_metric("signals_total")
        mint = extract_mint(text)
        if not mint:
            self._increment_metric("signals_without_mint_total")
            return None
        self._increment_metric("signals_with_mint_total")
        opportunity = Opportunity(
            source=source,
            message_id=str(message_id),
            mint=mint,
            raw_message=text,
            message_at=message_at,
        )
        opportunity_id, created = await asyncio.to_thread(self.store.record_opportunity, opportunity)
        if not created:
            self._increment_metric("signals_duplicate_total")
            logger.info("duplicate signal ignored: %s/%s/%s", source, message_id, mint)
            return None

        decision = await asyncio.to_thread(
            self.risk.reserve_buy, mint, opportunity_id, self.settings.buy_amount_sol
        )
        if not decision.allowed or not decision.order_id:
            self._increment_metric("signals_rejected_total")
            await asyncio.to_thread(
                self.store.set_opportunity_status, opportunity_id, "rejected", decision.reason
            )
            await self._notify(f"Signal rejected {mint}: {decision.reason}")
            return None
        order_id = decision.order_id

        async with self._semaphore:
            result = await asyncio.to_thread(
                self.executor.execute,
                mint=mint,
                side=Side.BUY,
                amount=self.settings.buy_amount_sol,
                opportunity_id=opportunity_id,
                started_at_monotonic=started,
                precreated_order_id=order_id,
            )
        if result.status in {OrderStatus.CONFIRMED, OrderStatus.DRY_RUN}:
            opportunity_status = "executed"
        elif result.status in {OrderStatus.UNKNOWN, OrderStatus.CONFIRMED_UNPARSED}:
            opportunity_status = "pending"
        else:
            opportunity_status = "failed"
        await asyncio.to_thread(
            self.store.set_opportunity_status,
            opportunity_id,
            opportunity_status,
            result.error,
        )
        if result.status is OrderStatus.CONFIRMED:
            self.exits.start(mint)
        mode = "DRY RUN" if result.dry_run else result.status.value
        latency = f"{result.submit_latency_ms:.0f}ms" if result.submit_latency_ms is not None else "n/a"
        await self._notify(f"{mode} {mint} — submit latency {latency}")
        return result

    async def reconcile_pending(self) -> None:
        """Resolve submitted/unknown orders; never blindly resubmit after a restart."""
        if self.settings.dry_run:
            return
        for order in await asyncio.to_thread(self.store.pending_orders):
            signature = order.get("signature")
            if not signature:
                try:
                    created = datetime.fromisoformat(str(order["created_at"]))
                    age = (datetime.now(timezone.utc) - created).total_seconds()
                except (TypeError, ValueError):
                    age = 0
                if age >= max(30.0, self.settings.rpc_timeout_seconds * 3):
                    await asyncio.to_thread(
                        self.store.fail_order,
                        str(order["id"]),
                        "Interrupted: no signed transaction reached a submit route",
                    )
                continue
            try:
                status = await asyncio.to_thread(
                    self.executor.confirmation_client.signature_status, signature
                )
                if not status:
                    if order["status"] == OrderStatus.CONFIRMED_UNPARSED.value:
                        continue
                    last_valid_height = order["last_valid_block_height"]
                    if last_valid_height is not None:
                        current_height = await asyncio.to_thread(
                            self.executor.confirmation_client.block_height
                        )
                        expired = current_height > int(last_valid_height)
                    else:
                        try:
                            created = datetime.fromisoformat(str(order["created_at"]))
                            age = (datetime.now(timezone.utc) - created).total_seconds()
                        except (TypeError, ValueError):
                            age = 0
                        expired = age >= 180
                    if expired:
                        await asyncio.to_thread(
                            self.store.fail_order,
                            str(order["id"]),
                            "Expired: signature absent beyond blockhash validity window",
                        )
                    continue
                if status.get("err") is not None:
                    await asyncio.to_thread(
                        self.store.fail_order,
                        str(order["id"]),
                        "OnChainTransactionError: transaction failed on chain",
                    )
                    continue
                if status.get("confirmationStatus") in {"confirmed", "finalized"}:
                    transaction = await asyncio.to_thread(
                        self.executor.confirmation_client.transaction, signature
                    )
                    if transaction:
                        side = Side(str(order["side"]))
                        try:
                            fill = extract_fill(
                                transaction, signature, self.executor.wallet, str(order["mint"]), side
                            )
                            await asyncio.to_thread(self.store.confirm_order, str(order["id"]), fill)
                            if side is Side.BUY:
                                self.exits.start(str(order["mint"]))
                        except Exception as exc:
                            await asyncio.to_thread(
                                self.store.update_order,
                                str(order["id"]),
                                OrderStatus.CONFIRMED_UNPARSED,
                                error=safe_error(exc),
                            )
            except Exception as exc:
                logger.warning(
                    "pending-order reconciliation deferred for %s: %s",
                    order["id"],
                    type(exc).__name__,
                )

    async def _reconcile_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.reconcile_interval_seconds)
            await self.reconcile_pending()

    async def start(self) -> None:
        if self.settings.dry_run:
            return
        await asyncio.to_thread(self.executor.warmup)
        await self.reconcile_pending()
        self.exits.recover()
        if not self._reconcile_task or self._reconcile_task.done():
            self._reconcile_task = asyncio.create_task(self._reconcile_loop(), name="order-reconciler")

    async def stop(self) -> None:
        if self._reconcile_task:
            self._reconcile_task.cancel()
            await asyncio.gather(self._reconcile_task, return_exceptions=True)
            self._reconcile_task = None
        await self.exits.stop()
        if self._metrics_task:
            self._metrics_task.cancel()
            await asyncio.gather(self._metrics_task, return_exceptions=True)
            self._metrics_task = None
        await self._flush_metrics()
