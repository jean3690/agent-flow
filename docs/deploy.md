# 部署说明

## 本地

见根目录 README。三个进程：

| 服务 | 端口 | 启动 |
| --- | --- | --- |
| ai-service | 8000 | uvicorn app.main:app --port 8000 |
| java-service | 8084 | mvn spring-boot:run |
| frontend | 5173 | npm run dev |

Java 默认 local profile：H2 内存库 + 自动建表 + 初始化管理员 admin/admin123。

## 生产（MySQL）

1. 执行 docs/schema.mysql.sql 建库表。
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

3. AI 服务用 gunicorn + uvicorn worker 多进程部署：

```bash
pip install ".[prod]"
gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
```

4. 前端 npm run build 后由 nginx 托管，/api 反代到 java-service。

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
| AI_SERVICE_TIMEOUT_MS | Java 侧执行总超时，默认 120000 |
| JWT_SECRET | 至少 32 字符 |
| APP_AUTH_DEFAULT_USERNAME / PASSWORD | 首次启动创建的管理员 |
