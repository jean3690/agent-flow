# 部署说明

## 本地

见根目录 README。三个进程：

| 服务 | 端口 | 启动 |
| --- | --- | --- |
| ai-service | 8000 | uvicorn app.main:app --port 8000 |
| java-service | 8084 | mvn spring-boot:run |
| frontend | 5173 | npm run dev |

Java 默认 local profile：H2 文件库（`java-service/data/agentflow.mv.db`，重启不丢数据）+ 自动建表 + 初始化管理员 admin/admin123。删除 `java-service/data/` 即可重置本地数据。

## 生产（MySQL）

1. 执行 docs/schema.mysql.sql 建库表（包含 api_key、workflow_trigger、workflow_version 等全部表）。
2. 配置环境变量：

```bash
SPRING_PROFILES_ACTIVE=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=agent_flow
MYSQL_USERNAME=agent_flow
MYSQL_PASSWORD=******
JWT_SECRET=至少32位随机串
AI_SERVICE_BASE_URL=http://127.0.0.1:8000
```

3. AI 服务建议先以单 worker 配合容器或系统服务管理器部署：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

运行任务注册表在 Python 进程内，Java 的运行表和 Cron 调度器也在进程内。直接开多 worker / 多 Java 副本会带来取消请求路由不一致和重复触发，不能当作已支持的高可用部署。扩容需增加任务路由、持久化队列、分布式调度锁和共享文件存储。若使用 Gunicorn，应采用独立的 `uvicorn-worker` 包，而非已弃用的 `uvicorn.workers`。

4. 前端 npm run build 后由 nginx 托管，/api 反代到 java-service；SSE 接口禁用代理缓冲并配置足够的读取超时。

## Docker Compose

```bash
docker compose up --build -d
docker compose logs -f java-service
```

## 关键配置项

| 变量 | 说明 |
| --- | --- |
| AI_MOCK_MODE | auto（无 key 自动 mock）/ always / never |
| AI_SERVICE_BASE_URL | Java 调用 Python 的地址 |
| AI_SERVICE_TIMEOUT_MS | Java 调 AI 请求的超时配置，默认 120000；流式 body 的完整消费期限需额外保护，不等价于严格总执行期限 |
| JWT_SECRET | 至少 32 字符 |
| CRYPTO_KEY | 服务商 Key 落库加密密钥，更换后旧密文不可解密，请保持稳定 |
| APP_AUTH_DEFAULT_USERNAME / PASSWORD | 首次启动创建的管理员 |

## 上线前检查

- 替换默认管理员密码、JWT_SECRET、CRYPTO_KEY 与 AI_INTERNAL_TOKEN；使用 HTTPS，不将 AI 服务端口和 H2 Console 暴露到公网。
- 模型凭据当前为平台共享配置；文件下载当前可匿名访问，知识库/文件未实现租户级隔离。多用户敏感业务需先增加细粒度权限及签名下载 URL。
- 对 Webhook 增加速率限制、请求体限制和令牌轮换策略；当前只有令牌校验，没有分布式限流。
- 程序异常可正常收尾，但进程崩溃不会自动恢复在途任务；需要重启扫描、状态恢复和持久化投递。
- 续跑是成功节点输出复用，输入/定义变更不会自动使缓存失效；不同版本或不同输入应全量重跑。
- 知识检索当前从关系库分片计算打分，未使用独立向量数据库/ANN 索引。大规模文档需索引与检索性能评估。
- 进行真实模型联调与容量压测；mock / 单元测试通过不能证明真实模型质量、QPS、P95 延迟或高可用性。
