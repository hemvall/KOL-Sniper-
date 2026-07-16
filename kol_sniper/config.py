from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    try:
        return float(env.get(key, str(default)))
    except ValueError as exc:
        raise ValueError(f"{key} must be a number") from exc


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(env.get(key, str(default)))
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    dry_run: bool = True
    database_path: Path = Path("data/kol_sniper.db")
    rpc_url: str = "https://api.mainnet-beta.solana.com"
    rpc_submit_urls: tuple[str, ...] = ()
    helius_sender_url: str | None = None
    helius_tip_account: str | None = None
    pumpportal_url: str = "https://pumpportal.fun/api/trade-local"
    builder_mode: str = "local"
    allow_builder_fallback: bool = False
    local_builder_command: tuple[str, ...] = ("node", "tools/pump_builder.mjs")
    local_builder_url: str | None = None

    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session: str = "data/sniper_session"
    telegram_channels: tuple[str, ...] = ()
    private_key: str | None = None
    notification_bot_token: str | None = None
    notification_chat_id: str | None = None
    admin_user_ids: tuple[str, ...] = ()

    buy_amount_sol: float = 0.1
    slippage_bps: int = 1_500
    priority_fee_sol: float = 0.0001
    sender_tip_sol: float = 0.0002
    max_execution_fee_sol: float = 0.01
    max_transaction_transfer_sol: float = 0.5
    max_open_positions: int = 4
    max_pending_orders: int = 2
    max_total_exposure_sol: float = 1.0
    max_daily_loss_sol: float = 0.25
    mint_cooldown_seconds: int = 86_400
    signal_concurrency: int = 8

    confirm_timeout_seconds: float = 25.0
    rpc_timeout_seconds: float = 3.0
    websocket_stale_seconds: float = 20.0
    reconcile_interval_seconds: float = 2.0
    exit_ladder: str = "2:0.25,3:0.25,5:0.25"
    stop_loss_pct: float = 30.0
    trailing_stop_pct: float = 25.0
    max_hold_seconds: int = 3_600
    health_host: str = "127.0.0.1"
    health_port: int = 8787
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        source: Mapping[str, str] = os.environ if env is None else env
        compat = dict(source)
        aliases = {
            "TELEGRAM_API_ID": "TG_API_ID",
            "TELEGRAM_API_HASH": "TG_API_HASH",
            "TELEGRAM_CHANNELS": "TG_CHANNELS",
            "PRIVATE_KEY": "SOL_PRIVATE_KEY",
            "BUY_AMOUNT_SOL": "BUY_SOL",
            "PRIORITY_FEE_SOL": "PRIORITY_FEE",
        }
        for current, legacy in aliases.items():
            if current not in compat and legacy in compat:
                compat[current] = compat[legacy]
        if "SLIPPAGE_BPS" not in compat and "SLIPPAGE" in compat:
            try:
                compat["SLIPPAGE_BPS"] = str(round(float(compat["SLIPPAGE"]) * 100))
            except ValueError as exc:
                raise ValueError("SLIPPAGE must be a number") from exc
        if "MAX_TRANSACTION_TRANSFER_SOL" not in compat and "BUY_SOL" in compat:
            try:
                legacy_slippage = float(compat.get("SLIPPAGE", "15")) / 100
                compat["MAX_TRANSACTION_TRANSFER_SOL"] = str(
                    float(compat["BUY_SOL"]) * (1 + legacy_slippage) + 0.001
                )
            except ValueError as exc:
                raise ValueError("BUY_SOL and SLIPPAGE must be numbers") from exc
        if "RPC_URL" not in compat:
            helius_key = compat.get("HELIUS_API_KEY", "").strip()
            if helius_key:
                network = compat.get("HELIUS_NETWORK", "mainnet").strip()
                compat["RPC_URL"] = f"https://{network}.helius-rpc.com/?api-key={helius_key}"
            elif compat.get("SOL_RPC_URL"):
                compat["RPC_URL"] = compat["SOL_RPC_URL"]
        values: Mapping[str, str] = compat
        api_id_raw = values.get("TELEGRAM_API_ID")
        try:
            api_id = int(api_id_raw) if api_id_raw else None
        except ValueError as exc:
            raise ValueError("TELEGRAM_API_ID must be an integer") from exc
        command = tuple(values.get("LOCAL_BUILDER_COMMAND", "node tools/pump_builder.mjs").split())
        return cls(
            dry_run=_bool(values.get("DRY_RUN"), True),
            database_path=Path(values.get("DATABASE_PATH", "data/kol_sniper.db")),
            rpc_url=values.get("RPC_URL", "https://api.mainnet-beta.solana.com"),
            rpc_submit_urls=_csv(values.get("RPC_SUBMIT_URLS")),
            helius_sender_url=values.get("HELIUS_SENDER_URL") or None,
            helius_tip_account=values.get("HELIUS_TIP_ACCOUNT") or None,
            pumpportal_url=values.get("PUMPPORTAL_URL", "https://pumpportal.fun/api/trade-local"),
            builder_mode=values.get("BUILDER_MODE", "local").lower(),
            allow_builder_fallback=_bool(values.get("ALLOW_BUILDER_FALLBACK"), False),
            local_builder_command=command,
            local_builder_url=values.get("LOCAL_BUILDER_URL") or None,
            telegram_api_id=api_id,
            telegram_api_hash=values.get("TELEGRAM_API_HASH") or None,
            telegram_session=values.get("TELEGRAM_SESSION", "data/sniper_session"),
            telegram_channels=_csv(values.get("TELEGRAM_CHANNELS")),
            private_key=values.get("PRIVATE_KEY") or None,
            notification_bot_token=values.get("NOTIFICATION_BOT_TOKEN")
            or values.get("TELEGRAM_BOT_TOKEN")
            or None,
            notification_chat_id=values.get("NOTIFICATION_CHAT_ID") or values.get("TELEGRAM_CHAT_ID") or None,
            admin_user_ids=_csv(values.get("ADMIN_USER_IDS") or values.get("ADMIN_CHAT_IDS")),
            buy_amount_sol=_float(values, "BUY_AMOUNT_SOL", 0.1),
            slippage_bps=_int(values, "SLIPPAGE_BPS", 1_500),
            priority_fee_sol=_float(values, "PRIORITY_FEE_SOL", 0.0001),
            sender_tip_sol=_float(values, "SENDER_TIP_SOL", 0.0002),
            max_execution_fee_sol=_float(values, "MAX_EXECUTION_FEE_SOL", 0.01),
            max_transaction_transfer_sol=_float(values, "MAX_TRANSACTION_TRANSFER_SOL", 0.5),
            max_open_positions=_int(values, "MAX_OPEN_POSITIONS", 4),
            max_pending_orders=_int(values, "MAX_PENDING_ORDERS", 2),
            max_total_exposure_sol=_float(values, "MAX_TOTAL_EXPOSURE_SOL", 1.0),
            max_daily_loss_sol=_float(values, "MAX_DAILY_LOSS_SOL", 0.25),
            mint_cooldown_seconds=_int(values, "MINT_COOLDOWN_SECONDS", 86_400),
            signal_concurrency=_int(values, "SIGNAL_CONCURRENCY", 8),
            confirm_timeout_seconds=_float(values, "CONFIRM_TIMEOUT_SECONDS", 25.0),
            rpc_timeout_seconds=_float(values, "RPC_TIMEOUT_SECONDS", 3.0),
            websocket_stale_seconds=_float(values, "WEBSOCKET_STALE_SECONDS", 20.0),
            reconcile_interval_seconds=_float(values, "RECONCILE_INTERVAL_SECONDS", 2.0),
            exit_ladder=values.get("EXIT_LADDER", "2:0.25,3:0.25,5:0.25"),
            stop_loss_pct=_float(values, "STOP_LOSS_PCT", 30.0),
            trailing_stop_pct=_float(values, "TRAILING_STOP_PCT", 25.0),
            max_hold_seconds=_int(values, "MAX_HOLD_SECONDS", 3_600),
            health_host=values.get("HEALTH_HOST", "127.0.0.1"),
            health_port=_int(values, "HEALTH_PORT", 8787),
            log_level=values.get("LOG_LEVEL", "INFO").upper(),
        )

    def errors(self, live: bool | None = None) -> list[str]:
        is_live = not self.dry_run if live is None else live
        errors: list[str] = []
        if self.builder_mode not in {"local", "pumpportal"}:
            errors.append("BUILDER_MODE must be local or pumpportal")
        required_trade_cap = self.buy_amount_sol * (1 + self.slippage_bps / 10_000)
        if self.buy_amount_sol <= 0 or required_trade_cap > self.max_transaction_transfer_sol:
            errors.append("MAX_TRANSACTION_TRANSFER_SOL must cover BUY_AMOUNT_SOL plus configured slippage")
        if not (1 <= self.slippage_bps <= 5_000):
            errors.append("SLIPPAGE_BPS must be between 1 and 5000")
        if (
            min(self.priority_fee_sol, self.sender_tip_sol) < 0
            or self.priority_fee_sol + self.sender_tip_sol > self.max_execution_fee_sol
            or self.max_execution_fee_sol <= 0
        ):
            errors.append("priority fee and Sender tip must be non-negative and within MAX_EXECUTION_FEE_SOL")
        if min(self.max_open_positions, self.max_pending_orders, self.signal_concurrency) < 1:
            errors.append("position, pending-order and concurrency limits must be positive")
        if self.max_total_exposure_sol <= 0 or self.max_daily_loss_sol <= 0:
            errors.append("exposure and daily-loss limits must be positive")
        if self.mint_cooldown_seconds < 0 or self.reconcile_interval_seconds <= 0:
            errors.append("mint cooldown must be non-negative and reconcile interval must be positive")
        if not (0 < self.stop_loss_pct < 100 and 0 < self.trailing_stop_pct < 100):
            errors.append("stop-loss and trailing-stop percentages must be between 0 and 100")
        if (
            min(
                self.confirm_timeout_seconds,
                self.rpc_timeout_seconds,
                self.websocket_stale_seconds,
                float(self.max_hold_seconds),
            )
            <= 0
        ):
            errors.append("timeouts and MAX_HOLD_SECONDS must be positive")
        if not (1 <= self.health_port <= 65_535):
            errors.append("HEALTH_PORT must be between 1 and 65535")
        if is_live:
            required = {
                "TELEGRAM_API_ID": self.telegram_api_id,
                "TELEGRAM_API_HASH": self.telegram_api_hash,
                "TELEGRAM_CHANNELS": self.telegram_channels,
                "PRIVATE_KEY": self.private_key,
                "RPC_URL": self.rpc_url,
            }
            errors.extend(f"{key} is required in live mode" for key, value in required.items() if not value)
            if self.helius_sender_url and not self.helius_tip_account:
                errors.append("HELIUS_TIP_ACCOUNT is required when HELIUS_SENDER_URL is set")
            if self.helius_sender_url and self.builder_mode == "pumpportal":
                errors.append(
                    "Helius Sender requires BUILDER_MODE=local so the tip is signed into the transaction"
                )
        return errors

    def require_valid(self, live: bool | None = None) -> None:
        errors = self.errors(live=live)
        if errors:
            raise ValueError("Invalid configuration: " + "; ".join(errors))
