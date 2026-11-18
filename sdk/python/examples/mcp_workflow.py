"""Explicitly configure an AgentFlow MCP workflow; never run a tool by default."""

import argparse
import json
import os

from agentflow import AgentFlowClient


def workflow(server_id, tool, arguments):
    return {
        "name": "SDK MCP 工具调用", "engineType": "langgraph",
        "nodes": [
            {"id": "start", "type": "input", "config": {}},
            {"id": "tool", "type": "mcp_tool", "config": {
                "serverId": str(server_id), "toolName": tool,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            }},
            {"id": "end", "type": "output", "config": {"mode": "key", "key": "outputs.tool"}},
        ],
        "edges": [{"source": "start", "target": "tool"}, {"source": "tool", "target": "end"}],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8084")
    parser.add_argument("--mcp-url", required=True)
    parser.add_argument("--tool", required=True, help="Explicit tool name to authorize, never all tools")
    parser.add_argument("--arguments", default='{"text":"{{input.text}}"}', help="JSON arguments matching the selected tool")
    parser.add_argument("--input", default='{"text":"hello"}', help="Runtime JSON object")
    parser.add_argument("--run", action="store_true", help="Actually invoke the authorized tool; may have side effects")
    args = parser.parse_args()
    key = os.environ.get("AGENTFLOW_API_KEY")
    if not key:
        parser.error("Set AGENTFLOW_API_KEY; credentials are not read from command-line arguments")
    try:
        arguments, input_data = json.loads(args.arguments), json.loads(args.input)
    except json.JSONDecodeError:
        parser.error("--arguments and --input must be valid JSON")
    if not isinstance(arguments, dict) or not isinstance(input_data, dict):
        parser.error("--arguments and --input must be JSON objects")
    remote_token = os.environ.get("MCP_BEARER_TOKEN")
    headers = {"Authorization": "Bearer " + remote_token} if remote_token else None
    with AgentFlowClient(args.base_url, api_key=key) as client:
        server = client.mcp.create("SDK MCP 示例", args.mcp_url, headers=headers, enabled=False)
        print("Created MCP service:", server["id"])
        probe = client.mcp.discover(server["id"])
        if not probe["ok"]:
            raise RuntimeError("MCP connection failed; the new service remains disabled. Check its configuration page.")
        if args.tool not in {tool["name"] for tool in probe["tools"]}:
            raise RuntimeError("Requested tool was not discovered; the new service remains disabled.")
        flow = client.workflows.create("SDK MCP 工具调用", workflow(server["id"], args.tool, arguments))
        print("Created workflow:", flow["id"])
        client.mcp.update(
            server["id"], name=server["name"], url=server["url"], allowed_tools=[args.tool],
            timeout_ms=server["timeoutMs"], enabled=True,
        )
        if args.run:
            result = client.workflows.run(flow["id"], input=input_data)
            if result["status"] != "SUCCESS":
                raise RuntimeError("Workflow did not succeed; inspect its execution record.")
            print(json.dumps(result["outputs"], ensure_ascii=False, indent=2))
        else:
            print("Configured only. No MCP tool was invoked; use --run to opt in.")


if __name__ == "__main__":
    main()
