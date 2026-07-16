from __future__ import annotations

import concurrent.futures
import itertools
import threading
import time
from collections.abc import Iterable
from typing import Any, cast

import requests

from .domain import Fill, Side


class RpcError(RuntimeError):
    pass


class OnChainTransactionError(RpcError):
    """A definitive chain rejection; unlike transport failures, this is terminal."""


class RpcClient:
    def __init__(self, url: str, timeout_seconds: float = 3.0):
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._ids = itertools.count(1)
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"Content-Type": "application/json", "User-Agent": "kol-sniper/2"})
            self._local.session = session
        return session

    def call(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        try:
            response = self._session().post(self.url, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RpcError(f"{method} transport failure ({type(exc).__name__})") from None
        if body.get("error"):
            error = body["error"]
            code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
            raise RpcError(f"{method} RPC error ({code})")
        return body.get("result")

    def ping(self) -> float:
        started = time.perf_counter()
        self.call("getLatestBlockhash", [{"commitment": "processed"}])
        return (time.perf_counter() - started) * 1_000

    def send_transaction(self, encoded_transaction: str) -> str:
        result = self.call(
            "sendTransaction",
            [
                encoded_transaction,
                {
                    "encoding": "base64",
                    "skipPreflight": True,
                    "maxRetries": 0,
                    "preflightCommitment": "processed",
                },
            ],
        )
        if not isinstance(result, str):
            raise RpcError("sendTransaction returned no signature")
        return result

    def signature_status(self, signature: str) -> dict[str, Any] | None:
        result = self.call("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])
        values = result.get("value", []) if result else []
        return values[0] if values else None

    def block_height(self) -> int:
        return int(self.call("getBlockHeight", [{"commitment": "processed"}]))

    def transaction(self, signature: str) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            self.call(
                "getTransaction",
                [
                    signature,
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed",
                        "maxSupportedTransactionVersion": 0,
                    },
                ],
            ),
        )


class TransactionSubmitter:
    """Fan out identical signed bytes; the first accepted signature wins."""

    def __init__(self, clients: Iterable[RpcClient]):
        self.clients = tuple(clients)
        if not self.clients:
            raise ValueError("at least one submit client is required")
        self._pools = tuple(
            concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"submit-{index}")
            for index, _ in enumerate(self.clients)
        )
        self._closed = False

    def submit(self, encoded_transaction: str) -> str:
        if self._closed:
            raise RuntimeError("transaction submitter is closed")
        errors: list[str] = []
        futures = [
            pool.submit(client.send_transaction, encoded_transaction)
            for pool, client in zip(self._pools, self.clients, strict=True)
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                signature = future.result()
                for pending in futures:
                    if pending is not future:
                        pending.cancel()
                return signature
            except Exception as exc:
                errors.append(type(exc).__name__)
        raise RpcError("all submit routes failed: " + " | ".join(errors))

    def close(self) -> None:
        self._closed = True
        for pool in self._pools:
            pool.shutdown(wait=False, cancel_futures=True)


def wait_for_confirmation(client: RpcClient, signature: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    delay = 0.15
    while time.monotonic() < deadline:
        status = client.signature_status(signature)
        if status:
            if status.get("err") is not None:
                raise OnChainTransactionError("transaction failed on chain")
            if status.get("confirmationStatus") in {"confirmed", "finalized"}:
                transaction = client.transaction(signature)
                if transaction is not None:
                    return transaction
        time.sleep(delay)
        delay = min(delay * 1.5, 1.0)
    raise TimeoutError(f"transaction confirmation timed out: {signature}")


def _account_key(value: Any) -> str:
    return str(value.get("pubkey")) if isinstance(value, dict) else str(value)


def _ui_amount(balance: dict[str, Any]) -> float:
    token = balance.get("uiTokenAmount", {})
    if token.get("uiAmountString") is not None:
        return float(str(token["uiAmountString"]))
    raw = float(token.get("amount", 0))
    divisor = float(10 ** int(token.get("decimals", 0)))
    return raw / divisor


def extract_fill(transaction: dict[str, Any], signature: str, wallet: str, mint: str, side: Side) -> Fill:
    meta = transaction.get("meta") or {}
    message = (transaction.get("transaction") or {}).get("message") or {}
    keys = [_account_key(value) for value in message.get("accountKeys", [])]
    if wallet not in keys:
        raise RpcError("confirmed transaction does not contain the configured wallet")
    index = keys.index(wallet)
    pre = meta.get("preBalances", [])
    post = meta.get("postBalances", [])
    if index >= len(pre) or index >= len(post):
        raise RpcError("confirmed transaction is missing wallet balance rows")
    pre_lamports, post_lamports = int(pre[index]), int(post[index])
    fee_lamports = int(meta.get("fee", 0))
    if side is Side.BUY:
        sol_amount = max(0, pre_lamports - post_lamports - fee_lamports) / 1_000_000_000
    else:
        sol_amount = max(0, post_lamports - pre_lamports + fee_lamports) / 1_000_000_000

    def token_total(rows: list[dict[str, Any]]) -> float:
        return sum(_ui_amount(row) for row in rows if row.get("mint") == mint and row.get("owner") == wallet)

    pre_tokens = token_total(meta.get("preTokenBalances", []))
    post_tokens = token_total(meta.get("postTokenBalances", []))
    delta = post_tokens - pre_tokens
    token_amount = max(0.0, delta if side is Side.BUY else -delta)
    if token_amount <= 0:
        raise RpcError("confirmed transaction has no expected wallet token delta")
    return Fill(
        signature=signature,
        mint=mint,
        side=side,
        token_amount=token_amount,
        sol_amount=sol_amount,
        fee_sol=fee_lamports / 1_000_000_000,
        slot=transaction.get("slot"),
        compute_units=meta.get("computeUnitsConsumed"),
    )
