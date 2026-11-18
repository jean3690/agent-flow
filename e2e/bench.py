#!/usr/bin/env python3
"""AgentFlow 同步执行入口的并发压测脚本。

默认流程：开始 → 文本模板 → 结束，不调用大模型，测的是
「Java 执行编排 + SSE 消费 + AI 服务构图 + 落库」这条主链路的开销。

用法::

    python3 e2e/bench.py --concurrency 20 --requests 400
    python3 e2e/bench.py --base-url http://127.0.0.1:8084 --api-key af_xxx

结果默认为本机单实例测量，只代表当前硬件与 H2/MySQL 配置下的表现，
不能直接当作生产容量结论。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

FLOW = {
    "name": "bench-sync",
    "engineType": "langgraph",
    "nodes": [
        {"id": "start", "type": "input", "name": "开始", "position": {"x": 0, "y": 0},
         "config": {"variables": ["topic"]}},
        {"id": "tmpl", "type": "template", "name": "文本模板", "position": {"x": 280, "y": 0},
         "config": {"template": "benchmark payload for {{input.topic}}"}},
        {"id": "end", "type": "output", "name": "结束", "position": {"x": 560, "y": 0},
         "config": {"mode": "template", "template": "{{outputs.tmpl.text}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "tmpl"},
        {"id": "e2", "source": "tmpl", "target": "end"},
    ],
}


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = max(0, min(len(sorted_values) - 1, int(round((pct / 100.0) * len(sorted_values) + 0.5)) - 1))
    return sorted_values[k]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AgentFlow 并发压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8084")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--requests", type=int, default=200, dest="total")
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--json", default="", help="把结果写入 JSON 文件")
    parser.add_argument("--keep", action="store_true", help="保留压测工作流")
    return parser.parse_args()


async def login(client: httpx.AsyncClient, args: argparse.Namespace) -> str:
    resp = await client.post("/api/auth/login",
                             json={"username": args.username, "password": args.password})
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise SystemExit(f"登录失败: {body}")
    return body["data"]["token"]


async def create_workflow(client: httpx.AsyncClient) -> int:
    resp = await client.post("/api/workflows", json={
        "name": f"bench-{int(time.time())}",
        "description": "e2e/bench.py 生成的压测工作流",
        "engineType": "langgraph",
        "status": 1,
        "flow": FLOW,
    })
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise SystemExit(f"创建工作流失败: {body}")
    return body["data"]["id"]


async def run_once(client: httpx.AsyncClient, workflow_id: int, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        started = time.perf_counter()
        try:
            resp = await client.post(f"/api/workflows/{workflow_id}/run",
                                     json={"input": {"topic": "agent-flow"}})
            elapsed = (time.perf_counter() - started) * 1000.0
            payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            ok = resp.status_code == 200 and payload.get("code") == 0 \
                and payload.get("data", {}).get("status") == "SUCCESS"
            return {"ok": ok, "ms": elapsed, "status": resp.status_code,
                    "error": "" if ok else str(payload)[:200]}
        except Exception as exc:  # noqa: BLE001 - 压测脚本需要把失败计入统计
            elapsed = (time.perf_counter() - started) * 1000.0
            return {"ok": False, "ms": elapsed, "status": 0, "error": f"{type(exc).__name__}: {exc}"}


async def main() -> int:
    args = parse_args()
    limits = httpx.Limits(max_connections=args.concurrency + 10,
                          max_keepalive_connections=args.concurrency + 10)
    headers = {}
    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout, limits=limits) as client:
        if args.api_key:
            headers["X-API-Key"] = args.api_key
        else:
            headers["Authorization"] = f"Bearer {await login(client, args)}"
        client.headers.update(headers)

        workflow_id = await create_workflow(client)
        print(f"压测工作流 id={workflow_id}，预热 {args.warmup} 次，正式 {args.total} 次 / 并发 {args.concurrency}")
        semaphore = asyncio.Semaphore(args.concurrency)
        try:
            for _ in range(args.warmup):
                result = await run_once(client, workflow_id, semaphore)
                if not result["ok"]:
                    raise SystemExit(f"预热失败: {result}")

            started = time.perf_counter()
            results = await asyncio.gather(
                *(run_once(client, workflow_id, semaphore) for _ in range(args.total)))
            wall = time.perf_counter() - started
        finally:
            if not args.keep:
                await client.delete(f"/api/workflows/{workflow_id}")

    latencies = sorted(item["ms"] for item in results if item["ok"])
    failures = [item for item in results if not item["ok"]]
    summary = {
        "base_url": args.base_url,
        "concurrency": args.concurrency,
        "requests": args.total,
        "success": len(latencies),
        "failed": len(failures),
        "wall_seconds": round(wall, 3),
        "throughput_rps": round(len(latencies) / wall, 2) if wall > 0 else 0.0,
        "latency_ms": {
            "min": round(min(latencies), 1) if latencies else 0.0,
            "mean": round(statistics.fmean(latencies), 1) if latencies else 0.0,
            "p50": round(percentile(latencies, 50), 1),
            "p90": round(percentile(latencies, 90), 1),
            "p95": round(percentile(latencies, 95), 1),
            "p99": round(percentile(latencies, 99), 1),
            "max": round(max(latencies), 1) if latencies else 0.0,
        },
        "first_errors": [item["error"] for item in failures[:5]],
    }

    print()
    print(f"成功 {summary['success']} / 失败 {summary['failed']}，"
          f"总耗时 {summary['wall_seconds']}s，吞吐 {summary['throughput_rps']} req/s")
    lat = summary["latency_ms"]
    print(f"延迟(ms): p50={lat['p50']} p90={lat['p90']} p95={lat['p95']} "
          f"p99={lat['p99']} mean={lat['mean']} max={lat['max']}")
    for error in summary["first_errors"]:
        print(f"  失败样例: {error}")

    if args.json:
        Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {args.json}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))