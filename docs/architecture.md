# 架构设计

## 1. 分层

```
┌────────────────────────────────────────────────────────────┐
│  Frontend (Vue 3)                                          │
│  Vue Flow 画布 / 节点面板 / 配置抽屉 / 调试抽屉 / Pinia      │
└───────────────────────┬────────────────────────────────────┘
                        │ REST + SSE (Bearer JWT)
┌───────────────────────┴────────────────────────────────────┐
│  Java 业务服务 (Spring Boot 3.4, 8084)                      │
│  Controller → Service → Mapper                             │
│  · AuthInterceptor (JWT)  · FlowValidator (环检测/拓扑排序)  │
│  · ExecutionService: 建记录 → 调 Python → 转发 SSE → 落库    │
└───────────────────────┬────────────────────────────────────┘
                        │ POST /v1/executions (SSE)
┌───────────────────────┴────────────────────────────────────┐
│  AI 服务 (FastAPI, 8000)                                    │
│  · FlowCompiler: JSON → StateGraph（条件边/分支）            │
│  · NodeRegistry: input/llm/tts/http/condition/template/output│
│  · ModelFactory: OpenAI 兼容客户端 + mock 兜底               │
│  · SkillRegistry: SKILL.md 三级加载                          │
└────────────────────────────────────────────────────────────┘
```

## 2. 职责边界

**Java 负责"平台"**：用户、工作流定义、版本、执行历史、节点目录、鉴权、对外 API。
它不引入任何模型 SDK，也不执行图——只做**校验 + 调度 + 留痕**。

**Python 负责"智能"**：把工作流 JSON 编译成 LangGraph 图，按节点类型执行，流式吐事件。
它是无状态服务，每次请求自带完整 flow，方便横向扩容。

这样切分的好处：

1. 加一个新模型/新节点类型，只改 Python，不用发 Java 包。
2. 业务侧事务、权限、审计留在 Java，符合企业后台的既有习惯。
3. Python 服务可独立压测、独立扩容。

## 3. 一次执行的时序

```
Browser        Java                     Python
  │ POST /api/workflows/1/execute        │
  ├─────────────>│                       │
  │              │ 1. 校验 flow（环/孤立节点）
  │              │ 2. 插入 execution_record(status=RUNNING)
  │              │ POST /v1/executions   │
  │              ├──────────────────────>│
  │              │                       │ 3. 编译 LangGraph
  │              │   event: run_started  │
  │              │<──────────────────────┤
  │ event:run_started                     │
  │<─────────────┤                       │
  │              │   event: node_started │
  │              │<──────────────────────┤
  │              │   event: token        │
  │              │<──────────────────────┤
  │              │   event: node_finished│
  │              │<──────────────────────┤
  │              │ 4. 写 execution_node_log（收尾批量落库）
  │              │   event: run_finished │
  │              │<──────────────────────┤
  │              │ 5. 更新 record（SUCCESS/耗时/输出）
  │ event:run_finished                    │
  │<─────────────┤                       │
```

## 4. LangGraph 构图策略

- 节点 id 直接使用工作流节点 id，状态里按 id 存输出。
- 普通边用 add_edge。
- condition 节点用 add_conditional_edges，路由函数读取该节点输出里的 branch，映射到 trueBranch / falseBranch。
- 入口节点 = 没有入边的节点（只允许一个），出口节点 = 没有出边的节点，统一连 END。
- 节点执行异常 → 抛出 NodeExecutionError，运行器捕获后发 node_failed / run_failed 并终止。

## 5. 扩展点

| 想做的事 | 改哪里 |
| --- | --- |
| 新增节点类型 | ai-service/app/nodes/ 加执行器 + registry 注册 + catalog 目录项 |
| 新增模型厂商 | ai-service/app/llm/providers.py 加一条 provider |
| 新增业务接口 | java-service controller + service + mapper |
| 新增前端节点表单 | 节点 definition 的 configSchema 即可，表单是通用渲染 |
