from __future__ import annotations

import argparse
import json
from typing import Any

from kol_sniper.analytics import performance_snapshot
from kol_sniper.config import Settings
from kol_sniper.storage import Store


def get_store() -> Store:
    return Store(Settings.from_env().database_path)


def log_call(
    mint: str,
    action: str,
    amount: float = 0.0,
    signature: str | None = None,
    **extra: Any,
) -> str:
    """Compatibility logger; durable trade writes belong to TradeExecutor."""
    store = get_store()
    order_id = store.create_order(
        mint=mint,
        side="sell" if action.lower().startswith("sell") else "buy",
        requested_amount=float(amount),
        amount_in_tokens=action.lower().startswith("sell"),
    )
    store.update_order(
        order_id,
        str(extra.get("status", "unknown")),
        signature=signature,
        error=str(extra.get("error")) if extra.get("error") else None,
    )
    return order_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect KOL Sniper durable state")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    store = get_store()
    payload = {
        "risk": store.risk_snapshot(),
        "performance": performance_snapshot(store),
        "positions": store.open_positions(),
        "orders": store.recent_orders(args.limit),
        "metrics": store.metrics(),
    }
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
