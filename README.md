# AgentFlow

参考 PaiAgent 重构的 AI 工作流编排平台：**AI 能力交给 Python + LangGraph + FastAPI，业务与平台能力交给 Java Spring Boot**，前端使用 Vue 3。

## 为什么拆成两个服务

PaiAgent 把 DAG/LangGraph 引擎、模型调用和业务 CRUD 都塞在 Spring Boot 里。AgentFlow 做如下切分：

| 关注点 | 归属 | 说明 |
| --- | --- | --- |
| 图编排 / 节点执行 / 模型调用 / 技能加载 | ai-service (Python) | LangGraph 原生生态，节点扩展只写 Python |
| 用户认证 / 工作流 CRUD / 执行记录 / 权限 | java-service (Java) | Spring Boot + MyBatis-Plus + MySQL，稳定的事务与后台能力 |
| 可视化编排 | frontend (Vue 3) | Vue Flow + Element Plus |

两个服务之间只有一条契约：**工作流 JSON + SSE 事件流**（见 docs/api-contract.md）。Java 不碰模型 SDK，Python 不碰数据库。

```
Vue 3 ──REST/SSE──> Java (8084) ──REST/SSE──> Python (8000)
  │                    │
  │                    └── MySQL: user / workflow / execution_record / node_definition
  └── Vue Flow 画布
```

## 目录结构

```
agent-flow/
├── ai-service/          # Python 3.11+ / FastAPI / LangGraph
│   ├── app/
│   │   ├── graph/       # LangGraph 构图与运行器
│   │   ├── nodes/       # 节点执行器（input/llm/tts/http/condition/template/output）
│   │   ├── llm/         # OpenAI 兼容模型工厂（OpenAI/DeepSeek/Qwen/智谱/AiPing）
│   │   ├── skills/      # SKILL.md 三级渐进式加载
│   │   └── api/         # REST + SSE
│   └── tests/
├── java-service/        # Spring Boot 3.4 / Java 21
│   └── src/main/java/com/agentflow/
├── frontend/            # Vue 3 + TS + Vue Flow + Element Plus
└── docs/                # 架构、协议、部署
```

## 快速开始（本地三端）

前置：JDK 21+、Maven 3.9+、Python 3.11+、Node 20+。

### 1. AI 服务（8000）

```bash
cd ai-service
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # 可选；也可以启动后在页面「模型配置」里填 Key
uvicorn app.main:app --reload --port 8000
```

### 2. Java 服务（8084）

```bash
cd java-service
cp .env.example .env
mvn spring-boot:run           # 默认 local profile，H2 文件库（./data），免装 MySQL
```

生产用 MySQL：--spring.profiles.active=mysql，先执行 docs/schema.mysql.sql。

### 3. 前端（5173）

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

打开 http://localhost:5173 ，默认账号 admin / admin123。

### Docker Compose

```bash
docker compose up --build
# web: http://localhost:8080  api: http://localhost:8084
# 数据落在命名卷（java-data / ai-data），`docker compose down -v` 彻底清空
# 可用 .env 传入 OPENAI_API_KEY / AI_INTERNAL_TOKEN / CORS_ALLOWED_ORIGINS 等
```

## 测试

```bash
make test
# 等价于
cd ai-service && .venv/bin/python -m pytest -q   # 16 个用例：表达式、构图、条件分支、技能
cd java-service && mvn test                      # 8 个用例：flow 校验、JWT
```

## 核心能力

- **可视化编排**：拖拽节点、连线、节点级参数配置、画布自动布局
- **LangGraph 引擎**：按 JSON 动态构图，支持条件分支、异步节点、自定义事件流
- **多模型统一**：所有厂商走 OpenAI 兼容协议，新增模型只加一行 providers 配置
- **知识库 / RAG**：文档导入、分片预览、索引与检索，`knowledge` 节点可直接引用片段
- **智能体节点**：ReAct 工具循环，内置读取输入、加载技能、知识检索、网页抓取（拦截内网地址）
- **多模态节点**：`image_generate` / `vision_analyze` / `video_generate`，产物统一走媒体文件代理
- **安全与检索质量**：服务商 Key AES-GCM 落库加密；知识检索混合重排（向量 + 词法）
- **服务商凭据前端可配**：Key / Base URL 在「模型配置」页保存到 Java 库，执行时下发给 AI 服务，环境变量兜底
- **节点插件化**：新增节点 = 一个 NodeExecutor 子类 + 注册表登记
- **技能系统**：SKILL.md + YAML Frontmatter，摘要 → 详情 → 引用三级加载
- **实时调试**：节点级 SSE 事件（开始/流式 token/成功/失败），Java 透传并落库
- **执行中心**：全局执行历史、状态筛选、节点输出回看，支持取消运行中的任务与断点续跑（复用已成功节点输出）
- **执行留痕**：每次执行写入 execution_record 与 execution_node_log

## 文档

- [架构设计](docs/architecture.md)
- [服务间契约](docs/api-contract.md)
- [数据库设计](docs/schema.mysql.sql)
- [部署说明](docs/deploy.md)

## License

MIT
