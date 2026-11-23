# Minimal demonstration of calling Agent Flow as a service via the SDK.
#
# Prerequisites:
#   pip install agentflow-sdk   (or run from this folder: pip install -e .)
#   A running Agent Flow backend (platform service on :8084) and a valid API Key.
#
# Set AGENTFLOW_BASE_URL and AGENTFLOW_API_KEY before running:
#   export AGENTFLOW_BASE_URL=http://127.0.0.1:8084
#   export AGENTFLOW_API_KEY=af_xxxxxxxxxxxxxxxx

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentflow import AgentFlowClient  # noqa: E402


def build_flow() -> dict:
    """input -> llm(mock) -> output"""
    return {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入",
             "position": {"x": 0, "y": 0}, "config": {"variables": ["topic"]}},
            {"id": "llm", "type": "llm", "name": "LLM",
             "position": {"x": 1, "y": 0},
             "config": {"provider": "mock", "model": "agentflow-mock",
                        "prompt": "用一句话介绍{{input.topic}}"}},
            {"id": "out", "type": "output", "name": "输出",
             "position": {"x": 2, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "llm"},
            {"id": "e2", "source": "llm", "target": "out"},
        ],
    }


def main() -> None:
    base_url = os.environ.get("AGENTFLOW_BASE_URL", "http://127.0.0.1:8084")
    api_key = os.environ.get("AGENTFLOW_API_KEY")

    client = AgentFlowClient(base_url, api_key=api_key)
    try:
        created = client.workflows.create("sdk-demo", build_flow())
        workflow_id = created["id"]
        print(f"created workflow id={workflow_id}")

        result = client.workflows.run(workflow_id, input={"topic": "LangGraph"})
        print("run status:", result["status"])
        print("outputs:", result["outputs"])

        client.workflows.delete(workflow_id)
        print("deleted workflow")
    finally:
        client.close()


if __name__ == "__main__":
    main()
