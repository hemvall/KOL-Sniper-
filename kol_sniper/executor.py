from __future__ import annotations

import logging
import threading
import time

from .config import Settings
from .domain import BuildRequest, ExecutionResult, OrderStatus, Side
from .errors import safe_error
from .rpc import (
    OnChainTransactionError,
    RpcClient,
    TransactionSubmitter,
    extract_fill,
    wait_for_confirmation,
)
from .storage import Store
from .transactions import TransactionBuilder, decode_transaction, load_keypair, sign_transaction
from .validation import TradeIntent, TransactionValidator

logger = logging.getLogger(__name__)


class TradeExecutor:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        builder: TransactionBuilder,
        validator: TransactionValidator,
        confirmation_client: RpcClient,
        submitter: TransactionSubmitter,
    ):
        self.settings = settings
        self.store = store
        self.builder = builder
        self.validator = validator
        self.confirmation_client = confirmation_client
        self.submitter = submitter
        self._keypair = None
        self._active = 0
        self._active_condition = threading.Condition()

    @property
    def keypair(self):
        if self._keypair is None:
            if not self.settings.private_key:
                raise RuntimeError("PRIVATE_KEY is required for live execution")
            self._keypair = load_keypair(self.settings.private_key)
        return self._keypair

    @property
    def wallet(self) -> str:
        if self.settings.dry_run and not self.settings.private_key:
            return "11111111111111111111111111111111"
        return str(self.keypair.pubkey())

    def warmup(self) -> None:
        self.builder.warm()
        self.store.set_metric("rpc_ping_ms", self.confirmation_client.ping())

    def close(self) -> None:
        deadline = (
            time.monotonic()
            + self.settings.confirm_timeout_seconds
            + 3 * self.settings.rpc_timeout_seconds
            + 20
        )
        with self._active_condition:
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.error("timed out waiting for %d in-flight trade(s) during shutdown", self._active)
                    break
                self._active_condition.wait(remaining)
        self.submitter.close()

    def execute(
        self,
        *,
        mint: str,
        side: Side,
        amount: float,
        opportunity_id: int | None = None,
        amount_in_tokens: bool = False,
        started_at_monotonic: float | None = None,
        precreated_order_id: str | None = None,
    ) -> ExecutionResult:
        with self._active_condition:
            self._active += 1
        try:
            return self._execute(
                mint=mint,
                side=side,
                amount=amount,
                opportunity_id=opportunity_id,
                amount_in_tokens=amount_in_tokens,
                started_at_monotonic=started_at_monotonic,
                precreated_order_id=precreated_order_id,
            )
        finally:
            with self._active_condition:
                self._active -= 1
                self._active_condition.notify_all()

    def _execute(
        self,
        *,
        mint: str,
        side: Side,
        amount: float,
        opportunity_id: int | None = None,
        amount_in_tokens: bool = False,
        started_at_monotonic: float | None = None,
        precreated_order_id: str | None = None,
    ) -> ExecutionResult:
        started = started_at_monotonic or time.perf_counter()
        order_id = precreated_order_id or self.store.create_order(
            mint, side.value, amount, opportunity_id=opportunity_id, amount_in_tokens=amount_in_tokens
        )
        self.store.increment_metric("orders_total")
        if self.settings.dry_run:
            self.store.update_order(order_id, OrderStatus.DRY_RUN, builder="dry-run")
            self.store.increment_metric("orders_dry_run_total")
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.DRY_RUN,
                latency_ms=(time.perf_counter() - started) * 1_000,
                dry_run=True,
            )
        local_signature: str | None = None
        broadcast_attempted = False
        try:
            request = BuildRequest(
                side=side,
                mint=mint,
                wallet=self.wallet,
                amount=amount,
                amount_in_tokens=amount_in_tokens,
                slippage_bps=self.settings.slippage_bps,
                priority_fee_sol=self.settings.priority_fee_sol,
                tip_sol=self.settings.sender_tip_sol if self.settings.helius_sender_url else 0.0,
                tip_account=self.settings.helius_tip_account,
            )
            built = self.builder.build(request)
            transaction = decode_transaction(built.encoded, built.encoding)
            validated = self.validator.validate(
                transaction,
                TradeIntent(
                    wallet=self.wallet,
                    mint=mint,
                    side=side,
                    amount=amount,
                    slippage_bps=self.settings.slippage_bps,
                    priority_fee_sol=self.settings.priority_fee_sol,
                    tip_sol=request.tip_sol,
                    tip_account=request.tip_account,
                ),
            )
            encoded, local_signature = sign_transaction(validated.transaction, self.keypair)
            last_valid_height = built.metadata.get("lastValidBlockHeight")
            self.store.update_order(
                order_id,
                OrderStatus.SIGNED,
                builder=built.builder,
                signature=local_signature,
                last_valid_block_height=(int(last_valid_height) if last_valid_height is not None else None),
            )
            # Once bytes reach any route, a transport error is ambiguous. Never
            # classify it as safe-to-retry until reconciliation proves expiry.
            broadcast_attempted = True
            signature = self.submitter.submit(encoded)
            if signature != local_signature:
                raise RuntimeError(
                    "submit route returned a signature that does not match the signed transaction"
                )
            self.store.update_order(order_id, OrderStatus.SUBMITTED, signature=signature)
            submit_latency = (time.perf_counter() - started) * 1_000
            self.store.set_metric("last_submit_latency_ms", submit_latency)
            chain_transaction = wait_for_confirmation(
                self.confirmation_client, signature, self.settings.confirm_timeout_seconds
            )
            try:
                fill = extract_fill(chain_transaction, signature, self.wallet, mint, side)
                self.store.confirm_order(order_id, fill)
            except Exception as exc:
                error = safe_error(exc)
                self.store.update_order(order_id, OrderStatus.CONFIRMED_UNPARSED, error=error)
                self.store.increment_metric("orders_confirmed_unparsed_total")
                logger.error("confirmed fill parsing failed for %s: %s", mint, type(exc).__name__)
                return ExecutionResult(
                    order_id=order_id,
                    status=OrderStatus.CONFIRMED_UNPARSED,
                    signature=signature,
                    latency_ms=(time.perf_counter() - started) * 1_000,
                    submit_latency_ms=submit_latency,
                    error=error,
                )
            self.store.increment_metric("orders_confirmed_total")
            latency = (time.perf_counter() - started) * 1_000
            self.store.set_metric("last_trade_latency_ms", latency)
            self.store.set_metric("last_confirmed_at", time.time())
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.CONFIRMED,
                signature=signature,
                fill=fill,
                latency_ms=latency,
                submit_latency_ms=submit_latency,
            )
        except OnChainTransactionError as exc:
            error = safe_error(exc)
            self.store.fail_order(order_id, error)
            self.store.increment_metric("orders_failed_total")
            return ExecutionResult(
                order_id=order_id,
                status=OrderStatus.FAILED,
                signature=local_signature,
                latency_ms=(time.perf_counter() - started) * 1_000,
                error=error,
            )
        except Exception as exc:
            error = safe_error(exc)
            if broadcast_attempted:
                status = OrderStatus.UNKNOWN
                self.store.update_order(
                    order_id,
                    status,
                    signature=local_signature,
                    error=error,
                )
                self.store.increment_metric("orders_unknown_total")
            else:
                status = OrderStatus.FAILED
                self.store.fail_order(order_id, error)
                self.store.increment_metric("orders_failed_total")
            logger.error("trade execution %s for %s: %s", status.value, mint, type(exc).__name__)
            return ExecutionResult(
                order_id=order_id,
                status=status,
                signature=local_signature,
                latency_ms=(time.perf_counter() - started) * 1_000,
                error=error,
            )
