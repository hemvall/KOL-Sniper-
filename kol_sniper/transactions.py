from __future__ import annotations

import base64
import json
import logging
import os
import queue
import subprocess
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import requests

from .domain import BuildRequest, BuiltTransaction
from .errors import safe_error

logger = logging.getLogger(__name__)


class BuilderUnavailable(RuntimeError):
    pass


def load_keypair(secret: str):
    try:
        from solders.keypair import Keypair
    except ImportError as exc:
        raise RuntimeError("solders is required for live transaction signing") from exc
    value = secret.strip()
    if value.startswith("["):
        raw = bytes(json.loads(value))
        if len(raw) != 64:
            raise ValueError("PRIVATE_KEY JSON must contain 64 bytes")
        return Keypair.from_bytes(raw)
    return Keypair.from_base58_string(value)


def decode_transaction(encoded: str, encoding: str = "base64"):
    try:
        from solders.transaction import VersionedTransaction
    except ImportError as exc:
        raise RuntimeError("solders is required to decode transactions") from exc
    if encoding == "base64":
        raw = base64.b64decode(encoded, validate=True)
    elif encoding == "base58":
        from .parser import base58_decode

        raw = base58_decode(encoded)
    else:
        raise ValueError(f"unsupported transaction encoding: {encoding}")
    return VersionedTransaction.from_bytes(raw)


def sign_transaction(transaction: Any, keypair: Any) -> tuple[str, str]:
    try:
        from solders.transaction import VersionedTransaction
    except ImportError as exc:
        raise RuntimeError("solders is required to sign transactions") from exc
    signed = VersionedTransaction(transaction.message, [keypair])
    signature = str(signed.signatures[0])
    encoded = base64.b64encode(bytes(signed)).decode("ascii")
    return encoded, signature


class TransactionBuilder(ABC):
    @abstractmethod
    def build(self, request: BuildRequest) -> BuiltTransaction:
        raise NotImplementedError

    def warm(self) -> None:
        return

    def close(self) -> None:
        return


class PumpPortalBuilder(TransactionBuilder):
    def __init__(self, url: str, timeout_seconds: float = 4.0):
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": "kol-sniper/2"})
            self._local.session = session
        return session

    def build(self, request: BuildRequest) -> BuiltTransaction:
        payload = {
            "publicKey": request.wallet,
            "action": request.side.value,
            "mint": request.mint,
            "amount": request.amount,
            "denominatedInSol": "false" if request.amount_in_tokens else "true",
            "slippage": request.slippage_bps / 100,
            "priorityFee": request.priority_fee_sol,
            "pool": request.pool,
        }
        response = self._session().post(self.url, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("PumpPortal returned an empty transaction")
        return BuiltTransaction(
            encoded=base64.b64encode(response.content).decode("ascii"),
            builder="pumpportal",
            includes_priority_fee=request.priority_fee_sol > 0,
            includes_sender_tip=False,
        )


class LocalPumpBuilder(TransactionBuilder):
    """Persistent JSON-lines bridge to the official TypeScript Pump SDK."""

    def __init__(self, command: tuple[str, ...], timeout_seconds: float = 4.0, rpc_url: str = ""):
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.rpc_url = rpc_url
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()

    def _start(self) -> subprocess.Popen[str]:
        if self._process and self._process.poll() is None:
            return self._process
        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=Path(__file__).resolve().parent.parent,
                env={"PATH": os.environ.get("PATH", ""), "NODE_ENV": "production", "RPC_URL": self.rpc_url},
            )
        except OSError as exc:
            raise BuilderUnavailable("local builder could not start") from exc
        process = self._process
        self._responses = queue.Queue()
        responses = self._responses

        def read_stdout() -> None:
            if process.stdout:
                for line in process.stdout:
                    responses.put(line)
            responses.put("")

        def read_stderr() -> None:
            if process.stderr:
                for line in process.stderr:
                    logger.warning("local builder: %s", safe_error(RuntimeError(line.rstrip())))

        threading.Thread(target=read_stdout, name="pump-builder-stdout", daemon=True).start()
        threading.Thread(target=read_stderr, name="pump-builder-stderr", daemon=True).start()
        return self._process

    def _exchange(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            process = self._start()
            if process.stdin is None:
                raise RuntimeError("local builder pipes are unavailable")
            process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            process.stdin.flush()
            try:
                line = self._responses.get(timeout=self.timeout_seconds)
            except queue.Empty as exc:
                process.kill()
                process.wait(timeout=2)
                self._process = None
                raise BuilderUnavailable(f"local builder exceeded {self.timeout_seconds:g}s") from exc
            if not line:
                self._process = None
                raise BuilderUnavailable("local builder stopped unexpectedly")
        result: dict[str, Any] = json.loads(line)
        if not result.get("ok"):
            message = safe_error(RuntimeError(str(result.get("error", "local builder failed"))))
            raise RuntimeError(message)
        return result

    def warm(self) -> None:
        self._exchange({"action": "warmup"})

    def build(self, request: BuildRequest) -> BuiltTransaction:
        result = self._exchange(
            {
                "action": request.side.value,
                "mint": request.mint,
                "wallet": request.wallet,
                "amount": request.amount,
                "amountInTokens": request.amount_in_tokens,
                "slippageBps": request.slippage_bps,
                "priorityFeeSol": request.priority_fee_sol,
                "tipSol": request.tip_sol,
                "tipAccount": request.tip_account,
            }
        )
        return BuiltTransaction(
            encoded=str(result["transaction"]),
            builder="official-pump-sdk",
            includes_priority_fee=bool(result.get("includesPriorityFee")),
            includes_sender_tip=bool(result.get("includesSenderTip")),
            metadata={
                "pool": result.get("pool", "bonding-curve"),
                "lastValidBlockHeight": result.get("lastValidBlockHeight"),
            },
        )

    def close(self) -> None:
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None


class IsolatedPumpBuilder(TransactionBuilder):
    """HTTP client for a separately sandboxed official-SDK builder service."""

    def __init__(self, url: str, timeout_seconds: float = 4.0):
        self.url = url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": "kol-sniper-builder-client/2"})
            self._local.session = session
        return session

    def _exchange(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._session().post(f"{self.url}/build", json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            result: dict[str, Any] = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise BuilderUnavailable(f"isolated builder transport failure ({type(exc).__name__})") from None
        if not result.get("ok"):
            message = safe_error(RuntimeError(str(result.get("error", "isolated builder failed"))))
            raise RuntimeError(message)
        return result

    def warm(self) -> None:
        self._exchange({"action": "warmup"})

    def build(self, request: BuildRequest) -> BuiltTransaction:
        result = self._exchange(
            {
                "action": request.side.value,
                "mint": request.mint,
                "wallet": request.wallet,
                "amount": request.amount,
                "amountInTokens": request.amount_in_tokens,
                "slippageBps": request.slippage_bps,
                "priorityFeeSol": request.priority_fee_sol,
                "tipSol": request.tip_sol,
                "tipAccount": request.tip_account,
            }
        )
        return BuiltTransaction(
            encoded=str(result["transaction"]),
            builder="isolated-official-pump-sdk",
            includes_priority_fee=bool(result.get("includesPriorityFee")),
            includes_sender_tip=bool(result.get("includesSenderTip")),
            metadata={
                "pool": result.get("pool", "bonding-curve"),
                "lastValidBlockHeight": result.get("lastValidBlockHeight"),
            },
        )


class FallbackBuilder(TransactionBuilder):
    def __init__(self, primary: TransactionBuilder, fallback: TransactionBuilder, enabled: bool):
        self.primary = primary
        self.fallback = fallback
        self.enabled = enabled

    def build(self, request: BuildRequest) -> BuiltTransaction:
        try:
            return self.primary.build(request)
        except BuilderUnavailable:
            if not self.enabled:
                raise
            return self.fallback.build(request)

    def close(self) -> None:
        self.primary.close()

    def warm(self) -> None:
        try:
            self.primary.warm()
        except BuilderUnavailable:
            if not self.enabled:
                raise
