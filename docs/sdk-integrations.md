# 程序化配置 MCP 与 Skills

三种官方 SDK 现在都能通过 **AgentFlow Java API** 管理扩展能力，不需要调用方自行实现 MCP 握手，也不连接 AI 服务的内部接口。

## 方法对照

| 能力 | Python | TypeScript | Java |
| --- | --- | --- | --- |
| Skills 列表 | `skills.list()` | `skills.list()` | `listSkills()` |
| Skills 详情 | `skills.get(name)` | `skills.get(name)` | `getSkill(name)` |
| 保存 SKILL.md | `skills.save(name, content)` | `skills.save(name, content)` | `saveSkill(name, content)` |
| 删除自定义技能 | `skills.delete(name)` | `skills.delete(name)` | `deleteSkill(name)` |
| 重载技能 | `skills.reload()` | `skills.reload()` | `reloadSkills()` |
| 引用资料 | `skills.reference(name, file)` | `skills.reference(name, file)` | `getSkillReference(name, file)` |
| MCP 列表 | `mcp.list()` | `mcp.list()` | `listMcpServers()` |
| 创建 MCP 配置 | `mcp.create(name, url, ...)` | `mcp.create(name, url, options)` | `createMcpServer(...)` |
| 完整更新配置 | `mcp.update(id, ...)` | `mcp.update(id, settings)` | `updateMcpServer(id, settings)` |
| 测试连接 / 发现 | `mcp.discover(id)` | `mcp.discover(id)` | `discoverMcpTools(id)` |
| 已授权工具 | `mcp.tools(id)` | `mcp.tools(id)` | `listMcpTools(id)` |
| 删除服务 | `mcp.delete(id)` | `mcp.delete(id)` | `deleteMcpServer(id)` |

代码示例见 [Python](../sdk/python/README.md#mcp-与-skills-管理)、[TypeScript](../sdk/typescript/README.md#mcp-与-skills-管理)、[Java](../sdk/java/README.md#mcp-与-skills-管理)。

## 推荐流程

```text
新建停用的 MCP 配置 → 发现工具并检查 ok → 明确选择工具 → 保存授权并启用 → 创建 / 执行工作流
```

- 创建默认不授权任何工具；不要把发现列表原样全部授权。
- `discover` 即使返回 HTTP 200，也可能是 `{ok:false,...}`。检查结果后再授权。
- 普通用户可以读取共享 Skills；保存、删除、重载仍要求管理员。SDK 不绕过平台权限。
- `skills.save` 会创建或覆盖同名自定义技能。运行示例前请换成未占用的技能标识，并保持正文 `name` 一致，避免覆盖已有指令。
- Skill 标识与引用文件名经过 SDK 检查，不能用它们拼接其他 API 路径。引用支持平台当前允许的 Markdown 文件名，不自动上传 `references`。
- MCP ID 必须是正整数；TypeScript 还要求安全整数，防止 JS 数值精度造成 ID 混淆。

## 更新语义与凭据

完整 MCP 更新必须提供 `name`、`url`、`allowedTools`、`timeoutMs`、`enabled`；Python 参数名为 snake_case。要求这些字段是为了防止部分修改悄悄重置权限、超时或启用状态。

| 意图 | Python | TypeScript / Java 配置 |
| --- | --- | --- |
| 保留认证 | 省略 `headers` | 省略 / null `headers` |
| 替换认证 | 传 `headers={...}` | 传非空 `headers` |
| 清除认证 | `clear_headers=True` | `clearHeaders=true` |

空请求头对象不是清除操作。变更 URL 时平台会清除旧凭据与发现结果；应传空工具授权列表，再重新发现和授权。不要把远程 MCP Token 当成 AgentFlow API Key，也不要把凭据写入工作流配置。

TypeScript 返回 `McpServer` 安全视图，未声明凭据字段；完整更新只发送请求字段，忽略 `id`、`tools` 和 `hasCredentials` 等元数据。Java 的 `McpServerSettings` 复制集合、避免外部修改，并在 `toString()` 中省略 URL / 认证请求头。

HTTP / 业务错误仍抛各 SDK 的 `ApiError` / `ApiException`；工作流执行失败必须另外检查 `status` 或 `run_failed`。MCP 操作期限与 SDK 请求期限不是同一个配置；Java SDK 自身的超时限制仍与其 README 中说明一致。

## 可运行 Python 示例

先安装本地 SDK，再在仓库根目录执行：

```bash
# 环境中预先设置 AGENTFLOW_API_KEY，可选 MCP_BEARER_TOKEN；不要把 Token 写进命令历史
python sdk/python/examples/mcp_workflow.py \
  --mcp-url https://your-server.example/mcp \
  --tool echo \
  --arguments '{"text":"{{input.text}}"}' \
  --input '{"text":"你好"}'
```

这会在平台创建新的 MCP 配置与工作流，默认不执行工具；使用 `--run` 才实际调用。每次运行创建新资源，不保证幂等；终端打印资源 ID，清理只能针对这些新 ID。配置阶段失败的新服务保持停用（若请求在启用提交之后才异常，需到配置页确认最终状态）。

工作流的 MCP 节点只保存以下内容，不携带远程凭据：

```json
{
  "id": "tool",
  "type": "mcp_tool",
  "config": {
    "serverId": "替换为配置 ID",
    "toolName": "echo",
    "arguments": "{\"text\":\"{{input.text}}\"}"
  }
}
```

Skills 挂载仍通过 `llm` / `react_agent` 的 `config.skillIds`；智能体 MCP 挂载使用 `config.mcpServerIds`。SDK 负责资源管理，实际工具调用由平台工作流完成。平台的网络、权限和执行边界见 [MCP 与 Skills 配置](mcp-skills.md)。

## 本轮验证

- Python SDK **47 项**、TypeScript SDK **25 项**、Java SDK **21 项**测试通过，本轮新增 **57 项** SDK / 示例回归。
- `make check` 的 **398 项测试**、类型检查与构建通过；Java SDK `mvn verify` 通过，JAR 包含 `McpServerSettings`。
- TypeScript 包名自引用可访问新增接口；打包清单包含 MCP / Skills 实现和类型声明，不包含测试产物。
- Python wheel 构建通过，并检查包含 MCP / Skills 资源模块。SDK 测试及包入口检查已纳入 CI。
- 示例默认不执行工具、仅在 `--run` 时调用，以及连接失败 / 工具缺失 / 执行失败的行为均用 mock API 回归。Java SDK 使用临时回环 HTTP 服务验证请求，不连接真实平台。
- 本轮没有对运行中的业务数据创建配置，没有新增真实 MCP / 模型联调，也没有重新运行浏览器 / 整栈测试。
