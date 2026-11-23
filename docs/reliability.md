# 可靠性设计：单实例执行保护、留痕与恢复

> 当前目标是可维护、可观测的单实例应用。数据库 Cron 租约不代表整个执行系统已支持高可用多副本。
> 代码入口见各节，真实事务和就绪探针测试见 `platform-service/tests/`。

## 1. 进程崩溃后的执行终态修复

**问题**：执行状态在内存 `running` 映射里维护，数据库只记录 RUNNING。进程被 kill、
容器被重建或 OOM 之后，没有任何线程会再写终态，记录会永久停在「运行中」：
列表一直显示进行中、统计失真、且因为「运行中的记录不允许删除」而无法清理。

**做法**：`execution.recover_stale()` 在 FastAPI lifespan 启动钩子中执行，把启动前遗留的
RUNNING 记录统一收尾：

- 状态置为 FAILED，`errorMessage` 写明「服务重启，执行中断（未收到终态）」；
- 用 `startedAt` 补齐 `finishedAt` 与 `elapsedMs`，执行时长统计不再出现空洞；
- 同一 `runId` 下仍为 RUNNING 的节点日志一并转为 FAILED。

恢复过程本身失败只记日志，不阻断启动——数据库不可用时服务仍应能起来，
再把问题暴露给健康检查，而不是陷入「启动即崩溃」的循环。

入口：`app/services/execution.py#recover_stale`

## 2. 多实例 CRON 派发租约

**问题**：`CronScheduler` 用后台线程逐秒检查到期时间，每个实例都会
各自触发一次，多副本部署时同一时刻会对同一工作流重复派发。引入 Redis 做分布式锁
又会给这个规模的项目增加一个必须运维的组件。

**做法**：新增 `scheduler_lock` 表，用数据库实现租约锁：

- `_try_acquire_lock(lock_key, lease)` 先原子 UPDATE 抢占**已过期**的租约，受影响行数为 1 表示接管成功；
- 没有过期行时尝试 INSERT，主键冲突说明别的实例持有租约，直接跳过本次派发；
- 租约 10 秒，进程崩溃后自动失效，不需要人工解锁，也不会留下死锁行；
- 调度器每 10 分钟清理一次过期行，表规模不随运行时间增长。

语义是「租约窗口内只派发一次」，不是「同一触发器串行执行」：真正的串行由
`triggers._firing` 集合负责，两者互补。

入口：`app/services/triggers.py#_try_acquire_lock`、`app/services/triggers.py#fire_cron`、
`app/services/scheduler.py`

## 3. 知识库资源级归属

**问题**：工作流和执行记录已经按 `user_id` 过滤，但知识库是全局共享的：
普通用户只要拿到 ID 就能读取、检索、删除别人的知识库和文档（IDOR）。

**做法**：

- 列表按当前用户过滤，管理员仍可见全部；
- 详情、删除、文档增删、分片预览、索引、检索统一走 `getOwned(id, user)`；
- 越权一律返回 **404**，不返回 403——避免调用方通过状态码探测资源是否存在；
- 内部运行期接口（`/internal/knowledge/*`，由 AI 服务携带内部令牌调用）保持原有行为，
  不引入「执行期没有用户上下文」的兼容负担。

入口：`app/services/knowledge.py`、`app/routers/knowledge.py`

## 4. 统一执行容量

同步 `/run`、SSE `/execute`、Cron 与 Webhook 共用一个有界 `BoundedExecutor`。同步请求等待任务结果，不再绕过线程池直接占用事件循环线程执行。排队取消仍会出队收尾，但不会向 Python 提交；同步等待线程被中断时保留中断标记，并请求任务取消。

| 配置 | 默认值 | 约束 |
| --- | --- | --- |
| `EXECUTION_CORE_POOL_SIZE` | 4 | ≥ 1 |
| `EXECUTION_MAX_POOL_SIZE` | 32 | ≥ 核心线程数 |
| `EXECUTION_QUEUE_CAPACITY` | 200 | ≥ 0；0 表示直接移交，不缓存排队任务 |

非法配置阻止启动。线程池最多同时运行 32 个任务，信号量再把「运行中 + 排队」总数限制为 232；超过后立即拒绝，不无限堆积。线程数和等待队列均满或线程池关闭时，返回 503，并把已创建的执行记录收尾为 FAILED。

指标：`agentflow_execution_pool_active`、`agentflow_execution_pool_queued`、`agentflow_execution_rejected_total`。原有 `agentflow_executions_running` 包含排队和正在收尾的记录，不等价于活动线程数。

入口：`app/services/execution.py`、`app/config.py`

## 5. 节点进度增量持久化

`ExecutionJournal` 用短会话提交节点状态，避免网络消费期间长时间持有数据库事务：

- 收到 `node_started` 即插入 RUNNING 节点日志；成功/失败事件更新同一主键，不重复插入。
- 输出、耗时与节点终态在收到对应事件时提交，因此运行中详情可以查看已到达 平台服务的节点进度。
- token 和普通日志事件仅转发，不逐条写库。
- 最终运行记录与未结束节点的收尾在同一事务中提交；节点写入失败会停止消费并关闭上游连接。
- 执行登记在最终收尾后才移除，避免收尾期间删除记录。
- SSE 终态及 `done` 延迟到最终收尾后发送；持久化失败改为失败事件，同步结果同样不会报告成功。持久化失败有 `agentflow_execution_persistence_failures_total` 指标。

进程崩溃后，启动修复保留已提交成功节点的输出，关闭仍为 RUNNING 的节点。**这不是自动续跑，也不是完整事件溯源**：尚未消费/提交的事件可能丢失，token 不持久化，运行级 token 汇总仍在最终收尾时保存。数据库不可用时，失败响应和日志不能代替实际持久化；应先恢复数据库，再检查遗留 RUNNING 记录。

入口：`app/services/execution.py`、`app/services/execution.py#recover_stale`

## 6. 存活与就绪分开

- `/actuator/health/liveness`：应用存活，不依赖数据库和 Python。外部依赖故障不应触发 平台服务重启循环。
- `/actuator/health/readiness`：聚合 `readinessState`、`db` 和 `aiService`；依赖不可用返回 503，恢复后重新返回 200。不验证真实厂商模型、密钥或任务恢复能力。
- `/api/system/health`：保留原兼容接口，仅表示平台服务存活，不能当完整依赖检查。
- Compose 的平台服务健康检查改用 readiness；健康响应不暴露依赖地址、异常和内部组件详情。

入口：`app/routers/observability.py`、`docker-compose.yml`

## 7. 上游执行资源保护

平台服务的连接和 SSE 读取已有固定期限，不因心跳重置；取消可终止等待中的上游连接，终态不再等待 EOF，大小受限的解析器会拒绝巨型无换行事件。Python 使用有界 UTF-8 事件缓冲、过载失败、注释心跳和执行准入，预留终态空间避免满队列无法关闭。完整配置、验证和范围见[执行资源保护](execution-protection.md)。

## 8. 文件用户边界

文件中心、文件 IO、媒体生成/本地图引用统一用户目录，子图继承身份。平台服务所有下载需认证并在 Service 选择身份；Python 文件与执行/取消接口需内部令牌，历史共享文件仅允许管理员通过显式入口只读处理。浏览器使用带 JWT 的 Blob 请求，令牌不放进 URL。见[文件隔离](file-isolation.md)。

## 还没做的（面试时如实说明）

- **持久化任务队列**：排队任务在内存里，进程重启后未开始的请求直接丢失；
- **完整请求期限和等待式背压**：平台服务上游已受保护，但排队、数据库和客户端写入不在该期限内；Python 同步 emit 采用过载失败，不会等待消费者腾位，事件仍不持久化；
- **外部状态和副作用一致性**：已对显式执行上下文做指纹校验及依赖失效，但环境/外部资源变化、动态依赖和副作用 exactly-once 不在保证范围内，见[续跑一致性](execution-resume.md)；
- **跨实例取消路由**：`/cancel` 只能取消本实例内存中的执行；
- **文件配额与沙箱**：已有用户命名空间，但没有每文件 ACL、共享链接、配额、流式下载、对象存储或主机级沙箱；模型配置仍为平台共享。
