from __future__ import annotations

from dataclasses import dataclass

import kol_sniper.executor as executor_module
from kol_sniper.config import Settings
from kol_sniper.domain import BuiltTransaction, OrderStatus, Side
from kol_sniper.executor import TradeExecutor
from kol_sniper.storage import Store

from .conftest import MINT


class Builder:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def build(self, request):
        if self.error:
            raise self.error
        return BuiltTransaction("encoded", builder="fake")

    def warm(self):
        return None


@dataclass
class Validated:
    transaction: object


class Validator:
    def validate(self, transaction, intent):
        return Validated(transaction)


class Confirmation:
    def ping(self):
        return 1.0


class Submitter:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def submit(self, encoded):
        if self.error:
            raise self.error
        return "local-signature"

    def close(self):
        return None


def make_executor(tmp_path, monkeypatch, *, builder_error=None, submit_error=None):
    monkeypatch.setattr(executor_module, "decode_transaction", lambda encoded, encoding: object())
    monkeypatch.setattr(
        executor_module, "sign_transaction", lambda transaction, keypair: ("signed", "local-signature")
    )
    settings = Settings(
        database_path=tmp_path / "state.db",
        dry_run=False,
        private_key="unused",
    )
    store = Store(settings.database_path)
    executor = TradeExecutor(
        settings,
        store,
        Builder(builder_error),  # type: ignore[arg-type]
        Validator(),  # type: ignore[arg-type]
        Confirmation(),  # type: ignore[arg-type]
        Submitter(submit_error),  # type: ignore[arg-type]
    )
    executor._keypair = type("Key", (), {"pubkey": lambda self: "wallet"})()
    return executor, store


def test_prebroadcast_error_is_failed(tmp_path, monkeypatch) -> None:
    executor, store = make_executor(tmp_path, monkeypatch, builder_error=ValueError("bad build"))
    result = executor.execute(mint=MINT, side=Side.BUY, amount=0.1)
    assert result.status is OrderStatus.FAILED
    assert store.recent_orders(1)[0]["status"] == "failed"


def test_submit_transport_error_is_unknown_with_local_signature(tmp_path, monkeypatch) -> None:
    executor, store = make_executor(tmp_path, monkeypatch, submit_error=TimeoutError("route timeout"))
    result = executor.execute(mint=MINT, side=Side.BUY, amount=0.1)
    order = store.recent_orders(1)[0]
    assert result.status is OrderStatus.UNKNOWN
    assert result.signature == "local-signature"
    assert order["status"] == "unknown"
    assert order["signature"] == "local-signature"
