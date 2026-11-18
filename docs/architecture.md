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
│  · AuthInterceptor (JWT / API Key) · FlowValidator (环检测) │
│  · ExecutionService: 建记录 → 调 Python → 转发 SSE → 落库    │
└───────────────────────┬────────────────────────────────────┘
                        │ POST /v1/executions (SSE)
┌───────────────────────┴────────────────────────────────────┐
│  AI 服务 (FastAPI, 8000)                                    │
│  · FlowCompiler: JSON → StateGraph（条件边/分支）            │
│  · NodeRegistry: AI / 数据 / 文件 / 记忆 / 联网 / 控制流     │
│  · ModelFactory: OpenAI 兼容客户端 + 厂商适配 + mock 兜底    │
│  · SkillRegistry: SKILL.md 三级加载                          │
└────────────────────────────────────────────────────────────┘
```

## 2. 职责边界

**Java 负责"平台"**：用户、工作流定义、版本、执行历史、节点目录、鉴权、对外 API。
它不引入任何模型 SDK，也不执行图——只做**校验 + 调度 + 留痕**。

**Python 负责"智能"**：把工作流 JSON 编译成 LangGraph 图，按节点类型执行，流式吐事件。
每次请求自带完整 flow，图定义无需查询数据库；知识检索与记忆读写通过 Java 内部 API 完成。但运行任务注册表、取消路由和媒体文件仍有进程/本地存储状态，不能把当前实现视为完全无状态、可直接多副本部署的系统。

这样切分的好处：

1. 加一个新模型/新节点类型，只改 Python，不用发 Java 包。
2. 业务侧事务、权限、审计留在 Java，符合企业后台的既有习惯。
3. Python 服务可独立测试与压测；扩容前需补齐任务路由和共享文件存储。

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

## 6. 执行可靠性与权限

- 执行记录归属在 Service 层校验，Controller 显式传入当前认证用户；用户列表查询在 SQL 条件中按 userId 限制，避免先取全量数据再过滤。
- 手动执行按调用方权限检查子工作流；触发器执行按记录所属用户检查引用，不能通过 subflow / foreach 绕过工作流隔离。
- flow / 凭据 / 子工作流 / 续跑缓存准备成功后才创建运行记录。异步执行先登记任务，再入有界线程池，排队取消不会被出队时的新对象覆盖。
- 任务拒绝记录 FAILED 并返回 503；正常、失败、取消及中断路径统一释放上游连接、收尾记录与未完成节点、更新指标。
- Java 同步与流式执行共用 SseReader，三种 SDK 增量消费事件；客户端退出流只释放连接，后台取消需调用 cancel 接口。
- 这些保证针对单实例内正常请求及异常收尾；进程崩溃恢复、跨实例取消与持久化任务投递尚未实现。
