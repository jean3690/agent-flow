# MCP 与 Skills 配置

本轮把扩展能力做进 AgentFlow 本身，不是配置 OpenCode。前端新增「Skills」「MCP」管理页；工作流列表可直接进入。

后续两种 SDK 也已补齐管理接口与示例，见 [程序化配置 MCP 与 Skills](sdk-integrations.md)。本文末尾保留管理功能阶段的验证记录，最新测试总数以 README 为准。

## Skills：平台共享指令

1. 管理员进入 **Skills**，新建技能或导入单个 `SKILL.md`。
2. 填写小写技能标识及带 YAML Frontmatter 的正文，保存。
3. 在大模型 / 智能体节点的「挂载技能」选择所需技能，保存工作流。

示例：

```markdown
---
name: report-helper
title: 报告助手
description: 组织清晰且可核查的报告
version: 1.0.0
tags: [报告]
---

先明确问题与资料，再给出结论。不编造数据，对不确定的信息明确标注。
```

- 内置技能只读，可复制为自定义技能；普通用户可查看与挂载，只有管理员能保存、删除、重载平台共享技能。
- 自定义技能保存在 `AI_MANAGED_SKILLS_DIR`（默认 `./data/skills`），与内置目录分开；Docker 使用持久化的 `/srv/data/skills`。
- 技能名称必须与正文里的 `name` 一致；保存采用原子替换，禁止目录越界与技能目录中的符号链接。
- 正文最多 200,000 字符，支持查看 `references/*.md`。本轮导入仅支持单个 Markdown 文件，不支持 ZIP 包或引用文件上传；引用资料仍可由部署者放入对应技能目录。
- 技能是指令 / 资料，不自动执行脚本，也不安装技能声明的工具。智能体的 `load_skill` 工具在配置了 `skillIds` 时只能加载已挂载的技能。
- `version` 当前是描述性元数据，不是不可变版本存储；工作流引用技能名称，后续执行读取最新已保存正文。

## MCP：远程 Streamable HTTP 工具

1. 进入 **MCP**，添加服务名称、HTTP(S) 端点地址。
2. 如需认证，在请求头填写 JSON，例如：

   ```json
   {"Authorization": "Bearer your-token"}
   ```

3. 保存配置，再点击 **测试连接 / 发现工具**。
4. 勾选允许调用的工具，**再次保存配置**。发现工具本身不授予调用权限；初始配置默认没有任何授权工具。
5. 接入工作流：
   - **MCP 工具节点**：选择服务与工具，按展示的参数结构填写 JSON，支持模板引用与原生数值 / 数组。
   - **智能体节点**：挂载 MCP 服务，模型仅能选择该服务中明确授权的工具。

参数示例：

```json
{"query": "{{input.topic}}", "limit": "{{input.limit}}"}
```

MCP 工具输出为 `text`、`data`、`content`、`serverId`、`toolName`。`data` 是服务返回的 `structuredContent`，没有结构化结果时为 null；内容块仍保留在 `content`，文本块拼接到 `text`。不自动把 JSON 文本猜测成结构化结果，需要时接 JSON 解析节点。

### 权限与凭据

- MCP 服务按创建用户隔离；管理员可管理全部配置。列表、删除、发现工具、工作流提交都校验权限，越权返回 404。
- 认证请求头整体经 AES-GCM 加密存入 平台数据库。前端只看到「是否已保存认证」，不回显请求头或密文。
- 编辑时留空请求头保留已有认证，明确勾选「清除已有认证」才能清除；修改端点地址会清掉旧目的地的凭据和发现结果，避免旧 Token 被发送到新地址。
- 工作流 JSON 只保存服务 ID / 工具名称，不保存端点凭据。平台服务在提交执行时只注入当前流程及其递归子流程引用、启用且有权限的配置；排队前完成权限检查。
- 发现工具只条件更新工具声明，不覆盖其他配置；如果地址或认证在发现过程中改变，需重新测试连接。
- 关闭服务 / 修改授权影响后续提交，不自动取消已提交或正在运行的任务；需在执行中心手动取消。

### 网络与执行限制

- 首期仅支持 Streamable HTTP，不支持本地 `stdio`、命令执行、旧版 SSE Transport、OAuth 自动登录或 Resources / Prompts 浏览。
- 默认拒绝内网 / 回环地址，检查 DNS 的全部结果；需要本地 MCP 时，**部署者**可设置精确的 `AI_MCP_PRIVATE_HOSTS=127.0.0.1,localhost`，不支持通配符。页面不能修改此策略。
- 带认证的公网连接必须使用 HTTPS；HTTP 认证只允许部署白名单中的主机。禁止 URL 账号密码、查询参数、跨源重定向和连接相关请求头覆盖。
- DNS 检查与实际连接仍有重绑定时间窗口，不能替代网络隔离；生产请配合出口防火墙 / 专用代理和明确允许的 MCP 服务清单。私网白名单意味着信任该主机，不宜开放给不可信服务。
- 每次操作有 1–60 秒总期限；最多发现 100 个工具 / 5 页，每个 HTTP 响应最多 2 MB，工具声明、参数与结果另外限制为 200,000 字符。一个智能体最多挂载 64 个工具。
- 智能体模拟模式不连接 MCP；独立 MCP 工具节点属于显式外部调用，不因模型 mock 模式而模拟。
- MCP / 模型返回属于外部不可信数据。权限允许不代表工具无副作用；有写入、删除等效果的工具应谨慎授权，失败重试可能重复执行副作用。

## API

所有 平台 API 仍使用 JWT / API Key 和 `{code,message,data}`。

| 接口 | 用途 |
| --- | --- |
| `GET /api/skills` | 共享技能列表 |
| `GET /api/skills/{name}` | 正文、原始 SKILL.md 与引用列表 |
| `PUT /api/skills/{name}` | 管理员保存，body: `{content}` |
| `DELETE /api/skills/{name}` | 管理员删除自定义技能 |
| `POST /api/skills/reload` | 管理员重载 |
| `GET /api/skills/{name}/references/{file}` | 读取 Markdown 引用资料 |
| `GET /api/mcp-servers` | 可访问的 MCP 配置，不含凭据 |
| `POST /api/mcp-servers` | 创建配置 |
| `PUT /api/mcp-servers/{id}` | 更新配置 / 授权工具 |
| `DELETE /api/mcp-servers/{id}` | 删除配置 |
| `POST /api/mcp-servers/{id}/discover` | 测试连接并发现工具 |
| `GET /api/mcp-servers/{id}/tools` | 已授权工具的参数声明 |

MCP 创建 / 更新字段：`name`、`url`、`headers?`、`clearHeaders`、`allowedTools`、`timeoutMs`、`enabled`。不接受本地进程命令配置。

## 升级与部署

- 更新 AI 依赖：仓库根目录执行 `ai-service/.venv/bin/pip install -e './ai-service[dev]'`。使用官方 MCP Python SDK 1.x 的 Streamable HTTP 客户端。
- 重启 AI 与平台服务，再刷新浏览器。SQLite / MySQL 启动时由 SQLAlchemy 自动创建 `mcp_server` 表。
- 两端 `AI_INTERNAL_TOKEN` 必须一致，生产替换默认值；新的技能写接口、MCP 发现接口，以及携带 MCP 配置的 AI 执行入口要求内部令牌。AI 服务本身仍应仅在可信内网暴露。
- `CRYPTO_KEY` 必须稳定且妥善保管；更换它会导致既有 MCP / 模型凭据无法解密。
- 将 Skills 目录与用户文件中心目录分开部署；平台共享技能不提供租户级隔离。

## 验证方式

- Python 回归包含技能管理、路径校验、内部认证、错误脱敏、DNS / 工具授权，以及官方 FastMCP 服务与客户端通过 ASGI Transport 的真实协议初始化、工具发现和调用。
- 平台服务 回归覆盖用户隔离、密文保存、不回显凭据、地址变更、授权校验与发现期间的条件更新。
- 浏览器回归使用 mock API 验证 Skills 管理、角色控制、MCP 配置 / 授权和节点选择。
- 未将 ASGI 协议测试描述为公网供应商联调；OAuth、真实模型自动调用外部服务与生产网络策略仍需部署后单独验证。

本轮 `make check` 通过：AI 219、平台服务 73、前端 SSE 13、Python SDK 12、TypeScript SDK 14、Python/TypeScript SDK 10，共 **341 项测试**，类型检查与构建通过。`make test-ui` 的 **32 项隔离浏览器回归通过**，本轮新增 23 项 Python、16 项 平台服务 和 4 项浏览器测试；相关 Python 文件 Ruff 检查通过。
