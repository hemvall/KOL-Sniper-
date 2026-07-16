from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .storage import Store


class HealthServer:
    def __init__(self, host: str, port: int, store: Store):
        self.store = store
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path not in {"/health", "/metrics"}:
                    self.send_error(404)
                    return
                if self.path == "/health":
                    metrics = outer.store.metrics()
                    last_signal = metrics.get("last_signal_at", 0)
                    payload: object = {
                        "status": "ok",
                        "time": time.time(),
                        "last_signal_age_seconds": time.time() - last_signal if last_signal else None,
                        "risk": outer.store.risk_snapshot(),
                    }
                else:
                    # Never expose order errors, signatures, mints, or positions
                    # from an unauthenticated operational endpoint.
                    payload = {"risk": outer.store.risk_snapshot(), "metrics": outer.store.metrics()}
                raw = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, name="health", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            self._server.server_close()
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
