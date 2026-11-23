# 部署说明

## 本地

见根目录 README。三个进程：

| 服务 | 端口 | 启动 |
| --- | --- | --- |
| ai-service | 8000 | uvicorn app.main:app --port 8000 |
| platform-service | 8084 | .venv/bin/uvicorn app.main:app --port 8084 |
| frontend | 5173 | npm run dev |

平台服务默认使用 SQLite 文件库（`platform-service/data/agentflow.db`，重启不丢数据）+ 自动建表 + 初始化管理员 admin/admin123。删除 `platform-service/data/` 即可重置本地数据。

## 生产（MySQL）

1. 将 `DATABASE_URL` 指向 MySQL（如 `mysql+pymysql://user:pass@host:3306/agent_flow?charset=utf8mb4`），启动时由 SQLAlchemy 自动建表，无需手工执行建表脚本。
2. 配置环境变量：

```bash
DATABASE_URL=mysql+pymysql://agent_flow:******@127.0.0.1:3306/agent_flow?charset=utf8mb4
JWT_SECRET=至少32位随机串
AI_SERVICE_BASE_URL=http://127.0.0.1:8000
```

3. AI 服务建议先以单 worker 配合容器或系统服务管理器部署：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

运行任务注册表在 Python 进程内，平台服务的运行表和取消句柄也在进程内。开多副本前需要了解现状：

- **CRON 已可多实例**：派发前抢 `scheduler_lock` 表租约（默认 10s，自动过期并定时清理），同一触发点只会被一个实例执行；
- **执行取消仍是单实例语义**：`/cancel` 只能取消收到请求的那台机器内存中的执行，跨实例取消需要额外的路由；
- **排队任务不持久化**：进程重启后尚未开始的任务丢失，在途执行由启动恢复标记为 FAILED；
- **文件按用户分区，但仍使用本地存储**：多实例需要共享存储；模型配置仍是平台共享配置。

因此当前适合「单实例正式 + 多实例只读/低并发演练」，不能当作已验证的高可用部署。若使用 Gunicorn，应采用独立的 `uvicorn-worker` 包，而非已弃用的 `uvicorn.workers`。

4. 前端 npm run build 后由 nginx 托管，/api 反代到 platform-service；SSE 接口禁用代理缓冲并配置足够的读取超时。

## Docker Compose

```bash
docker compose up --build -d
docker compose logs -f platform-service
```

## 关键配置项

| 变量 | 说明 |
| --- | --- |
| AI_MOCK_MODE | auto（无 key 自动 mock）/ always / never |
| AI_SERVICE_BASE_URL | 平台服务调用 AI 的地址 |
| AI_SERVICE_TIMEOUT_MS | 平台服务调 AI 的请求超时配置，默认 120000；工作流完整上游读取另由 ExecutionControl 的固定期限保护 |
| EXECUTION_CORE_POOL_SIZE | 共用执行线程池核心线程数，默认 4，必须 ≥ 1 |
| EXECUTION_MAX_POOL_SIZE | 共用执行线程池最大线程数，默认 32，必须 ≥ 核心线程数 |
| EXECUTION_QUEUE_CAPACITY | 等待队列容量，默认 200，必须 ≥ 0；0 表示不排队 |
| EXECUTION_TRANSPORT_GRACE_MS | Python 有效运行预算之外的 平台服务上游读取宽限，默认 5000，必须 ≥ 0 |
| EXECUTION_MAX_EVENT_CHARS | 平台服务 SSE 行/事件解码字符上限，默认 2000000，必须 ≥ 256 |
| AI_MAX_CONCURRENCY | Python 同时保留的执行/响应流名额，默认 8；1–256 |
| AI_EVENT_BUFFER_MAX_EVENTS / MAX_BYTES | Python 普通事件积压数 / UTF-8 字节上限，默认 256 / 4194304 |
| AI_EVENT_MAX_BYTES | Python 单个 SSE 事件字节上限，默认 1048576 |
| AI_EVENT_HEARTBEAT_SECONDS | Python 空闲 SSE 注释心跳间隔，默认 15；1–300 秒 |
| JWT_SECRET | 至少 32 字符 |
| CRYPTO_KEY | 服务商 Key 落库加密密钥，更换后旧密文不可解密，请保持稳定 |
| APP_AUTH_DEFAULT_USERNAME / PASSWORD | 首次启动创建的管理员 |

### 健康检查与执行容量

部署时使用 `/actuator/health/readiness` 判断是否可以接流量：它检查应用就绪、数据库与 Python 健康状态，不可用返回 503。Compose 已采用这个接口。进程存活/重启探针使用 `/actuator/health/liveness`，不要因为 AI 服务暂时不可用而重启平台服务。原 `/api/system/health` 只提供兼容的存活检查；本地脚本单独启动平台服务时不强制依赖 AI 服务就绪。

同步、SSE 和自动触发共用线程池；线程池最多同时运行 32 个任务，信号量再将运行中与排队总数限制为 232；饱和请求直接返回 503。根据实际模型耗时、并行限制和内存调整容量，关注 `/actuator/prometheus` 的 `agentflow_execution_pool_active`、`agentflow_execution_pool_queued` 与 `agentflow_execution_rejected_total`。Actuator 指标端点应仅内网可访问，公网反向代理限制 `/actuator/**`，按需开放最小健康检查路径。

节点状态转换已增量落库，终态及未完成节点的收尾通过短事务提交。网络调用不包在数据库事务内；数据库写入失败会导致执行失败，但数据库不可用期间无法保证终态已写入，需要恢复后检查遗留记录。详情见[执行可靠性](reliability.md)。

平台服务上游读取期限从出队连接时开始，覆盖响应头等待和 body，收到运行终态即可停止读取，不等待 EOF。它不覆盖排队、数据库或浏览器 socket 写入，不是整个 HTTP 请求的硬期限。Python 缓冲是“有界＋超限失败”，不是等待式背压；根据真实输出大小配置单事件限制，并将代理空闲超时设得高于心跳间隔。完整边界见[执行资源保护](execution-protection.md)。

## 上线前检查

- 替换默认管理员密码、JWT_SECRET、CRYPTO_KEY 与 AI_INTERNAL_TOKEN；使用 HTTPS，不将 AI 服务端口和 SQLite 数据库文件暴露到公网。
- 模型凭据仍为平台共享配置；文件 API/节点/媒体已按用户目录隔离，所有下载需 JWT / API Key，浏览器采用带凭证请求 + Blob 而非匿名 URL。历史区管理员只读，不自动迁移；见[文件隔离](file-isolation.md)。仍需配额、审计、流式下载与主机权限加固，不等于完整多租户沙箱。
- 对 Webhook 增加速率限制、请求体限制和令牌轮换策略；当前只有令牌校验，没有分布式限流。
- 程序异常可正常收尾，进程崩溃后重启会把遗留的 RUNNING 执行修复为 FAILED，但**不会续跑**；需要持久化队列与断点恢复才能自动续做。
- 多实例部署时注意 `scheduler_lock` 表随 schema 一起创建，并确认各实例时钟偏差在秒级以内。
- 续跑会验证显式执行上下文指纹，输入/定义/下发配置变化返回 409；历史无指纹记录需完整重跑。外部资源或运行环境变化不受指纹保护，需自行完整重跑，见[续跑一致性](execution-resume.md)。
- 知识检索当前从关系库分片计算打分，未使用独立向量数据库/ANN 索引。大规模文档需索引与检索性能评估。
- 进行真实模型联调与容量压测；mock / 单元测试通过不能证明真实模型质量、QPS、P95 延迟或高可用性。
