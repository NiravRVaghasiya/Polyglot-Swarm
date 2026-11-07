"""Load test: realistic learner journeys against a real API process (ADR-0035).

Starts ``uvicorn src.api.app:app`` (one worker, as in production) on a fresh
temporary data directory with the deterministic LLM, optionally with
simulated provider latency, seeds learner accounts, then runs complete
learner journeys at increasing concurrency:

    learner plan -> start session -> 3 chat turns -> due reviews
    -> submit a review -> progress overview -> end session

Each step is timed per endpoint. The deterministic LLM means the numbers
measure the **application** (routing, agents, SQLite, evidence, learner
model) plus the simulated wait, not a real provider's latency or quality.

    python ops/loadtest.py --levels 1 5 10 25 --journeys 3 --llm-latency-ms 0 600
    python ops/loadtest.py --out docs/production/loadtest-results.json
    python ops/loadtest.py --levels 1 --llm-latency-ms 600 --think-ms 0 3000

``--think-ms`` pauses between chat turns, standing in for the learner reading
the reply and typing the next message. A turn's analysis runs after its reply
(``src.api.sessions``) and the next turn waits for it, so with no pause the
next turn absorbs that wait; with a realistic pause it overlaps the learner.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _env(data: Path, latency_ms: float) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "DATA_DIR": str(data),
            "DB_PATH": str(data / "polyglot.db"),
            "PROFILES_DIR": str(data / "user_profiles"),
            "CHROMA_PATH": str(data / "chroma"),
            "POLYGLOT_DETERMINISTIC": "1",
            "POLYGLOT_FAKE_LATENCY_MS": str(latency_ms),
            "USER_RATE_LIMIT_PER_MINUTE": "100000",
            "LLM_USER_DAILY_CALLS": "0",
            "LLM_USER_DAILY_BUDGET_USD": "0",
            "MAINTENANCE_INTERVAL_SECONDS": "0",
            "LOG_LEVEL": "WARNING",
            "TELEMETRY_ENABLED": "true",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def _seed_users(env: dict[str, str], n: int) -> list[str]:
    """Create ``n`` learners in the temp database; returns bearer tokens."""
    code = (
        "import json,sys\n"
        "from src.memory import schema\n"
        "from src.api import auth\n"
        "schema.init_all()\n"
        "out=[]\n"
        f"for i in range({n}):\n"
        "    auth.register(f'load-{i}', 'load-test-password')\n"
        "    out.append(auth.login(f'load-{i}', 'load-test-password'))\n"
        "print(json.dumps(out))\n"
    )
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
        check=True,
    )  # fmt: skip
    tokens: list[str] = json.loads(proc.stdout.strip().splitlines()[-1])
    return tokens


class Recorder:
    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = defaultdict(list)
        self.errors: dict[str, int] = defaultdict(int)
        self.statuses: dict[str, int] = defaultdict(int)

    async def call(self, client: httpx.AsyncClient, label: str, method: str, url: str,
                   **kw: Any) -> httpx.Response | None:  # fmt: skip
        t0 = time.perf_counter()
        try:
            resp = await client.request(method, url, **kw)
        except httpx.HTTPError:
            self.errors[label] += 1
            self.statuses["exception"] += 1
            return None
        self.samples[label].append((time.perf_counter() - t0) * 1000)
        self.statuses[str(resp.status_code)] += 1
        if resp.status_code >= 400:
            self.errors[label] += 1
        return resp


async def journey(
    client: httpx.AsyncClient, rec: Recorder, token: str, n: int, think_s: float = 0.0
) -> None:
    h = {"Authorization": f"Bearer {token}"}
    await rec.call(client, "GET learner/plan", "GET", "/api/v1/learner/plan", headers=h)
    start = await rec.call(
        client, "POST sessions/start", "POST", "/api/v1/sessions/start",
        json={"language": "Spanish"}, headers=h,
    )  # fmt: skip
    if start is None or start.status_code != 200:
        return
    sid = start.json()["session_id"]
    for i, msg in enumerate(("hola, quiero un café", "ayer fui al mercado", "me gusta leer")):
        if i and think_s:
            await asyncio.sleep(think_s)
        await rec.call(
            client, "POST chat", "POST", "/api/v1/chat",
            json={"session_id": sid, "message": f"{msg} ({n}.{i})"}, headers=h,
        )  # fmt: skip
    await rec.call(client, "GET review/due", "GET", "/api/v1/review/due", headers=h)
    await rec.call(
        client, "POST review/submit", "POST", "/api/v1/review/submit",
        json={"word": "café", "correct": True}, headers=h,
    )  # fmt: skip
    await rec.call(client, "GET progress/overview", "GET", "/api/v1/progress/overview", headers=h)
    await rec.call(client, "POST sessions/end", "POST", f"/api/v1/sessions/{sid}/end", headers=h)


def _pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


async def run_level(
    base: str, tokens: list[str], concurrency: int, journeys: int, think_ms: float = 0.0
) -> dict[str, Any]:
    rec = Recorder()
    limits = httpx.Limits(max_connections=concurrency + 5)
    async with httpx.AsyncClient(base_url=base, timeout=120.0, limits=limits) as client:
        t0 = time.perf_counter()

        async def user(u: int) -> None:
            for j in range(journeys):
                await journey(client, rec, tokens[u], j, think_ms / 1000)

        await asyncio.gather(*(user(u) for u in range(concurrency)))
        wall = time.perf_counter() - t0
    total = sum(len(v) for v in rec.samples.values()) + rec.statuses.get("exception", 0)
    errors = sum(rec.errors.values())
    endpoints = {
        label: {
            "n": len(v),
            "p50_ms": round(statistics.median(v), 1),
            "p95_ms": round(_pct(v, 0.95), 1),
            "p99_ms": round(_pct(v, 0.99), 1),
            "max_ms": round(max(v), 1),
            "errors": rec.errors.get(label, 0),
        }
        for label, v in sorted(rec.samples.items())
    }
    non_llm = [
        x for label, v in rec.samples.items()
        if label not in ("POST chat", "POST sessions/end") for x in v
    ]  # fmt: skip
    return {
        "concurrency": concurrency,
        "think_ms": think_ms,
        "journeys": concurrency * journeys,
        "requests": total,
        "wall_s": round(wall, 2),
        "throughput_rps": round(total / wall, 2),
        "journeys_per_min": round(concurrency * journeys / wall * 60, 1),
        "error_rate": round(errors / max(1, total), 4),
        "statuses": dict(rec.statuses),
        "non_llm_p95_ms": round(_pct(non_llm, 0.95), 1),
        "endpoints": endpoints,
    }


def _server(env: dict[str, str], port: int) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "uvicorn", "src.api.app:app", "--host", "127.0.0.1",
         "--port", str(port), "--workers", "1", "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip


def _rss_mb(pid: int) -> float | None:
    try:
        import psutil  # type: ignore[import-untyped, unused-ignore]

        return round(psutil.Process(pid).memory_info().rss / 2**20, 1)
    except Exception:  # noqa: BLE001 - optional measurement
        return None


def run(
    levels: list[int], journeys: int, latencies: list[float], thinks: list[float]
) -> dict[str, Any]:
    results: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpus": os.cpu_count(),
        },  # fmt: skip
        "llm": "deterministic fake (no network), simulated latency per call as listed",
        "runs": [],
    }
    for latency in latencies:
        with tempfile.TemporaryDirectory(
            prefix="polyglot-load-", ignore_cleanup_errors=True
        ) as tmp:
            data = Path(tmp)
            env = _env(data, latency)
            tokens = _seed_users(env, max(levels))
            port = _free_port()
            proc = _server(env, port)
            base = f"http://127.0.0.1:{port}"
            try:
                for _ in range(120):
                    try:
                        if httpx.get(f"{base}/ready", timeout=2).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.5)
                else:
                    raise RuntimeError("server did not become ready")
                for think, level in ((t, lv) for t in thinks for lv in levels):
                    out = asyncio.run(run_level(base, tokens, level, journeys, think))
                    out["llm_latency_ms"] = latency
                    out["server_rss_mb"] = _rss_mb(proc.pid)
                    results["runs"].append(out)
                    print(
                        f"latency={latency:>5.0f}ms think={think:>5.0f}ms c={level:>3} "
                        f"rps={out['throughput_rps']:>7} "
                        f"journeys/min={out['journeys_per_min']:>7} err={out['error_rate']:.2%} "
                        f"non-LLM p95={out['non_llm_p95_ms']}ms "
                        f"chat p95={out['endpoints'].get('POST chat', {}).get('p95_ms')}ms"
                    )
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--levels", type=int, nargs="+", default=[1, 5, 10, 25, 50])
    ap.add_argument("--journeys", type=int, default=2, help="journeys per virtual user")
    ap.add_argument("--llm-latency-ms", type=float, nargs="+", default=[0.0, 600.0])
    ap.add_argument(
        "--think-ms", type=float, nargs="+", default=[0.0], help="pause between chat turns"
    )
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    results = run(args.levels, args.journeys, args.llm_latency_ms, args.think_ms)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
