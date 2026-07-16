from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .config import Settings
from .executor import TradeExecutor
from .risk import RiskManager
from .rpc import RpcClient, TransactionSubmitter
from .service import NotificationCallback, SniperService
from .storage import Store
from .strategy import ExitManager
from .transactions import (
    FallbackBuilder,
    IsolatedPumpBuilder,
    LocalPumpBuilder,
    PumpPortalBuilder,
    TransactionBuilder,
)
from .validation import TransactionValidator


@dataclass
class Runtime:
    store: Store
    service: SniperService
    builder: TransactionBuilder

    async def close(self) -> None:
        await self.service.stop()
        await asyncio.to_thread(self.service.executor.close)
        self.builder.close()


def create_runtime(settings: Settings, notify: NotificationCallback | None = None) -> Runtime:
    store = Store(settings.database_path)
    confirmation = RpcClient(settings.rpc_url, settings.rpc_timeout_seconds)
    urls: list[str] = []
    if settings.helius_sender_url:
        urls.append(settings.helius_sender_url)
    urls.extend(settings.rpc_submit_urls)
    urls.append(settings.rpc_url)
    clients = [RpcClient(url, settings.rpc_timeout_seconds) for url in dict.fromkeys(urls)]
    submitter = TransactionSubmitter(clients)

    portal = PumpPortalBuilder(settings.pumpportal_url, settings.rpc_timeout_seconds)
    if settings.builder_mode == "local":
        if settings.local_builder_url:
            local: TransactionBuilder = IsolatedPumpBuilder(
                settings.local_builder_url, settings.rpc_timeout_seconds
            )
        else:
            local = LocalPumpBuilder(
                settings.local_builder_command, settings.rpc_timeout_seconds, settings.rpc_url
            )
        builder: TransactionBuilder = FallbackBuilder(local, portal, settings.allow_builder_fallback)
    else:
        builder = portal
    validator = TransactionValidator(settings.max_transaction_transfer_sol)
    executor = TradeExecutor(settings, store, builder, validator, confirmation, submitter)
    risk = RiskManager(settings, store)
    exits = ExitManager(settings, store, executor)
    service = SniperService(settings, store, executor, risk, exits, notify)
    return Runtime(store, service, builder)
