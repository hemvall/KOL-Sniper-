from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from .domain import Fill, Opportunity, OrderRecord, OrderStatus, PositionRecord, Side
from .schema import migrate_schema
from .storage_exits import PENDING_STATUSES, ExitStoreMixin


class Store(ExitStoreMixin):
    """SQLite-backed source of truth with process-local write serialization."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def migrate(self) -> None:
        # SQLite forbids changing journal mode inside BEGIN IMMEDIATE when an
        # existing database is reopened after a process restart.
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
        with self.transaction() as db:
            migrate_schema(db)

    @staticmethod
    def _iso(value: datetime | None = None) -> str:
        return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()

    def record_opportunity(self, opportunity: Opportunity) -> tuple[int, bool]:
        with self.transaction() as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO opportunities
                   (source, message_id, mint, raw_message, message_at, received_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    opportunity.source,
                    opportunity.message_id,
                    opportunity.mint,
                    opportunity.raw_message,
                    self._iso(opportunity.message_at) if opportunity.message_at else None,
                    self._iso(opportunity.received_at),
                ),
            )
            created = cursor.rowcount == 1
            row = db.execute(
                "SELECT id FROM opportunities WHERE source=? AND message_id=? AND mint=?",
                (opportunity.source, opportunity.message_id, opportunity.mint),
            ).fetchone()
            if row is None:
                raise RuntimeError("failed to load recorded opportunity")
            return int(row["id"]), created

    def set_opportunity_status(self, opportunity_id: int, status: str, reason: str | None = None) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE opportunities SET status=?, reason=? WHERE id=?",
                (status, reason, opportunity_id),
            )

    def create_order(
        self,
        mint: str,
        side: str,
        requested_amount: float,
        opportunity_id: int | None = None,
        amount_in_tokens: bool = False,
    ) -> str:
        order_id = uuid.uuid4().hex
        now = self._iso()
        with self.transaction() as db:
            self._insert_order(
                db, order_id, mint, side, requested_amount, opportunity_id, amount_in_tokens, now
            )
        return order_id

    @staticmethod
    def _insert_order(
        db: sqlite3.Connection,
        order_id: str,
        mint: str,
        side: str,
        requested_amount: float,
        opportunity_id: int | None,
        amount_in_tokens: bool,
        now: str,
    ) -> None:
        db.execute(
            """INSERT INTO orders
               (id, opportunity_id, mint, side, requested_amount, amount_in_tokens, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                opportunity_id,
                mint,
                side,
                requested_amount,
                int(amount_in_tokens),
                OrderStatus.BUILDING.value,
                now,
                now,
            ),
        )

    def reserve_buy(
        self,
        *,
        mint: str,
        amount_sol: float,
        opportunity_id: int,
        slippage_bps: int,
        max_pending_orders: int,
        max_open_positions: int,
        max_total_exposure_sol: float,
        max_daily_loss_sol: float,
        mint_cooldown_seconds: int,
        execution_overhead_sol: float,
    ) -> tuple[str | None, str]:
        """Atomically enforce portfolio limits and reserve a buy order."""
        now = datetime.now(timezone.utc)
        cutoff = datetime.fromtimestamp(now.timestamp() - mint_cooldown_seconds, timezone.utc).isoformat()
        pending_placeholders = ",".join("?" for _ in PENDING_STATUSES)
        with self.transaction() as db:
            pending = int(
                db.execute(
                    f"SELECT COUNT(*) AS n FROM orders WHERE status IN ({pending_placeholders})",
                    PENDING_STATUSES,
                ).fetchone()["n"]
            )
            if pending >= max_pending_orders:
                return None, "pending-order limit reached"
            if db.execute("SELECT 1 FROM positions WHERE mint=? AND status='open'", (mint,)).fetchone():
                return None, "mint already has an open position"
            recent_statuses = (*PENDING_STATUSES, OrderStatus.CONFIRMED.value, OrderStatus.DRY_RUN.value)
            recent_placeholders = ",".join("?" for _ in recent_statuses)
            if db.execute(
                f"""SELECT 1 FROM orders WHERE mint=? AND side='buy'
                    AND status IN ({recent_placeholders}) AND created_at>=? LIMIT 1""",
                (mint, *recent_statuses, cutoff),
            ).fetchone():
                return None, "mint cooldown is active"
            position_row = db.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(cost_sol),0) AS exposure FROM positions WHERE status='open'"
            ).fetchone()
            pending_buys = db.execute(
                f"""SELECT COUNT(DISTINCT mint) AS n, COALESCE(SUM(requested_amount),0) AS exposure
                    FROM orders WHERE side='buy' AND status IN ({pending_placeholders})""",
                PENDING_STATUSES,
            ).fetchone()
            projected_positions = int(position_row["n"]) + int(pending_buys["n"]) + 1
            if projected_positions > max_open_positions:
                return None, "projected open-position limit reached"
            reserve_multiplier = 1 + slippage_bps / 10_000
            projected_exposure = (
                float(position_row["exposure"])
                + float(pending_buys["exposure"]) * reserve_multiplier
                + int(pending_buys["n"]) * execution_overhead_sol
                + amount_sol * reserve_multiplier
                + execution_overhead_sol
            )
            if projected_exposure > max_total_exposure_sol:
                return None, "projected total exposure cap reached"
            daily_pnl = float(
                db.execute(
                    "SELECT COALESCE(SUM(pnl_sol),0) AS pnl FROM pnl_events WHERE created_at>=?",
                    (now.date().isoformat(),),
                ).fetchone()["pnl"]
            )
            if daily_pnl <= -max_daily_loss_sol:
                return None, "daily loss circuit breaker is open"
            order_id = uuid.uuid4().hex
            self._insert_order(
                db,
                order_id,
                mint,
                Side.BUY.value,
                amount_sol,
                opportunity_id,
                False,
                now.isoformat(),
            )
            return order_id, ""

    def update_order(
        self,
        order_id: str,
        status: OrderStatus | str,
        *,
        builder: str | None = None,
        signature: str | None = None,
        error: str | None = None,
        last_valid_block_height: int | None = None,
    ) -> None:
        value = status.value if isinstance(status, OrderStatus) else status
        if value not in {item.value for item in OrderStatus}:
            raise ValueError(f"invalid order status: {value}")
        with self.transaction() as db:
            db.execute(
                """UPDATE orders SET status=?, builder=COALESCE(?, builder),
                   signature=COALESCE(?, signature), error=?,
                   last_valid_block_height=COALESCE(?, last_valid_block_height),
                   updated_at=? WHERE id=?
                   AND status NOT IN ('confirmed','failed','dry_run')""",
                (
                    value,
                    builder,
                    signature,
                    error,
                    last_valid_block_height,
                    self._iso(),
                    order_id,
                ),
            )

    def record_fill(self, order_id: str, fill: Fill) -> None:
        """Compatibility alias; confirmations are always one atomic transition."""
        self.confirm_order(order_id, fill)

    def _insert_fill(self, db: sqlite3.Connection, order_id: str, fill: Fill) -> bool:
        cursor = db.execute(
            """INSERT OR IGNORE INTO fills
               (order_id, signature, mint, side, token_amount, sol_amount, fee_sol, slot, compute_units, confirmed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                fill.signature,
                fill.mint,
                fill.side.value,
                fill.token_amount,
                fill.sol_amount,
                fill.fee_sol,
                fill.slot,
                fill.compute_units,
                self._iso(fill.confirmed_at),
            ),
        )
        return cursor.rowcount == 1

    def confirm_order(self, order_id: str, fill: Fill) -> None:
        with self.transaction() as db:
            order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if not order:
                raise ValueError("cannot confirm an unknown order")
            if order["mint"] != fill.mint or order["side"] != fill.side.value:
                raise ValueError("fill does not match order mint/side")
            inserted = self._insert_fill(db, order_id, fill)
            if inserted:
                self._apply_fill(db, fill)
            else:
                existing = db.execute(
                    "SELECT order_id FROM fills WHERE signature=?", (fill.signature,)
                ).fetchone()
                if not existing or existing["order_id"] != order_id:
                    raise ValueError("fill signature already belongs to another order")
            now = self._iso()
            db.execute(
                "UPDATE orders SET status=?, error=NULL, updated_at=? WHERE id=?",
                (OrderStatus.CONFIRMED.value, now, order_id),
            )
            db.execute(
                "UPDATE exit_steps SET status='complete', next_retry_at=NULL, updated_at=? WHERE order_id=?",
                (now, order_id),
            )

    def _apply_fill(self, db: sqlite3.Connection, fill: Fill) -> None:
        now = self._iso(fill.confirmed_at)
        row = db.execute("SELECT * FROM positions WHERE mint=?", (fill.mint,)).fetchone()
        if fill.side.value == "buy":
            total_cost = fill.sol_amount + fill.fee_sol
            if row and row["status"] == "open":
                db.execute(
                    """UPDATE positions SET token_amount=token_amount+?, entry_token_amount=entry_token_amount+?,
                       cost_sol=cost_sol+?, entry_cost_sol=entry_cost_sol+?, updated_at=? WHERE mint=?""",
                    (fill.token_amount, fill.token_amount, total_cost, total_cost, now, fill.mint),
                )
            elif row:
                db.execute("DELETE FROM exit_steps WHERE mint=?", (fill.mint,))
                db.execute(
                    """UPDATE positions SET token_amount=?, entry_token_amount=?, cost_sol=?, entry_cost_sol=?,
                       peak_price_sol=NULL, opened_at=?, updated_at=?, status='open' WHERE mint=?""",
                    (fill.token_amount, fill.token_amount, total_cost, total_cost, now, now, fill.mint),
                )
            else:
                db.execute(
                    """INSERT INTO positions
                       (mint, token_amount, entry_token_amount, cost_sol, entry_cost_sol, opened_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (fill.mint, fill.token_amount, fill.token_amount, total_cost, total_cost, now, now),
                )
            return
        if not row or float(row["token_amount"]) <= 0:
            return
        prior_tokens = float(row["token_amount"])
        sold_tokens = min(prior_tokens, fill.token_amount)
        allocated_cost = float(row["cost_sol"]) * (sold_tokens / prior_tokens)
        remaining_tokens = max(0.0, prior_tokens - sold_tokens)
        remaining_cost = max(0.0, float(row["cost_sol"]) - allocated_cost)
        pnl = fill.sol_amount - allocated_cost - fill.fee_sol
        db.execute(
            """UPDATE positions SET token_amount=?, cost_sol=?, realized_pnl_sol=realized_pnl_sol+?,
               updated_at=?, status=? WHERE mint=?""",
            (
                remaining_tokens,
                remaining_cost,
                pnl,
                now,
                "closed" if remaining_tokens <= 1e-12 else "open",
                fill.mint,
            ),
        )
        db.execute(
            "INSERT OR IGNORE INTO pnl_events(mint, signature, pnl_sol, created_at) VALUES (?, ?, ?, ?)",
            (fill.mint, fill.signature, pnl, now),
        )

    def risk_snapshot(self) -> dict[str, float]:
        with self.connection() as db:
            pending_placeholders = ",".join("?" for _ in PENDING_STATUSES)
            pending = db.execute(
                f"SELECT COUNT(*) AS n FROM orders WHERE status IN ({pending_placeholders})", PENDING_STATUSES
            ).fetchone()["n"]
            row = db.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(cost_sol),0) AS exposure FROM positions WHERE status='open'"
            ).fetchone()
            reserved = db.execute(
                f"""SELECT COALESCE(SUM(requested_amount),0) AS exposure FROM orders
                    WHERE side='buy' AND status IN ({pending_placeholders})""",
                PENDING_STATUSES,
            ).fetchone()["exposure"]
            daily = db.execute(
                "SELECT COALESCE(SUM(pnl_sol),0) AS pnl FROM pnl_events WHERE created_at >= ?",
                (datetime.now(timezone.utc).date().isoformat(),),
            ).fetchone()["pnl"]
            return {
                "pending_orders": float(pending),
                "open_positions": float(row["n"]),
                "exposure_sol": float(row["exposure"]),
                "reserved_exposure_sol": float(reserved),
                "projected_exposure_sol": float(row["exposure"]) + float(reserved),
                "daily_pnl_sol": float(daily),
            }

    def open_positions(self) -> list[PositionRecord]:
        with self.connection() as db:
            return [
                cast(PositionRecord, dict(row))
                for row in db.execute("SELECT * FROM positions WHERE status='open'")
            ]

    def get_position(self, mint: str) -> PositionRecord | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM positions WHERE mint=?", (mint,)).fetchone()
            return cast(PositionRecord, dict(row)) if row else None

    def update_position_peak(self, mint: str, peak_price_sol: float) -> None:
        with self.transaction() as db:
            db.execute(
                """UPDATE positions SET peak_price_sol=CASE
                   WHEN peak_price_sol IS NULL OR peak_price_sol < ? THEN ? ELSE peak_price_sol END,
                   updated_at=? WHERE mint=? AND status='open'""",
                (peak_price_sol, peak_price_sol, self._iso(), mint),
            )

    def pending_orders(self) -> list[OrderRecord]:
        placeholders = ",".join("?" for _ in PENDING_STATUSES)
        with self.connection() as db:
            return [
                cast(OrderRecord, dict(row))
                for row in db.execute(
                    f"SELECT * FROM orders WHERE status IN ({placeholders}) ORDER BY created_at",
                    PENDING_STATUSES,
                )
            ]

    def fail_order(self, order_id: str, error: str) -> None:
        with self.transaction() as db:
            now = self._iso()
            updated = db.execute(
                """UPDATE orders SET status=?, error=?, updated_at=? WHERE id=?
                   AND status NOT IN ('confirmed','confirmed_unparsed','dry_run')""",
                (OrderStatus.FAILED.value, error, now, order_id),
            )
            if updated.rowcount != 1:
                return
            row = db.execute("SELECT attempts FROM exit_steps WHERE order_id=?", (order_id,)).fetchone()
            if row:
                retry_at = datetime.fromtimestamp(
                    datetime.now(timezone.utc).timestamp() + min(60, 2 ** min(int(row["attempts"]), 6)),
                    timezone.utc,
                ).isoformat()
                db.execute(
                    "UPDATE exit_steps SET status='failed', next_retry_at=?, updated_at=? WHERE order_id=?",
                    (retry_at, now, order_id),
                )

    def set_metric(self, key: str, value: float) -> None:
        with self.transaction() as db:
            db.execute(
                """INSERT INTO metrics(key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value, self._iso()),
            )

    def increment_metric(self, key: str, amount: float = 1.0) -> None:
        with self.transaction() as db:
            db.execute(
                """INSERT INTO metrics(key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=metrics.value+excluded.value,
                   updated_at=excluded.updated_at""",
                (key, amount, self._iso()),
            )

    def write_metrics(self, values: dict[str, float], deltas: dict[str, float]) -> None:
        """Flush hot-path counters in one SQLite transaction."""
        with self.transaction() as db:
            now = self._iso()
            for key, value in values.items():
                db.execute(
                    """INSERT INTO metrics(key, value, updated_at) VALUES (?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                       updated_at=excluded.updated_at""",
                    (key, value, now),
                )
            for key, amount in deltas.items():
                db.execute(
                    """INSERT INTO metrics(key, value, updated_at) VALUES (?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET value=metrics.value+excluded.value,
                       updated_at=excluded.updated_at""",
                    (key, amount, now),
                )

    def metrics(self) -> dict[str, float]:
        with self.connection() as db:
            return {
                str(row["key"]): float(row["value"]) for row in db.execute("SELECT key, value FROM metrics")
            }

    def recent_orders(self, limit: int = 20) -> list[OrderRecord]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,))
            return [cast(OrderRecord, dict(row)) for row in rows]
