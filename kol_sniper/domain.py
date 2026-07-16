from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypedDict


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    BUILDING = "building"
    SIGNED = "signed"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    CONFIRMED_UNPARSED = "confirmed_unparsed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    DRY_RUN = "dry_run"


class OrderRecord(TypedDict):
    id: str
    opportunity_id: int | None
    mint: str
    side: str
    requested_amount: float
    amount_in_tokens: int
    status: str
    builder: str | None
    signature: str | None
    error: str | None
    last_valid_block_height: int | None
    created_at: str
    updated_at: str


class PositionRecord(TypedDict):
    mint: str
    token_amount: float
    entry_token_amount: float
    cost_sol: float
    entry_cost_sol: float
    realized_pnl_sol: float
    peak_price_sol: float | None
    opened_at: str
    updated_at: str
    status: str


class ExitStepRecord(TypedDict):
    mint: str
    step_key: str
    target_multiple: float
    fraction: float
    status: str
    order_id: str | None
    attempts: int
    next_retry_at: str | None
    updated_at: str


@dataclass(frozen=True)
class Opportunity:
    source: str
    message_id: str
    mint: str
    raw_message: str
    received_at: datetime = field(default_factory=utc_now)
    message_at: datetime | None = None
    id: int | None = None


@dataclass(frozen=True)
class BuildRequest:
    side: Side
    mint: str
    wallet: str
    amount: float
    amount_in_tokens: bool = False
    slippage_bps: int = 1_500
    priority_fee_sol: float = 0.0001
    tip_sol: float = 0.0
    tip_account: str | None = None
    pool: str = "auto"


@dataclass(frozen=True)
class BuiltTransaction:
    encoded: str
    encoding: str = "base64"
    builder: str = "unknown"
    includes_priority_fee: bool = False
    includes_sender_tip: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Fill:
    signature: str
    mint: str
    side: Side
    token_amount: float
    sol_amount: float
    fee_sol: float = 0.0
    slot: int | None = None
    compute_units: int | None = None
    confirmed_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class ExecutionResult:
    order_id: str
    status: OrderStatus
    signature: str | None = None
    fill: Fill | None = None
    latency_ms: float | None = None
    submit_latency_ms: float | None = None
    error: str | None = None
    dry_run: bool = False
