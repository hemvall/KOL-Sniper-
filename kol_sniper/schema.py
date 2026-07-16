from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 3


def migrate_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            message_id TEXT NOT NULL,
            mint TEXT NOT NULL,
            raw_message TEXT NOT NULL,
            message_at TEXT,
            received_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'received',
            reason TEXT,
            UNIQUE(source, message_id, mint)
        );
        CREATE INDEX IF NOT EXISTS idx_opportunities_mint ON opportunities(mint, received_at);
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            opportunity_id INTEGER REFERENCES opportunities(id),
            mint TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
            requested_amount REAL NOT NULL,
            amount_in_tokens INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            builder TEXT,
            signature TEXT,
            error TEXT,
            last_valid_block_height INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, created_at);
        CREATE TABLE IF NOT EXISTS fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL REFERENCES orders(id),
            signature TEXT NOT NULL UNIQUE,
            mint TEXT NOT NULL,
            side TEXT NOT NULL,
            token_amount REAL NOT NULL,
            sol_amount REAL NOT NULL,
            fee_sol REAL NOT NULL DEFAULT 0,
            slot INTEGER,
            compute_units INTEGER,
            confirmed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS positions (
            mint TEXT PRIMARY KEY,
            token_amount REAL NOT NULL,
            entry_token_amount REAL NOT NULL,
            cost_sol REAL NOT NULL,
            entry_cost_sol REAL NOT NULL,
            realized_pnl_sol REAL NOT NULL DEFAULT 0,
            peak_price_sol REAL,
            opened_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS exit_steps (
            mint TEXT NOT NULL REFERENCES positions(mint),
            step_key TEXT NOT NULL,
            target_multiple REAL NOT NULL,
            fraction REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            order_id TEXT REFERENCES orders(id),
            attempts INTEGER NOT NULL DEFAULT 0,
            next_retry_at TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(mint, step_key)
        );
        CREATE TABLE IF NOT EXISTS metrics (
            key TEXT PRIMARY KEY,
            value REAL NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pnl_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mint TEXT NOT NULL,
            signature TEXT NOT NULL UNIQUE,
            pnl_sol REAL NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    position_columns = {row["name"] for row in db.execute("PRAGMA table_info(positions)")}
    if "entry_cost_sol" not in position_columns:
        db.execute("ALTER TABLE positions ADD COLUMN entry_cost_sol REAL NOT NULL DEFAULT 0")
        db.execute("UPDATE positions SET entry_cost_sol=cost_sol")
    exit_columns = {row["name"] for row in db.execute("PRAGMA table_info(exit_steps)")}
    if "attempts" not in exit_columns:
        db.execute("ALTER TABLE exit_steps ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
    if "next_retry_at" not in exit_columns:
        db.execute("ALTER TABLE exit_steps ADD COLUMN next_retry_at TEXT")
    order_columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)")}
    if "last_valid_block_height" not in order_columns:
        db.execute("ALTER TABLE orders ADD COLUMN last_valid_block_height INTEGER")
    db.execute(
        """INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (str(SCHEMA_VERSION),),
    )
