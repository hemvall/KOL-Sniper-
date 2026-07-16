from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .config import Settings
from .domain import OrderStatus, Side
from .executor import TradeExecutor
from .storage import Store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExitStep:
    multiple: float
    fraction: float


def parse_exit_ladder(value: str) -> list[ExitStep]:
    steps: list[ExitStep] = []
    total = 0.0
    for raw in value.split(","):
        if not raw.strip():
            continue
        target_raw, fraction_raw = raw.split(":", 1)
        target = float(target_raw)
        fraction = float(fraction_raw)
        if target <= 1 or not (0 < fraction <= 1):
            raise ValueError("exit targets must be >1 and fractions must be in (0,1]")
        total += fraction
        steps.append(ExitStep(target, fraction))
    if not steps or total > 1.000001:
        raise ValueError("exit ladder must contain steps whose fractions total at most 1")
    return sorted(steps, key=lambda step: step.multiple)


def trade_price(event: dict[str, Any]) -> float | None:
    try:
        virtual_sol = float(event.get("vSolInBondingCurve", 0))
        virtual_tokens = float(event.get("vTokensInBondingCurve", 0))
        if virtual_sol > 0 and virtual_tokens > 0:
            return (virtual_sol / 1e9) / (virtual_tokens / 1e6)
        sol_amount = abs(float(event.get("solAmount", 0)))
        token_amount = abs(float(event.get("tokenAmount", 0)))
        return sol_amount / token_amount if sol_amount > 0 and token_amount > 0 else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


class PumpPriceHub:
    """One reconnecting PumpPortal socket shared by every open position."""

    def __init__(self, url: str = "wss://pumpportal.fun/api/data", stale_seconds: float = 20.0):
        self.url = url
        self.stale_seconds = stale_seconds
        self._queues: dict[str, set[asyncio.Queue[float]]] = {}
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def prices(self, mint: str) -> AsyncIterator[float]:
        queue: asyncio.Queue[float] = asyncio.Queue(maxsize=1)
        self._queues.setdefault(mint, set()).add(queue)
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._run(), name="pump-price-hub")
        self._changed.set()
        try:
            while True:
                yield await queue.get()
        finally:
            queues = self._queues.get(mint)
            if queues:
                queues.discard(queue)
                if not queues:
                    self._queues.pop(mint, None)
            self._changed.set()

    async def _run(self) -> None:
        import websockets

        backoff = 0.25
        while self._queues:
            try:
                async with websockets.connect(
                    self.url,
                    open_timeout=3,
                    ping_interval=10,
                    ping_timeout=5,
                    close_timeout=2,
                    max_queue=256,
                ) as socket:
                    backoff = 0.25
                    subscribed: set[str] = set()
                    while self._queues:
                        wanted = set(self._queues)
                        added = wanted - subscribed
                        removed = subscribed - wanted
                        if added:
                            await socket.send(
                                json.dumps({"method": "subscribeTokenTrade", "keys": sorted(added)})
                            )
                        if removed:
                            await socket.send(
                                json.dumps({"method": "unsubscribeTokenTrade", "keys": sorted(removed)})
                            )
                        subscribed = wanted
                        self._changed.clear()
                        receive = asyncio.create_task(socket.recv())
                        changed = asyncio.create_task(self._changed.wait())
                        done, pending = await asyncio.wait(
                            {receive, changed},
                            timeout=self.stale_seconds,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for task in pending:
                            task.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        if not done:
                            raise TimeoutError("shared price stream became stale")
                        if changed in done and changed.result():
                            if receive in done:
                                raw = receive.result()
                            else:
                                continue
                        else:
                            raw = receive.result()
                        event = json.loads(raw)
                        price = trade_price(event)
                        event_mint = str(event.get("mint") or "")
                        if not event_mint and len(subscribed) == 1:
                            event_mint = next(iter(subscribed))
                        if price is not None:
                            for target in self._queues.get(event_mint, set()):
                                if target.full():
                                    try:
                                        target.get_nowait()
                                    except asyncio.QueueEmpty:
                                        pass
                                target.put_nowait(price)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("shared price stream reconnect: %s", type(exc).__name__)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8.0)
        self._task = None

    async def close(self) -> None:
        task = self._task
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._task = None


# Compatibility name for existing integrations.
PumpPriceStream = PumpPriceHub


class ExitManager:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        executor: TradeExecutor,
        stream_factory: Callable[[], PumpPriceStream] | None = None,
    ):
        self.settings = settings
        self.store = store
        self.executor = executor
        self.steps = parse_exit_ladder(settings.exit_ladder)
        self.price_stream = (
            stream_factory or (lambda: PumpPriceHub(stale_seconds=settings.websocket_stale_seconds))
        )()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, mint: str) -> None:
        current = self._tasks.get(mint)
        if current and not current.done():
            return
        self._tasks[mint] = asyncio.create_task(self.monitor(mint), name=f"exit:{mint}")

    def recover(self) -> None:
        for position in self.store.open_positions():
            self.start(str(position["mint"]))

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        close = getattr(self.price_stream, "close", None)
        if close:
            await close()

    async def _sell(
        self,
        mint: str,
        token_amount: float,
        step_key: str,
        target_multiple: float,
        fraction: float,
    ) -> bool:
        if token_amount <= 0:
            return False
        order_id = await asyncio.to_thread(
            self.store.reserve_exit,
            mint=mint,
            step_key=step_key,
            target_multiple=target_multiple,
            fraction=fraction,
            token_amount=token_amount,
        )
        if not order_id:
            return False
        result = await asyncio.to_thread(
            self.executor.execute,
            mint=mint,
            side=Side.SELL,
            amount=token_amount,
            amount_in_tokens=True,
            precreated_order_id=order_id,
        )
        await asyncio.to_thread(self.store.finish_exit_attempt, result.order_id, result.status)
        return result.status is OrderStatus.CONFIRMED

    async def monitor(self, mint: str) -> None:
        position = self.store.get_position(mint)
        if not position:
            return
        entry_tokens = float(position["entry_token_amount"])
        cost_sol = float(position["entry_cost_sol"])
        if entry_tokens <= 0 or cost_sol <= 0:
            logger.error("cannot monitor malformed position %s", mint)
            return
        entry_price = cost_sol / entry_tokens
        peak_price = max(entry_price, float(position.get("peak_price_sol") or 0))
        self.store.ensure_exit_steps(mint, [(step.multiple, step.fraction) for step in self.steps])
        opened = time.time()
        try:
            opened = datetime.fromisoformat(str(position["opened_at"])).timestamp()
        except (TypeError, ValueError):
            pass

        price_iterator = self.price_stream.prices(mint).__aiter__()
        deadline = opened + self.settings.max_hold_seconds
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                current = self.store.get_position(mint)
                if not current or current["status"] != "open":
                    return
                await self._sell(mint, float(current["token_amount"]), "time", 0, 1)
                await asyncio.sleep(self.settings.reconcile_interval_seconds)
                continue
            price_task: asyncio.Future[float] = asyncio.ensure_future(anext(price_iterator))
            done, _ = await asyncio.wait({price_task}, timeout=remaining)
            if not done:
                price_task.cancel()
                await asyncio.gather(price_task, return_exceptions=True)
                deadline = time.time()
                continue
            try:
                price = price_task.result()
            except StopAsyncIteration:
                return
            current = self.store.get_position(mint)
            if not current or current["status"] != "open" or float(current["token_amount"]) <= 0:
                return
            if price > peak_price:
                peak_price = price
                await asyncio.to_thread(self.store.update_position_peak, mint, peak_price)
            stop_price = entry_price * (1 - self.settings.stop_loss_pct / 100)
            trailing_price = peak_price * (1 - self.settings.trailing_stop_pct / 100)
            if price <= stop_price or (peak_price > entry_price and price <= trailing_price):
                amount = float(current["token_amount"])
                if await self._sell(mint, amount, "stop", 0, 1):
                    return
                continue

            persisted = {row["step_key"]: row for row in self.store.exit_steps(mint)}
            for step in self.steps:
                key = f"{step.multiple:g}x"
                row = persisted.get(key)
                if price >= entry_price * step.multiple and row and row["status"] in {"pending", "failed"}:
                    amount = min(float(current["token_amount"]), entry_tokens * step.fraction)
                    if await self._sell(mint, amount, key, step.multiple, step.fraction):
                        current = self.store.get_position(mint) or current
