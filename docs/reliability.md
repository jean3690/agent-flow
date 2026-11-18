# 可靠性设计：崩溃恢复、分布式调度与资源归属

> 这三块对应「单实例玩具」和「可以多实例部署的服务」之间的差距。
> 代码入口见每节末尾，测试为 `java-service/src/test/java/com/agentflow/service/` 下同名测试。

## 1. 进程崩溃后的执行终态修复

**问题**：执行状态在内存 `running` 映射里维护，数据库只记录 RUNNING。进程被 kill、
容器被重建或 OOM 之后，没有任何线程会再写终态，记录会永久停在「运行中」：
列表一直显示进行中、统计失真、且因为「运行中的记录不允许删除」而无法清理。

**做法**：`ExecutionRecoveryService` 监听 `ApplicationReadyEvent`，把启动前遗留的
RUNNING 记录统一收尾：

- 状态置为 FAILED，`errorMessage` 写明「服务重启，执行中断（未收到终态）」；
- 用 `startedAt` 补齐 `finishedAt` 与 `elapsedMs`，执行时长统计不再出现空洞；
- 同一 `runId` 下仍为 RUNNING 的节点日志一并转为 FAILED。

恢复过程本身失败只记日志，不阻断启动——数据库不可用时服务仍应能起来，
再把问题暴露给健康检查，而不是陷入「启动即崩溃」的循环。

入口：`service/ExecutionRecoveryService.java`

## 2. 多实例 CRON 派发租约

**问题**：`TriggerScheduler` 用 `ThreadPoolTaskScheduler` 注册 cron，每个实例都会
各自触发一次，多副本部署时同一时刻会对同一工作流重复派发。引入 Redis 做分布式锁
又会给这个规模的项目增加一个必须运维的组件。

**做法**：新增 `scheduler_lock` 表，用数据库实现租约锁：

- `tryAcquire(lockKey, lease)` 先原子 UPDATE 抢占**已过期**的租约，受影响行数为 1 表示接管成功；
- 没有过期行时尝试 INSERT，主键冲突说明别的实例持有租约，直接跳过本次派发；
- 租约 10 秒，进程崩溃后自动失效，不需要人工解锁，也不会留下死锁行；
- 调度器每 10 分钟清理一次过期行，表规模不随运行时间增长。

语义是「租约窗口内只派发一次」，不是「同一触发器串行执行」：真正的串行由
`TriggerService` 里的 `firing` 集合负责，两者互补。

入口：`service/SchedulerLockService.java`、`service/TriggerService.java#fireCron`、
`service/TriggerScheduler.java`

## 3. 知识库资源级归属

**问题**：工作流和执行记录已经按 `user_id` 过滤，但知识库是全局共享的：
普通用户只要拿到 ID 就能读取、检索、删除别人的知识库和文档（IDOR）。

**做法**：

- 列表按当前用户过滤，管理员仍可见全部；
- 详情、删除、文档增删、分片预览、索引、检索统一走 `getOwned(id, user)`；
- 越权一律返回 **404**，不返回 403——避免调用方通过状态码探测资源是否存在；
- 内部运行期接口（`/internal/knowledge/*`，由 AI 服务携带内部令牌调用）保持原有行为，
  不引入「执行期没有用户上下文」的兼容负担。

入口：`service/KnowledgeBaseService.java`、`controller/KnowledgeBaseController.java`

## 还没做的（面试时如实说明）

- **持久化任务队列**：排队任务在内存里，进程重启后未开始的请求直接丢失；
- **节点日志实时落库**：现在是一次执行结束后批量写入，崩溃后拿不到节点级细节，
  只剩终态和错误信息；
- **跨实例取消路由**：`/cancel` 只能取消本实例内存中的执行；
- **文件目录多租户**：文件中心仍是共享命名空间，只有知识库做了归属校验。
