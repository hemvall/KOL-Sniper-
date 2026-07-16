from __future__ import annotations

import argparse
import asyncio
import statistics
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from kol_sniper.config import Settings
from kol_sniper.runtime import create_runtime

MINTS = (
    "4t1xhKJd6oFGr98oWJoxYjLU74eFe7xiYSRDoX18pump",
    "HHi9GXkuBchA2LugrZvTLNhzoChAZFkvQNjeDagcpump",
    "HM2SSkV3FrLhdZQo3PSZFezYXbEHi3U1icvJmYZqpump",
)


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * percentile_value))
    return ordered[index]


async def run(iterations: int) -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = replace(
            Settings.from_env(),
            dry_run=True,
            database_path=Path(directory) / "benchmark.db",
            max_pending_orders=max(2, iterations),
            max_open_positions=max(4, iterations),
            mint_cooldown_seconds=0,
        )
        runtime = create_runtime(settings)
        timings: list[float] = []
        try:
            for index in range(iterations):
                started = time.perf_counter()
                await runtime.service.handle_signal(
                    source="benchmark",
                    message_id=str(index),
                    text=f"pump.fun/coin/{MINTS[index % len(MINTS)]}",
                )
                timings.append((time.perf_counter() - started) * 1_000)
        finally:
            await runtime.close()
        print(
            f"dry-run pipeline n={iterations} median={statistics.median(timings):.2f}ms "
            f"p95={percentile(timings, 0.95):.2f}ms max={max(timings):.2f}ms"
        )
        print("This excludes builder, RPC propagation and on-chain confirmation latency.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--iterations", type=int, default=100)
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("iterations must be positive")
    asyncio.run(run(args.iterations))


if __name__ == "__main__":
    main()
