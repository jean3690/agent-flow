# AgentFlow Python 后端

这是现有 Spring Boot 后端（`backend/`）的 Python 重写版本，使用 FastAPI + SQLAlchemy 实现，默认监听 **8084** 端口，接口路径、请求体、`{code,message,data}` 响应结构、JWT/刷新令牌与 SSE 事件格式均与 Java 版保持一致，现有 React 前端无需改动。

Java 后端仍保留在仓库中，未删除；切换时停掉 Java 进程，用 Python 后端占用 8084 即可。

## 技术栈

| 领域 | Java 版 | Python 版 |
| --- | --- | --- |
| Web | Spring Boot 3.4 + Spring MVC | FastAPI + Uvicorn |
| 数据访问 | MyBatis-Plus | SQLAlchemy 2.x + PyMySQL |
| 鉴权 | JJWT + Redis | PyJWT（HS256/384/512 按密钥长度选择）+ Redis（不可用时内存降级） |
| LLM | Spring AI ChatClient | OpenAI 兼容 HTTP 客户端（httpx） |
| 工作流 | 自研 DAG + LangGraph4j | 自研 DAG + 等价顺序状态图引擎 |
| 对象存储 | MinIO SDK | minio Python SDK |
| 文档 | SpringDoc | FastAPI OpenAPI（`/docs`） |

## 快速开始

```bash
cd python-backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # 按需修改数据库、JWT、MinIO 配置
.venv/bin/python run.py
```

默认地址：http://localhost:8084 。Swagger 文档：http://localhost:8084/docs 。

首次连接数据库时：

- 数据库不存在会自动 `CREATE DATABASE`；
- 若 `workflow` 表不存在，会自动执行仓库里的 `backend/src/main/resources/schema.sql`（跳过 `CREATE DATABASE`/`USE`），保证表结构与 Java 版一致；
- 已有数据库不会被覆盖，只补齐缺失的表。

也可以用 uvicorn 启动：

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8084
```

## Docker 一键启动

```bash
cd python-backend

# MySQL + Redis + 对象存储 + Python 后端
docker compose up -d --build

# 需要同时启动前端（Nginx 托管构建产物，并把 /api 反代到后端）时
docker compose --profile full up -d --build
```

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 后端 API | http://localhost:8084 | Swagger: /docs |
| 前端 | http://localhost:5173 | 仅 `--profile full` 启动 |
| MySQL | localhost:13306 | root / `agentflow123`（可用 `MYSQL_ROOT_PASSWORD` 覆盖） |
| Redis | localhost:16379 | 刷新令牌 |
| 对象存储 S3 API | http://localhost:19000 | 默认 RustFS |
| 对象存储控制台 | http://localhost:19001 | 默认 minioadmin / minioadmin |

说明：

- 首次启动时若 `agent_flow` 库为空，会自动执行镜像内的 `schema.sql`，表结构、索引、JSON/MEDIUMTEXT 字段与 Java 版一致。
- 当前环境的 Docker 镜像源拒绝拉取 `minio/minio`，因此默认使用 S3 兼容的 `rustfs/rustfs`。可拉取 MinIO 时通过 `OBJECT_STORAGE_IMAGE=minio/minio:latest docker compose up -d` 替换；注意 MinIO 需要把环境变量改为 `MINIO_ROOT_USER/MINIO_ROOT_PASSWORD`。
- 常用命令：`docker compose logs -f backend`、`docker compose ps`、`docker compose down`。`docker compose down -v` 会删除数据库、Redis 与对象存储数据。
- 默认管理员仍为 `admin/admin123`，部署到公网前请通过 `APP_AUTH_DEFAULT_PASSWORD`、`JWT_SECRET` 覆盖。

## 从旧版本升级

本次为完全切换，不保留旧标识：

- 数据库名改为 `agent_flow`；已有数据可通过 `mysqldump` 导出后导入新库。
- 环境变量前缀改为 `AGENTFLOW_`（如 `AGENTFLOW_DATABASE_URL`、`AGENTFLOW_AUTO_MIGRATE`）。
- 对象存储 bucket 改为 `agent-flow`；Docker 项目名与容器名统一为 `agent-flow-*`。
- JWT 密钥与刷新令牌不兼容旧版本，升级后需要重新登录。

## 配置

配置读取顺序：环境变量 > `python-backend/.env` > `backend/.env` > 默认值。

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `SERVER_PORT` | 服务端口 | 8084 |
| `MYSQL_HOST/PORT/DATABASE/USERNAME/PASSWORD` | MySQL 连接 | localhost/3306/agent_flow/root/空 |
| `REDIS_HOST/PORT/PASSWORD` | 刷新令牌存储 | localhost/6379/空 |
| `JWT_SECRET` | JWT 密钥；留空时本地自动生成临时密钥 | 空 |
| `APP_AUTH_DEFAULT_USERNAME/PASSWORD` | 默认管理员账户，留空则禁用 | admin/admin123 |
| `MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET_NAME/PUBLIC_URL` | 对象存储 | localhost:9000 / minioadmin / agent-flow |
| `SKILLS_PATH` | Skill 目录，默认复用 `backend/src/main/resources/skills` | 自动探测 |
| `AGENTFLOW_AUTO_MIGRATE` | 是否自动建表/写入节点定义 | true |
| `AGENTFLOW_DATABASE_URL` | 直接指定 SQLAlchemy URL（测试可用 SQLite） | 空 |
| `MCP_UVX_PATH` | `uvx` 可执行文件路径 | uvx |

TTS、图片/视频生成依赖 MinIO 与对应云服务；MCP 联网搜索依赖本机 `uvx`（`mcp-server-askecho-search-infinity`）。

## 目录结构

```text
python-backend/
├── app/
│   ├── main.py                 # FastAPI 入口、CORS、鉴权中间件、初始化
│   ├── settings.py             # 环境变量与 .env
│   ├── db.py / models.py       # SQLAlchemy 会话与全部数据模型
│   ├── security.py             # JWT、刷新令牌存储
│   ├── serializers.py          # 实体 -> 前端响应结构
│   ├── engine.py               # DAG 引擎、断点续跑、LangGraph 等价引擎、SSE 事件
│   ├── executors.py            # 节点执行器（IO/条件/LLM/ReAct/TTS/图片/视频/记忆/知识库/搜索）
│   ├── llm.py                  # OpenAI 兼容 Chat 调用与提示词模板
│   ├── tts.py                  # 通义千问 / StepAudio TTS 与 WAV 合并
│   ├── media_clients.py        # 图片、Agnes/Agent Plan 视频客户端
│   ├── knowledge.py            # 知识库、分片、索引、检索
│   ├── agent_plan.py           # Agent Plan 配置解析、Embedding、长期记忆
│   ├── mcp.py                  # MCP 工具配置与 stdio JSON-RPC 客户端
│   ├── skills.py               # SKILL.md 加载与 reference 管理
│   ├── tools.py                # ReAct Agent 工具集
│   ├── routers/                # 按 Java Controller 一一对应的路由
│   └── seed.py                 # 空库时写入预置节点定义
├── tests/smoke_test.py         # 端到端冒烟测试（SQLite，无需 MySQL）
├── requirements.txt
└── run.py
```

## 已对齐的接口

- 认证：`POST /api/auth/login|logout|refresh`、`GET /api/auth/current`
- 工作流：`/api/workflows` 增删改查、执行、SSE 流式执行、最近执行、快照、变量、断点续跑
- 节点定义：`GET /api/node-types`（隐藏独立的 Agent 子节点，逻辑与 Java 一致）
- 全局模型配置：`/api/llm-config` 全部路由（含详情、默认配置、设置默认）
- 知识库：创建/删除/详情、文本导入、文件上传、分片预览、索引、检索
- MCP：列表、新增、更新、删除、测试、Agent Plan 联网搜索预设
- Skills：列表、详情、reference
- 媒体：`POST /api/media/images`
- 静态音频：`/audio/**`

SSE 事件名与负载：`WORKFLOW_START`、`NODE_START`、`NODE_SUCCESS`、`NODE_PROGRESS`、`NODE_ERROR`、`WORKFLOW_COMPLETE`、`ERROR`。

## 与 Java 版的行为说明

- JWT 算法按密钥字节数选择 HS256/HS384/HS512，与 JJWT 的 `Keys.hmacShaKeyFor` 行为一致；在同一个 `JWT_SECRET` 下两版签发的令牌可互相验证。
- 刷新令牌优先存 Redis；Redis 不可用时降级到进程内存储（重启后失效），便于本地开发。
- Agent 长期记忆与 Java 版一样是进程内实现（非数据库持久化）。
- LangGraph 引擎使用等价的顺序状态图实现，支持拓扑执行、节点输出状态传递、失败继续执行与事件推送，并保留 `engineType=langgraph` 的路由行为。
- 逻辑删除、时间格式（`yyyy-MM-dd HH:mm:ss`）、空字段跳过更新、默认配置切换等细节均按 Java 版语义处理。
- 数值型 `temperature` 以 `Numeric(3,2)` 存储并输出为浮点数。

## 测试

```bash
cd python-backend
.venv/bin/python tests/smoke_test.py
```

测试使用临时 SQLite 数据库，覆盖：未认证拦截、登录/刷新、节点定义、工作流 CRUD、DAG 与 LangGraph 执行、条件分支跳过、失败快照、断点续跑、SSE、模型配置、Skills、知识库导入/索引/检索、MCP 列表。
