# AgentFlow Python SDK

适用于 Python 3.9+。通过 API Key 或 JWT 调用平台服务，自动解包业务响应，并支持同步执行与 SSE 逐事件消费。

## 本地安装

当前 SDK 随源码提供；不要假定 PyPI 上的同名包就是本项目。

```bash
# 在仓库根目录执行
python -m pip install -e ./sdk/python
# 开发与测试
python -m pip install -e './sdk/python[dev]'
python -m pytest sdk/python/tests -q
```

## 调用示例

```python
import os
from agentflow import AgentFlowClient, ApiError

with AgentFlowClient("http://127.0.0.1:8084", api_key=os.environ["AGENTFLOW_API_KEY"]) as client:
    workflows = client.workflows.list()
    workflow_id = workflows["records"][0]["id"]  # 需要先创建一个可执行的工作流
    result = client.workflows.run(workflow_id, input={"topic": "LangGraph"}, mock=True)
    print(result["status"], result["outputs"])

    for event, payload in client.workflows.execute_stream(workflow_id, input={}, mock=True):
        print(event, payload)
```

也可传 `token="JWT"`；两者同时存在时 API Key 优先。`timeout` 单位为秒，默认 120 秒，遵循 HTTPX 的连接/读写/连接池超时语义，不是整个流的总时长限制。

HTTP 错误或非零业务码会抛出 `ApiError`。工作流自身失败通过结果的 `status == "FAILED"` 或 `run_failed` 事件表示，调用方必须检查。

SSE 支持 LF/CRLF/CR、UTF-8、注释、默认 `message` 事件和多行 JSON；兼容末尾缺少空行的响应。提前退出迭代时请调用生成器的 `close()`，释放 HTTP 连接：

```python
events = client.workflows.execute_stream(workflow_id)
try:
    for event, payload in events:
        if event == "run_started":
            break
finally:
    events.close()
```

关闭客户端连接只释放调用方连接，不等价于取消后台执行。取消任务请调用 `POST /api/executions/{runId}/cancel`。

## MCP 与 Skills 管理

`client.mcp` 调用 AgentFlow 的管理 API，不是直接连接 MCP 服务。新建服务没有授权工具，先发现，再明确授权：

```python
import os
from agentflow import AgentFlowClient

with AgentFlowClient("http://127.0.0.1:8084", api_key=os.environ["AGENTFLOW_API_KEY"]) as client:
    server = client.mcp.create("文档工具", os.environ["MCP_URL"], enabled=False)
    probe = client.mcp.discover(server["id"])
    if not probe["ok"]:
        raise RuntimeError(probe["message"])  # 新配置保持停用，不授权工具
    tool = "echo"  # 替换为你明确允许的工具，不自动授权全部发现结果
    if tool not in {item["name"] for item in probe["tools"]}:
        raise RuntimeError("目标工具不存在")
    server = client.mcp.update(
        server["id"], name=server["name"], url=server["url"],
        allowed_tools=[tool], timeout_ms=server["timeoutMs"], enabled=True,
    )
    print(server["id"], client.mcp.tools(server["id"]))
```

需要认证时给 `create()` 或 `update()` 传 `headers={"Authorization": "Bearer ..."}`。这些是 **MCP 服务**的凭据，独立于客户端的 AgentFlow API Key。更新时省略 `headers` 会保留已有认证；传 `clear_headers=True` 明确清除。地址变更会由服务端清除旧凭据和发现结果，需重新发现 / 授权。更新是完整替换配置，`name`、`url`、`allowed_tools`、`timeout_ms`、`enabled` 为必填。

Skills 的读取可供普通用户使用，保存 / 删除 / 重载需要管理员：

```python
content = "---\nname: report-helper\ndescription: 组织可核查的报告\n---\n\n不编造数据。\n"
with AgentFlowClient("http://127.0.0.1:8084", api_key=os.environ["AGENTFLOW_API_KEY"]) as client:
    skill = client.skills.save("report-helper", content)
    print(client.skills.get(skill["name"])["content"])
    # 仅在技能已包含该引用文件时读取；save() 不上传 references。
    # print(client.skills.reference(skill["name"], "guide.md")["content"])
    # client.skills.delete(skill["name"])
```

可运行示例：[examples/mcp_workflow.py](examples/mcp_workflow.py)。默认只创建 / 配置服务与工作流；加 `--run` 才会实际调用工具。它会写入平台配置，连接失败或目标工具缺失时新服务保持停用；执行失败不会自动撤销授权，清理请按示例返回的 ID 操作。

完整 API 对照、权限与流程定义见 [SDK 接入说明](../../docs/sdk-integrations.md)。
