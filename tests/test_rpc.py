import time
from collections.abc import Iterable
from typing import cast

import pytest

from kol_sniper.domain import Side
from kol_sniper.rpc import RpcClient, RpcError, TransactionSubmitter, extract_fill

from .conftest import MINT, WALLET


def transaction_fixture(delta: float = 125.0):
    return {
        "slot": 99,
        "transaction": {"message": {"accountKeys": [{"pubkey": WALLET, "signer": True}]}},
        "meta": {
            "fee": 5_000,
            "computeUnitsConsumed": 120_000,
            "preBalances": [2_000_000_000],
            "postBalances": [1_899_995_000],
            "preTokenBalances": [],
            "postTokenBalances": [
                {"mint": MINT, "owner": WALLET, "uiTokenAmount": {"uiAmountString": str(delta)}}
            ],
        },
    }


def test_extracts_confirmed_buy_fill() -> None:
    fill = extract_fill(transaction_fixture(), "sig", WALLET, MINT, Side.BUY)
    assert fill.token_amount == 125
    assert fill.sol_amount == pytest.approx(0.1)
    assert fill.fee_sol == 0.000005
    assert fill.compute_units == 120_000


def test_rejects_confirmation_without_token_delta() -> None:
    with pytest.raises(RpcError, match="no expected"):
        extract_fill(transaction_fixture(0), "sig", WALLET, MINT, Side.BUY)


def test_rejects_missing_token_owner_or_wallet_balance() -> None:
    transaction = transaction_fixture()
    transaction["meta"]["postTokenBalances"][0].pop("owner")
    with pytest.raises(RpcError, match="no expected"):
        extract_fill(transaction, "sig", WALLET, MINT, Side.BUY)
    transaction = transaction_fixture()
    transaction["transaction"]["message"]["accountKeys"] = []
    with pytest.raises(RpcError, match="configured wallet"):
        extract_fill(transaction, "sig", WALLET, MINT, Side.BUY)


def test_submit_fanout_returns_without_waiting_for_slow_route() -> None:
    class Client:
        def __init__(self, delay: float, result: str):
            self.delay = delay
            self.result = result

        def send_transaction(self, encoded: str) -> str:
            time.sleep(self.delay)
            return self.result

    clients = cast(Iterable[RpcClient], [Client(0.3, "slow"), Client(0.01, "fast")])
    submitter = TransactionSubmitter(clients)
    try:
        started = time.perf_counter()
        assert submitter.submit("bytes") == "fast"
        assert time.perf_counter() - started < 0.15
    finally:
        submitter.close()
