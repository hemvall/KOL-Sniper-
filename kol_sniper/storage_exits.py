from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, cast

from .domain import ExitStepRecord, OrderStatus, Side

PENDING_STATUSES = ("building", "signed", "submitted", "unknown", "confirmed_unparsed")


class ExitStoreMixin:
    """Durable exit-intent repository mixed into the public Store."""

    def ensure_exit_steps(self, mint: str, steps: list[tuple[float, float]]) -> None:
        owner = cast(Any, self)
        with owner.transaction() as db:
            now = owner._iso()
            for target, fraction in steps:
                key = f"{target:g}x"
                db.execute(
                    """INSERT OR IGNORE INTO exit_steps
                       (mint, step_key, target_multiple, fraction, updated_at) VALUES (?, ?, ?, ?, ?)""",
                    (mint, key, target, fraction, now),
                )

    def exit_steps(self, mint: str) -> list[ExitStepRecord]:
        owner = cast(Any, self)
        with owner.connection() as db:
            return [
                cast(ExitStepRecord, dict(row))
                for row in db.execute(
                    "SELECT * FROM exit_steps WHERE mint=? ORDER BY target_multiple", (mint,)
                )
            ]

    def mark_exit_step(self, mint: str, step_key: str, status: str, order_id: str | None = None) -> None:
        owner = cast(Any, self)
        with owner.transaction() as db:
            db.execute(
                "UPDATE exit_steps SET status=?, order_id=COALESCE(?, order_id), updated_at=? WHERE mint=? AND step_key=?",
                (status, order_id, owner._iso(), mint, step_key),
            )

    def reserve_exit(
        self,
        *,
        mint: str,
        step_key: str,
        target_multiple: float,
        fraction: float,
        token_amount: float,
    ) -> str | None:
        """Atomically reserve one exit intent and its sell order."""
        owner = cast(Any, self)
        now = owner._iso()
        placeholders = ",".join("?" for _ in PENDING_STATUSES)
        with owner.transaction() as db:
            position = db.execute(
                "SELECT token_amount FROM positions WHERE mint=? AND status='open'", (mint,)
            ).fetchone()
            if not position or float(position["token_amount"]) <= 0:
                return None
            if token_amount <= 0 or token_amount > float(position["token_amount"]) + 1e-9:
                return None
            if db.execute(
                f"SELECT 1 FROM orders WHERE mint=? AND side='sell' AND status IN ({placeholders}) LIMIT 1",
                (mint, *PENDING_STATUSES),
            ).fetchone():
                return None
            db.execute(
                """INSERT OR IGNORE INTO exit_steps
                   (mint, step_key, target_multiple, fraction, updated_at) VALUES (?, ?, ?, ?, ?)""",
                (mint, step_key, target_multiple, fraction, now),
            )
            claimed = db.execute(
                """UPDATE exit_steps SET status='executing', attempts=attempts+1,
                   next_retry_at=NULL, order_id=NULL, updated_at=?
                   WHERE mint=? AND step_key=? AND status IN ('pending','failed')
                   AND (next_retry_at IS NULL OR next_retry_at<=?)""",
                (now, mint, step_key, now),
            )
            if claimed.rowcount != 1:
                return None
            order_id = uuid.uuid4().hex
            owner._insert_order(db, order_id, mint, Side.SELL.value, token_amount, None, True, now)
            db.execute(
                "UPDATE exit_steps SET order_id=? WHERE mint=? AND step_key=?",
                (order_id, mint, step_key),
            )
            return order_id

    def finish_exit_attempt(self, order_id: str, status: OrderStatus) -> None:
        if status not in {OrderStatus.FAILED, OrderStatus.UNKNOWN, OrderStatus.DRY_RUN}:
            return
        owner = cast(Any, self)
        with owner.transaction() as db:
            row = db.execute("SELECT attempts FROM exit_steps WHERE order_id=?", (order_id,)).fetchone()
            if not row:
                return
            now = datetime.now(timezone.utc)
            if status is OrderStatus.FAILED:
                retry_at = datetime.fromtimestamp(
                    now.timestamp() + min(60, 2 ** min(int(row["attempts"]), 6)), timezone.utc
                ).isoformat()
                exit_status = "failed"
            elif status is OrderStatus.UNKNOWN:
                retry_at = None
                exit_status = "unknown"
            else:
                retry_at = None
                exit_status = "simulated"
            db.execute(
                "UPDATE exit_steps SET status=?, next_retry_at=?, updated_at=? WHERE order_id=?",
                (exit_status, retry_at, now.isoformat(), order_id),
            )
