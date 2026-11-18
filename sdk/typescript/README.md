# AgentFlow TypeScript SDK

适用于 Node.js 20+（原生 `fetch` / `ReadableStream` / `AbortSignal.timeout`），ESM 包，无运行时 npm 依赖。

## 本地构建与安装

当前 SDK 随源码提供；不要假定 npm 上的同名包就是本项目。

```bash
# 在仓库根目录执行
npm --prefix sdk/typescript install
npm --prefix sdk/typescript test
npm --prefix sdk/typescript run build
# 在调用方项目目录安装本地 SDK，替换为实际路径
npm install /absolute/path/to/agent-flow/sdk/typescript
```

生成可分发包：在 `sdk/typescript` 执行 `npm pack`，自动构建并生成 `agentflow-sdk-0.1.0.tgz`；调用方可通过 `npm install /path/to/agentflow-sdk-0.1.0.tgz` 安装。测试编译产物位于 `dist-test/`，不进入 npm 包。

## 调用示例

```typescript
import { AgentFlowClient } from "agentflow-sdk";

const client = new AgentFlowClient("http://127.0.0.1:8084", {
  apiKey: process.env.AGENTFLOW_API_KEY,
  timeout: 120_000,
});
const workflows = await client.workflows.list();
const workflowId = workflows.records[0].id; // 需要先创建一个可执行的工作流
const result = await client.workflows.run(workflowId, { topic: "LangGraph" }, { mock: true });
console.log(result.status, result.outputs);

for await (const [event, payload] of client.workflows.executeStream(workflowId, {}, { mock: true })) {
  console.log(event, payload);
}
```

也可传 `token: "JWT"`；两者同时存在时 API Key 优先。`timeout` 为正整数毫秒，默认 120000，限制整个请求（含流式响应消费）的时长，超时通过 `TimeoutError` 抛出。

HTTP 错误或非零业务码会抛出 `ApiError`。工作流自身失败通过结果的 `status == "FAILED"` 或 `run_failed` 事件表示，调用方必须检查。

SSE 增量解析 UTF-8 与跨块 CRLF，支持注释、默认 `message`、多行 JSON和无末尾空行；`break`、解析失败或网络异常时会取消响应体并释放 reader。关闭客户端连接不等价于取消后台执行；取消任务请调用 `POST /api/executions/{runId}/cancel`。

## MCP 与 Skills 管理

新增 `client.mcp`，以及导出的 `McpServer`、`McpServerUpdate`、`McpTool`、`McpDiscoveryResult` 和 Skills 类型。配置视图不含认证请求头。

```typescript
const client = new AgentFlowClient("http://127.0.0.1:8084", {
  apiKey: process.env.AGENTFLOW_API_KEY,
});
if (!process.env.MCP_URL) throw new Error("请设置 MCP_URL");
let server = await client.mcp.create("文档工具", process.env.MCP_URL, { enabled: false });
const probe = await client.mcp.discover(server.id);
if (!probe.ok) throw new Error(probe.message);
const tool = "echo"; // 只授权自己明确选择的工具
if (!probe.tools.some(item => item.name === tool)) throw new Error("目标工具不存在");
server = await client.mcp.update(server.id, { ...server, allowedTools: [tool], enabled: true });
console.log(server.id, await client.mcp.tools(server.id));

// 需要管理员权限；普通用户可 list / get / reference。
await client.skills.save("report-helper", "---\nname: report-helper\ndescription: 报告指令\n---\n不编造数据。\n");
console.log((await client.skills.get("report-helper")).content);
```

给 `create()` 的第三个参数或 `update()` 的配置传 `headers`，设置远程 MCP 认证；更新省略它会保留已有凭据，`clearHeaders: true` 才会明确清除。`update()` 的五个配置字段全部必填；SDK 只发送请求字段，忽略返回视图中的 `id`、`tools`、`hasCredentials` 等元数据。

`discover()` 返回 `ok: false` 时不一定抛异常，必须检查该字段。HTTP / 权限错误仍抛 `ApiError`。更多流程示例与权限说明见 [SDK 接入说明](../../docs/sdk-integrations.md)。
