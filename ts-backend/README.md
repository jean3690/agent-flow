# AgentFlow TypeScript 后端

基于 **NestJS + TypeORM** 的 TypeScript 后端实现，与 Java / Python 版本接口完全兼容，前端无需改动。默认监听 **8084**。

## 目录

```text
src/
├── main.ts                 # Nest 启动、CORS、鉴权中间件
├── app.module.ts           # 模块与依赖注入
├── config.ts               # 环境变量
├── common/index.ts         # Result、JSON、时间、 provider 归一化
├── database/               # TypeORM 数据源与实体
├── auth/                   # JWT、刷新令牌、认证接口
├── engine/                 # DAG / LangGraph 等价引擎、执行器、SSE 事件
├── modules/controllers.ts  # 所有 REST Controller
└── services/               # LLM、Agent Plan、知识库、MCP、媒体、Skills
tests/smoke.ts              # 23 项端到端冒烟测试（sqljs 内存库）
```

## 本地运行

```bash
cd ts-backend
npm install
npm run build
npm start                  # http://localhost:8084
```

使用 SQLite 内存库（无需 MySQL）：

```bash
DB_TYPE=sqljs npm start
```

冒烟测试：

```bash
npm run build
npm run smoke              # 自动拉起 sqljs 版服务并执行 23 项检查
```

## Docker

```bash
cd ts-backend
docker compose up -d --build                  # MySQL + Redis + 对象存储 + TS 后端
docker compose --profile full up -d --build   # 额外启动前端（:5174）
```

| 服务 | 端口 |
|------|------|
| TS 后端 | 8084 |
| 前端 | 5174 |
| MySQL | 13307 |
| Redis | 16380 |
| 对象存储 | 19002 / 控制台 19003 |

首次启动会自动建库 `agent_flow` 并执行仓库自带的 `schema.sql`。

## 与 Java/Python 版的兼容性

- 接口路径、`{code,message,data}` 响应体、JWT（HS256/384/512）、SSE 事件名与负载一致
- 支持 DAG / `engineType=langgraph` 两种执行模式、条件分支跳过、执行快照与断点续跑
- 支持全部节点：输入/输出/条件、LLM/ReAct、TTS、图片/视频生成、知识库、记忆、联网搜索/抓取、视觉质检
- 数据库名 `agent_flow`、对象存储 bucket `agent-flow`、环境变量前缀 `AGENTFLOW_*`

> 外部 LLM / TTS / 图片视频 / MCP 搜索需要真实 API Key、`uvx` 与对象存储；冒烟测试不调用外部服务。
