#!/usr/bin/env python3
"""Load test for the API (Phase 15).

Logs in once, then fires concurrent GET requests at the read endpoints the
dashboard uses and reports throughput, latency percentiles and errors per
endpoint. Read-only: it never changes data and never publishes anything.

    LOAD_TEST_EMAIL=admin@example.com LOAD_TEST_PASSWORD=... \\
      python scripts/load_test.py --base-url http://127.0.0.1:8000 --users 20 --seconds 30

Exit code 1 if the error rate is above --max-error-rate or p95 above --max-p95-ms.
Needs only ``httpx`` (a backend dependency).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from collections import defaultdict

import httpx

ENDPOINTS = [
    "/api/health/ready",
    "/api/overview",
    "/api/agents",
    "/api/trends",
    "/api/analytics/overview?days=30",
    "/api/costs/summary",
    "/api/system/status",
]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[k]


async def worker(
    client: httpx.AsyncClient,
    deadline: float,
    offset: int,
    latencies: dict[str, list[float]],
    errors: dict[str, int],
) -> None:
    i = offset
    while time.monotonic() < deadline:
        path = ENDPOINTS[i % len(ENDPOINTS)]
        i += 1
        start = time.perf_counter()
        try:
            r = await client.get(path)
            ok = r.status_code < 400
        except httpx.HTTPError:
            ok = False
        latencies[path].append((time.perf_counter() - start) * 1000)
        if not ok:
            errors[path] += 1


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=int, default=20, help="concurrent clients")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=1000)
    args = parser.parse_args()
    email = os.environ.get("LOAD_TEST_EMAIL", "")
    password = os.environ.get("LOAD_TEST_PASSWORD", "")
    if not email or not password:
        print("LOAD_TEST_EMAIL und LOAD_TEST_PASSWORD setzen (Konto mit Leserechten).", file=sys.stderr)
        return 2

    limits = httpx.Limits(max_connections=args.users, max_keepalive_connections=args.users)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30, limits=limits) as client:
        r = await client.post("/api/auth/login", json={"email": email, "password": password})
        if r.status_code != 200:
            print(f"Anmeldung fehlgeschlagen: HTTP {r.status_code}", file=sys.stderr)
            return 2
        latencies: dict[str, list[float]] = defaultdict(list)
        errors: dict[str, int] = defaultdict(int)
        started = time.monotonic()
        deadline = started + args.seconds
        await asyncio.gather(
            *(worker(client, deadline, n, latencies, errors) for n in range(args.users))
        )
        elapsed = time.monotonic() - started

    total = sum(len(v) for v in latencies.values())
    failed = sum(errors.values())
    every = [ms for v in latencies.values() for ms in v]
    print(f"{args.users} gleichzeitige Clients, {elapsed:.0f} s, {total} Anfragen")
    print(f"{'Endpunkt':40} {'Anz.':>6} {'p50':>7} {'p95':>7} {'p99':>7} {'Fehler':>6}")
    for path in ENDPOINTS:
        v = latencies.get(path, [])
        print(
            f"{path:40} {len(v):6d} {percentile(v, 50):6.0f}ms {percentile(v, 95):6.0f}ms "
            f"{percentile(v, 99):6.0f}ms {errors.get(path, 0):6d}"
        )
    p95 = percentile(every, 95)
    rate = failed / total if total else 1.0
    print(
        f"Gesamt: {total / elapsed:.1f} Anfragen/s, Median {statistics.median(every):.0f} ms, "
        f"p95 {p95:.0f} ms, Fehlerquote {rate:.2%}"
    )
    if rate > args.max_error_rate or p95 > args.max_p95_ms:
        print("Grenzwerte überschritten.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
