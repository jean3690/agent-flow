#!/usr/bin/env python3
"""向运行中的整栈灌入演示数据：工作流、发布版本与执行记录。

用于录屏、截图和面试演示，避免对着空列表讲解::

    python3 e2e/seed_demo.py
    python3 e2e/seed_demo.py --reset   # 先删除同名演示工作流再重建
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_ROWS = json.dumps(
    [
        {"name": "华东-标准版", "score": 92, "region": "east"},
        {"name": "华南-试用版", "score": 71, "region": "south"},
        {"name": "华北-企业版", "score": 88, "region": "north"},
        {"name": "西南-标准版", "score": 64, "region": "west"},
        {"name": "总部-企业版", "score": 96, "region": "hq"},
    ],
    ensure_ascii=False,
)

TRIAGE_FLOW = {
    "name": "客服工单智能分诊",
    "description": "大模型意图识别 + 分诊结果模板；本地未配置 Key 时走 mock 输出",
    "engineType": "langgraph",
    "nodes": [
        {"id": "start", "type": "input", "name": "接收工单", "position": {"x": 60, "y": 160},
         "config": {"variables": ["ticket"]}},
        {"id": "classify", "type": "llm", "name": "意图识别与分派", "position": {"x": 360, "y": 160},
         "config": {
             "provider": "mock",
             "model": "agentflow-mock",
             "systemPrompt": "你是客服分诊助手，输出「分类 | 优先级 | 建议处理组」。",
             "prompt": "工单内容：{{input.ticket}}",
             "temperature": 0.2,
         }},
        {"id": "reply", "type": "template", "name": "生成分诊结果", "position": {"x": 660, "y": 160},
         "config": {"template": "分诊结果：{{outputs.classify.text}}"}},
        {"id": "end", "type": "output", "name": "返回", "position": {"x": 960, "y": 160},
         "config": {"mode": "template", "template": "{{outputs.reply.text}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "classify"},
        {"id": "e2", "source": "classify", "target": "reply"},
        {"id": "e3", "source": "reply", "target": "end"},
    ],
}


class Client:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = ""
        self.username = username
        self.password = password

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode('utf-8', 'ignore')}")
        if payload.get("code") != 0:
            raise SystemExit(f"{method} {path} -> {payload}")
        return payload.get("data")

    def login(self) -> None:
        self.token = self.request("POST", "/api/auth/login",
                                  {"username": self.username, "password": self.password})["token"]

    def find_workflow(self, name: str) -> int | None:
        page = self.request("GET", f"/api/workflows?page=1&size=100&keyword={urllib.parse.quote(name)}")
        for item in page.get("records", []):
            if item["name"] == name:
                return int(item["id"])
        return None


def ensure_workflow(client: Client, definition: dict, reset: bool) -> int:
    existing = client.find_workflow(definition["name"])
    if existing and reset:
        client.request("DELETE", f"/api/workflows/{existing}")
        existing = None
    if existing:
        return existing
    payload = {
        "name": definition["name"],
        "description": definition.get("description", ""),
        "engineType": "langgraph",
        "status": 1,
        "flow": definition,
    }
    return int(client.request("POST", "/api/workflows", payload)["id"])


def run(client: Client, workflow_id: int, data: dict) -> str:
    result = client.request("POST", f"/api/workflows/{workflow_id}/run", {"input": data})
    return result.get("status", "UNKNOWN")


def main() -> int:
    parser = argparse.ArgumentParser(description="灌入 AgentFlow 演示数据")
    parser.add_argument("--base-url", default="http://127.0.0.1:8084")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--reset", action="store_true", help="删除同名演示工作流后重建")
    args = parser.parse_args()

    client = Client(args.base_url, args.username, args.password)
    client.login()

    export_flow = json.loads((ROOT / "docs/examples/data-export.flow.json").read_text(encoding="utf-8"))
    export_flow["name"] = "订单数据清洗与 CSV 导出"
    export_flow["description"] = "JSON 解析 → 条件过滤 → 排序 → CSV 生成，全程无模型调用"

    export_id = ensure_workflow(client, export_flow, args.reset)
    triage_id = ensure_workflow(client, TRIAGE_FLOW, args.reset)

    print(f"数据导出工作流 id={export_id}")
    for _ in range(3):
        print("  执行:", run(client, export_id, {"raw": SAMPLE_ROWS}))
    print("  发布:", client.request("POST", f"/api/workflows/{export_id}/publish")["publishedVersion"])

    print(f"工单分诊工作流 id={triage_id}")
    tickets = [
        "客户反馈订单 20261118001 三天未发货，要求今天给出物流单号",
        "企业版账号无法登录，提示密码错误但已经重置两次",
        "想咨询发票抬头修改流程，以及是否可以开电子专票",
    ]
    for ticket in tickets:
        print("  执行:", run(client, triage_id, {"ticket": ticket}))
    print("  发布:", client.request("POST", f"/api/workflows/{triage_id}/publish")["publishedVersion"])
    print("演示数据已就绪")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())