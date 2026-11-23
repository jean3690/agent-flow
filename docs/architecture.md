# 架构设计

## 1. 分层

```
┌────────────────────────────────────────────────────────────┐
│  Frontend (Vue 3)                                          │
│  Vue Flow 画布 / 节点面板 / 配置抽屉 / 调试抽屉 / Pinia      │
└───────────────────────┬────────────────────────────────────┘
                        │ REST + SSE (Bearer JWT)
┌───────────────────────┴────────────────────────────────────┐
│  平台服务 (FastAPI, 8084)                      │
│  Router → Service → SQLAlchemy                             │
│  · Auth 中间件 (JWT / API Key) · FlowValidator (环检测) │
│  · ExecutionService: 校验 → 有界线程池 → 调 Python → SSE     │
│  · ExecutionJournal: 节点增量留痕 → 终态事务提交             │
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

**平台服务负责"平台"**：用户、工作流定义、版本、执行历史、节点目录、鉴权、对外 API。
它不引入任何模型 SDK，也不执行图——只做**校验 + 调度 + 留痕**。

**Python 负责"智能"**：把工作流 JSON 编译成 LangGraph 图，按节点类型执行，流式吐事件。
每次请求自带完整 flow，图定义无需查询数据库；知识检索与记忆读写通过平台内部 API 完成。但运行任务注册表、取消路由和媒体文件仍有进程/本地存储状态，不能把当前实现视为完全无状态、可直接多副本部署的系统。

这样切分的好处：

1. 加一个新模型/新节点类型，只改 Python，不用发 平台服务 包。
2. 业务侧事务、权限、审计留在平台服务，符合企业后台的既有习惯。
3. Python 服务可独立测试与压测；扩容前需补齐任务路由和共享文件存储。

## 3. 一次执行的时序

```
Browser        平台服务                     Python
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
  │              │ 持久化 RUNNING 节点日志 │
  │              │   event: token        │
  │              │<──────────────────────┤
  │              │   event: node_finished│
  │              │<──────────────────────┤
  │              │ 4. 更新节点日志（输出/耗时/终态）
  │              │   event: run_finished │
  │              │<──────────────────────┤
  │              │ 5. 事务提交 record 与未结束节点的收尾
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
| 新增业务接口 | platform-service controller + service + mapper |
| 新增前端节点表单 | 节点 definition 的 configSchema 即可，表单是通用渲染 |

## 6. 执行可靠性与权限

- 执行记录归属在 Service 层校验，Controller 显式传入当前认证用户；用户列表查询在 SQL 条件中按 userId 限制，避免先取全量数据再过滤。
- 手动执行按调用方权限检查子工作流；触发器执行按记录所属用户检查引用，不能通过 subflow / foreach 绕过工作流隔离。
- flow / 凭据 / 子工作流 / 续跑缓存准备成功后才创建运行记录。异步执行先登记任务，再入有界线程池，排队取消不会被出队时的新对象覆盖。
- 任务拒绝记录 FAILED 并返回 503；正常、失败、取消及中断路径统一释放上游连接、收尾记录与未完成节点、更新指标。
- 平台同步与流式执行共用 SSE 解析器，两种 SDK 增量消费事件；客户端退出流只释放连接，后台取消需调用 cancel 接口。
- 同步 `/run`、SSE `/execute`、Cron 与 Webhook 共用 `BoundedExecutor`，同步入口等待线程池任务结果，不在事件循环线程上直接运行图。容量配置有启动校验，拒绝统一返回 503 并记录指标。
- `ExecutionJournal` 是独立模块：节点开始/成功/失败使用短事务提交；运行终态与未结束节点的最终收尾使用同一事务。网络消费过程不持有数据库事务，也不逐 token 写库。
- SSE 的 `run_finished` / `run_failed` 与 `done` 在最终收尾后发送；落库失败不发送成功事件，同步结果也标记 FAILED。数据库本身不可用时不能保证写入终态，需要恢复数据库并检查遗留记录。
- `ExecutionPreparationService` 冻结输入、图和内联子图、凭据/MCP 配置并计算上下文摘要；`ExecutionResumeService` 校验已结束的源记录与摘要，按依赖选择缓存，不兼容返回 409。缓存命中保留历史输出但不重复计入 token/成本，详见[续跑一致性](execution-resume.md)。
- `/actuator/health/liveness` 只检查应用存活；`/actuator/health/readiness` 聚合应用就绪、数据库和 AI 服务。Compose 用就绪探针决定依赖启动，现有 `/api/system/health` 保持兼容，仅代表存活。
- `ExecutionControl` 管理每次运行的上游固定期限、等待中的连接和读取；单独的期限线程不受执行池饱和影响。`app/sse.py` 有大小边界并在终态停止读取；Python EventBus 限制事件数/字节并在过载时明确失败，运行准入限制保留的响应名额。见[执行资源保护](execution-protection.md)。
- `FileService` 统一文件用户权限，Python 存储辅助函数绑定用户根目录，所有文件/媒体节点和子图复用这一边界；文件与执行调用需内部令牌，浏览器通过凭证请求获取 Blob，历史共享区显式只读。文件存储策略升级为 v2 执行指纹。见[文件隔离](file-isolation.md)。
- 这些保证针对单实例内正常请求及异常收尾；启动修复只将遗留任务标记为失败，进程崩溃后的自动续做、跨实例取消与持久化任务投递尚未实现。

## 7. 保持模块化，而不是继续拆服务

本项目是 **单实例应用 + Python AI 执行进程**，不是严格意义上的单进程单体，也不按微服务集群建设。继续使用一个业务数据库与现有部署单元，通过清晰的职责和事务边界降低维护成本：

| 逻辑模块 | 主要入口 | 边界 |
| --- | --- | --- |
| 身份与凭据 | AuthService、ApiKeyService、LlmProviderService | 用户认证、权限上下文、凭据保护，不执行工作流 |
| 工作流定义 | WorkflowService、FlowValidator | 定义、版本、发布和校验，不持有运行连接 |
| 执行准备 | ExecutionPreparationService、ExecutionResumeService | 定义与权限快照、上下文摘要、续跑缓存校验，不持有网络流 |
| 执行编排 | ExecutionService | 入队、取消、消费事件、执行指标，不再组装递归请求或选择续跑缓存 |
| 执行留痕 | ExecutionJournal、ExecutionRecoveryService | 短数据库事务、节点进度、终态与重启修复，不调用模型 |
| 文件资源 | FileService、Python core/storage | 用户目录权限、内部身份、路径规则、历史只读区，路由层不直接选存储根 |
| 自动触发 | TriggerService、TriggerScheduler | 触发条件与去重，通过统一执行入口派发 |
| AI 运行时 | Python graph / nodes / llm | 图与模型执行，通过内部 API 访问业务数据，不直连业务数据库 |

当前平台服务按 `app/routers`、`app/services`、`app/models.py` 分层。新增能力优先扩展所属 Service；跨模块通过 Service 协作，路由层不直接操作模型查询。需要长耗时网络调用的操作应与数据库事务分开，避免把整个工作流包在一个会话事务中。

`LayerBoundaryTest` 为分层增加回归约束：检查字段、构造器、方法签名和泛型依赖，禁止 Controller 引用 Mapper、Service 反向依赖 Controller，以及持久化/数据层反向依赖业务入口。不新增架构测试库；当前检查不覆盖方法体调用，不能替代代码审查。

下一阶段应优先补齐文件配额/流式下载、数据库/客户端写入期限及真正等待式背压，继续评估动态外部依赖的缓存边界和副作用幂等；只有实际容量要求出现后，再评估持久化队列、共享文件存储和多实例任务路由。
