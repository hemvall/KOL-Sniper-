from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .storage import Store


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str = ""
    order_id: str | None = None


class RiskManager:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store

    def allow_buy(self, amount_sol: float) -> RiskDecision:
        if amount_sol <= 0:
            return RiskDecision(False, "buy amount must be positive")
        if amount_sol > self.settings.max_transaction_transfer_sol:
            return RiskDecision(False, "buy exceeds per-transaction cap")
        snapshot = self.store.risk_snapshot()
        if snapshot["pending_orders"] >= self.settings.max_pending_orders:
            return RiskDecision(False, "pending-order limit reached")
        if snapshot["open_positions"] + snapshot["pending_orders"] >= self.settings.max_open_positions:
            return RiskDecision(False, "open-position limit reached")
        reserve = amount_sol * (1 + self.settings.slippage_bps / 10_000)
        if snapshot["projected_exposure_sol"] + reserve > self.settings.max_total_exposure_sol:
            return RiskDecision(False, "total exposure cap reached")
        if snapshot["daily_pnl_sol"] <= -self.settings.max_daily_loss_sol:
            return RiskDecision(False, "daily loss circuit breaker is open")
        return RiskDecision(True)

    def reserve_buy(self, mint: str, opportunity_id: int, amount_sol: float) -> RiskDecision:
        if amount_sol <= 0 or amount_sol > self.settings.max_transaction_transfer_sol:
            return RiskDecision(False, "buy amount violates per-transaction cap")
        order_id, reason = self.store.reserve_buy(
            mint=mint,
            amount_sol=amount_sol,
            opportunity_id=opportunity_id,
            slippage_bps=self.settings.slippage_bps,
            max_pending_orders=self.settings.max_pending_orders,
            max_open_positions=self.settings.max_open_positions,
            max_total_exposure_sol=self.settings.max_total_exposure_sol,
            max_daily_loss_sol=self.settings.max_daily_loss_sol,
            mint_cooldown_seconds=self.settings.mint_cooldown_seconds,
            execution_overhead_sol=self.settings.priority_fee_sol
            + (self.settings.sender_tip_sol if self.settings.helius_sender_url else 0)
            + 0.005,
        )
        return RiskDecision(order_id is not None, reason, order_id)
