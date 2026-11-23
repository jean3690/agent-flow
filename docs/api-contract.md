# 服务间契约

平台服务 → Python 的主执行契约是 **提交执行（含 flow）** 与 **回传 SSE 事件**；知识检索期间 Python 也会调用平台服务的内部检索接口，此外还有模型、技能、文件与 embedding 接口。
本文件是唯一事实来源，改协议必须同步 ai-service/app/schemas/ 与 platform-service 的 dto。

## 0. 认证与外部调用

AgentFlow 对外暴露的 REST API 全部以 /api 为前缀，运行在平台服务端口（默认 8084），统一返回 { code: 0 表示成功, message, data }。它既可供前端使用，也可被任意外部程序直接调用（作为服务/组件）。

认证二选一：

- API Key（推荐服务间调用）：请求头 X-API-Key: af_xxxx。由管理员 POST /api/api-keys 创建，明文仅返回一次，库内哈希存储。
- 服务账号 JWT：POST /api/auth/login 取 token，请求头 Authorization: Bearer <token>。

OpenAPI 文档：启动后访问 /swagger-ui.html，机器契约在 /v3/api-docs。

官方 SDK（封装了上面这套认证 + 解包 + 同步/流式执行）：Python `sdk/python`、TypeScript `sdk/typescript`。

管理接口（仅 ADMIN）：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /api/api-keys | 创建 API Key（body: { name, ownerUserId?, expiresAt? }），返回一次性明文 rawKey |
| GET | /api/api-keys | 列出 Key（掩码，不暴露明文） |
| DELETE | /api/api-keys/{id} | 吊销 Key |

## 1. 工作流 Flow 结构

```jsonc
{
  "id": "12",                       // 可空，平台侧传入用于埋点
  "name": "内容生产",
  "engineType": "langgraph",        // langgraph | dag（v1 只实现 langgraph）
  "nodes": [
    {
      "id": "n_input",
      "type": "input",              // 见节点目录
      "name": "开始",
      "position": { "x": 100, "y": 200 },
      "config": {}                  // 节点类型各自的配置
    }
  ],
  "edges": [
    { "id": "e1", "source": "n_input", "target": "n_llm" }
  ]
}
```

## 2. 节点类型与 config

| type | config 字段 | 输出 |
| --- | --- | --- |
| input | variables?: string[] 声明的输入变量名 | { "value": runInput, ...runInput } |
| llm | provider, model, systemPrompt, prompt, temperature, maxTokens, skillIds? | { "text", "model", "usage" } |
| knowledge | knowledgeBaseId, query, topK | { "text", "chunks", "count" } |
| knowledge_upsert | knowledgeBaseId, title?, content | { "documentId", "title", "status", "chunkCount", "text" } |
| multi_query_retrieve | provider, model, knowledgeBaseId, query, numQueries?, topK?, finalTopK? | { "text", "chunks", "queries", "count" } |
| hyde_retrieve | provider, model, knowledgeBaseId, query, topK?, finalTopK? | { "text", "chunks", "queries", "hypothetical", "count" } |
| rerank | provider, model, query, source?, topK? | { "text", "chunks", "count", "inputCount" } |
| rag_answer | provider, model, query, knowledgeBaseId?, source?, topK?, requireCitations? | { "text", "citations", "chunks", "cited", "count" } |
| memory_write | scope(workflow/user/global), memoryType, content, tags?, provider?, model? | { "memoryId", "scope", "memoryType", "stored" } |
| memory_retrieve | scope, query, topK?, tags?, provider?, model? | { "memories", "context", "text", "citations", "count" } |
| web_search | provider(tavily/mcp), query?, limit?, freshness?, includeAnswer?, serverId?, toolName?, arguments? | { "query", "summary", "results", "citations", "count", "text" } |
| web_fetch | urls, maxChars?, timeoutMs? | { "pages", "content", "text", "citations", "count", "failures" } |
| react_agent | provider, model, systemPrompt, prompt, maxSteps, knowledgeBaseId?, toolIds | { "text", "steps", "toolCalls" } |
| plan_execute | provider, model, goal, maxSteps?, synthesize?, plannerPrompt?, executorPrompt?, synthesizePrompt? | { "text", "plan", "results", "stepCount" } |
| reflection | provider, model, prompt, systemPrompt?, maxRounds?, threshold?, critiquePrompt?, revisePrompt? | { "text", "score", "roundsUsed", "history" } |
| multi_agent | provider, model, topic, agents(JSON), rounds?, moderatorPrompt? | { "text", "transcript", "rounds", "agentCount" } |
| evaluator | provider, model, content?, rubric?, threshold?, failOnLow? | { "passed", "score", "feedback", "issues" } |
| self_consistency | provider, model, prompt, samples?, systemPrompt?, aggregatorPrompt? | { "text", "candidates", "agreement", "samples" } |
| llm_router | provider, model, input, routes(JSON), fallbackTarget?, systemPrompt? | { "route", "target", "reason", "confidence" } |
| orchestrator | provider, model, task, workers(JSON), maxWorkers?, concurrency?, aggregate?, plannerPrompt?, aggregatorPrompt? | { "text", "selectedWorkers", "results", "reason", "workerCount" } |
| human_approval | title?, content?, waitSeconds?, rejectBehavior?, autoApprove? | { "approved", "approvalId", "status", "comment", "decidedBy" } |
| image_generate | provider, model, prompt, size, referenceImageUrl? | { "imageUrl", "provider", "model", "size" } |
| vision_analyze | provider, model, imageUrl, prompt | { "text", "imageUrl", "model" } |
| video_generate | provider, model, prompt, referenceImageUrl?, duration?, resolution?, ratio? | { "videoUrl", "posterUrl", "provider", "model" } |
| tts | provider, voice, text, format | { "audioUrl", "durationMs", "format" } |
| http | method, url, headers, body, timeoutMs | { "status", "body", "headers" } |
| condition | expression, trueBranch, falseBranch | { "result", "branch" } |
| template | template | { "text" } |
| output | template?, key? | { "value" } |
| file_read | path?, encoding?, maxChars? | { path, fileName, url, size, text, charCount, truncated } |
| file_write | path?, content?, encoding?, append?, overwrite? | { path, fileName, url, size, text, charCount, appended } |
| file_list | prefix?, limit? | { files, count, text, value } |
| file | action(read/write/append/list), path?, content?, encoding?, append?, overwrite?, prefix?, limit? | 同对应具体节点 |
| merge | sources?, mode(object/array/text/first), joinWith? | { value, text, count, sources, outputs } |
| delay | durationMs | { durationMs, elapsedMs } |
| subflow | workflowId, input?, childTimeoutMs? | { value, output, text, outputs, subflowId, nodeCount, elapsedMs } |
| foreach | items, bodyWorkflowId, input?, concurrency?, itemKey?, itemTimeoutMs? | { results, count, successCount, failedCount, text } |

模板语法：{{input}}、{{nodeId}}、{{nodeId.text}}、{{vars.name}}。
条件表达式：受限 AST 求值，可用 context（运行时上下文）、outputs、state，支持比较/布尔/算术/成员运算与 len、str、int、float、bool。

所有节点还支持通用执行选项（与节点自身 config 平级）：

| 字段 | 说明 |
| --- | --- |
| retry | 失败重试次数，0-5，默认 0 |
| retryDelayMs | 重试间隔毫秒，默认 500 |
| timeoutMs | 单节点超时毫秒，0 表示不限；超时计入失败并触发重试 |
| onError | fail（默认，终止工作流）或 continue（记录失败后继续下游） |

`onError=continue` 时节点输出为 { failed: true, error: { code, message } }，下游可用 `{{nodeId.failed}}` 判断并走兜底逻辑；该节点会以 FAILED 状态出现在节点日志中，但整体运行仍可成功。

## 3. 提交执行

POST /v1/executions ，Content-Type: application/json ，Accept: text/event-stream

```json
{
  "runId": "9f1c...",
  "workflowId": "12",
  "flow": { "...": "见上" },
  "input": { "topic": "LangGraph 是什么" },
  "providers": {
    "openai": { "apiKey": "sk-***", "baseUrl": "" }
  },
  "resume": { "tpl": { "text": "上次成功节点的输出" } },
  "subflows": { "12": { "nodes": [], "edges": [] } },
  "options": { "mock": false, "timeoutMs": 120000 }
}
```

`providers` 为可选字段：平台服务在执行前把前端保存的服务商凭据随请求下发，Python 按「请求覆盖 → 环境变量」的优先级解析，不落盘。`resume` 为断点续跑缓存（平台服务由 `resumeRunId` 从节点日志生成，`input` 节点不缓存），命中即跳过该节点执行。`subflows` 为子工作流定义表（workflowId → Flow），平台服务会递归内联 `subflow` / `foreach` 引用的已保存工作流，Python 执行时无需回查数据库。响应即为 SSE 流（text/event-stream）。

### 3.1 同步执行（对外服务调用推荐）

POST /api/workflows/{id}/run ，Content-Type: application/json 。与 /execute 的区别是它同步返回：平台内部消费 SSE 流，结束后汇总为 JSON：

    {
      "runId": "9f1c...",
      "status": "SUCCESS",
      "outputs": { "...": "..." },
      "nodeStatus": [ { "nodeId": "...", "status": "SUCCESS", "output": {} } ],
      "elapsedMs": 1234,
      "errorMessage": null
    }

适合只关心最终结果的程序调用方；需要实时节点进度时仍使用 /execute 的 SSE 流。

## 4. SSE 事件

每条事件格式：event: <name> 换行 data: <json> 换行 换行。

| event | data |
| --- | --- |
| run_started | runId, workflowId, startedAt, nodeCount |
| node_started | runId, nodeId, nodeType, nodeName, seq, timestamp |
| node_token | runId, nodeId, delta |
| node_finished | runId, nodeId, status, output, elapsedMs |
| node_failed | runId, nodeId, status, error, elapsedMs |
| node_log | runId, nodeId, level, message |
| run_finished | runId, status, outputs, output, elapsedMs |
| run_failed | runId, status, error, elapsedMs |
| done | 空对象，流结束标记 |

output 取最后执行的 output 节点的 value；没有 output 节点时回退到最后执行节点的可提取值。run_finished 的 outputs 字段另行包含按节点 ID 索引的输出集合。

平台服务与 SDK 按 UTF-8 增量读取，兼容 LF / CRLF / CR、注释、默认 message 事件与多行 data（以换行连接）；为避免漏掉终态事件，也容忍最后一个事件未以空行结尾。HTTP 失败、业务响应失败与工作流 run_failed 是不同层次的错误：调用方需分别处理。

## 5. 其他接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /health | 健康检查，返回 models 数量与 mock 状态 |
| GET | /v1/catalog/nodes | 节点目录（类型、名称、图标、configSchema） |
| GET | /v1/catalog/models | 可用模型列表（provider/model/是否已配置 key） |
| GET | /v1/providers | 服务商元数据（label/models/defaultModel/supportsTts/envConfigured） |
| POST | /v1/providers/test | 用给定或环境变量 Key 发一次最小请求，返回 `{ ok, latencyMs, message }` |
| POST | /v1/providers/models | 用 body 中的 `apiKey`/`baseUrl` 请求上游 `GET {base}/models`，返回 `{ ok, source, provider, models, message }`；失败或无 Key 时 `models` 回退内置清单（`source=static`） |

`/v1/catalog/models` 是静态注册表快照，`/v1/providers/models` 是实时拉取结果，二者用途不同。后者与 `/v1/providers/test` 同等级，仅内网可达；Key 只走 POST body，不进入 URL 或日志。
| GET | /v1/skills | 技能摘要列表 |
| GET | /v1/skills/{name} | 技能详情（含三级加载的正文与引用） |

## 6. 服务商凭据（前端可配置）

前端 → 平台服务（`/api/llm-providers`，走登录鉴权），元数据由 ai-service 的 providers 注册表提供：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/llm-providers | 服务商列表，合并 DB 凭据与环境变量状态（只返回掩码 Key） |
| PUT | /api/llm-providers/{provider} | 保存 Key / 自定义 Base URL；`apiKey` 留空表示沿用已保存值，`baseUrl` 留空表示回退默认 |
| DELETE | /api/llm-providers/{provider} | 清除已保存凭据 |
| POST | /api/llm-providers/{provider}/test | 测试连接，可传临时 `apiKey`/`baseUrl` |
| GET | /api/llm-providers/{provider}/models | 拉取该服务商实际可用模型；query 不含任何凭据，平台内部用 POST+JSON 把已保存的明文 Key 下发给 ai-service |

存储：`llm_provider_config`（平台数据库）。执行时 平台服务查表并注入提交请求的 `providers` 字段；Python 仅在内存中使用，不回写、不写日志。环境变量作为兜底，DB 配置优先。

## 7. 知识库

平台服务持有知识库、文档与分片；embedding 由 ai-service 计算，检索打分在 平台侧完成。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/knowledge-bases | 知识库列表（含文档数/分片数） |
| POST | /api/knowledge-bases | 新建：name、description、embeddingProvider、embeddingModel、chunkSize、chunkOverlap |
| GET | /api/knowledge-bases/{id} | 详情 |
| DELETE | /api/knowledge-bases/{id} | 删除知识库及分片 |
| GET | /api/knowledge-bases/{id}/documents | 文档列表 |
| POST | /api/knowledge-bases/{id}/documents/text | 导入文本 { title, content } |
| POST | /api/knowledge-bases/{id}/documents/upload | 上传 txt/md 文件（multipart，字段 file） |
| DELETE | /api/knowledge-bases/{id}/documents/{docId} | 删除文档 |
| POST | /api/knowledge-bases/{id}/documents/{docId}/preview | 分片预览，可选 chunkSize/chunkOverlap |
| POST | /api/knowledge-bases/{id}/documents/{docId}/index | 分片 + embedding + 落库 |
| POST | /api/knowledge-bases/{id}/search | 检索 { query, topK } |

跨服务接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /v1/embeddings（ai-service） | 入参 provider/model/input/apiKey?/baseUrl?；返回 vectors/model/mock。无 Key 时返回确定性 mock 向量 |
| POST | /internal/knowledge/search（平台服务） | 供 knowledge 节点执行期调用，头 `X-Internal-Token` 校验，入参 knowledgeBaseId/query/topK |
| POST | /internal/approvals（平台服务） | 供 human_approval 节点创建待办，入参 runId/workflowId/nodeId/userId/title/content/expiresInSeconds |
| GET | /internal/approvals/{id}（平台服务） | 供 human_approval 节点轮询审批状态 |
| POST | /internal/knowledge/upsert（平台服务） | 供 knowledge_upsert 节点调用；同知识库同标题覆盖，写入后同步分片 + embedding 建索引 |
| POST | /internal/memory/write（平台服务） | 供 memory_write 节点调用，入参 workflowId/userId/scope/memoryType/content/tags/sourceNodeId/provider/model |
| POST | /internal/memory/search（平台服务） | 供 memory_retrieve 节点调用，入参 workflowId/userId/scope/query/topK/tags/provider/model |

打分：真实 embedding 用余弦相似度；mock 或 embedding 不可用时退化为字符 bigram + IDF 的覆盖率打分（零分片段会被过滤）。

## 8. 执行记录

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/executions | 全局执行分页，参数 page/size/workflowId?/status? |
| GET | /api/executions/{runId} | 详情：输入、最终输出、节点日志 |
| POST | /api/executions/{runId}/cancel | 取消运行中的执行 |
| DELETE | /api/executions/{runId} | 删除已结束的执行记录及节点日志 |

权限规则：非管理员只查询本人 `userId` 的执行记录；详情、取消、删除与续跑缓存读取均校验记录归属，越权和不存在统一返回 404。按 workflowId 查询时先校验工作流访问权限。管理员可以访问所有执行记录。

执行准备（凭据、子工作流及续跑缓存）失败时不会插入 RUNNING 记录。异步线程池拒绝任务返回 HTTP 503 / code 5030，记录收尾为 FAILED。禁止删除运行中记录，返回 HTTP 409 / code 4090；请先取消并等待终态。取消排队任务后，该任务出队时不会向 AI 服务提交执行。上游异常中断时，未完成节点会随运行收尾为 FAILED 或 CANCELED。

取消链路：平台服务通知 ai-service `POST /v1/executions/{runId}/cancel` 终止 LangGraph 任务，同时关闭上游 SSE 流；记录状态置为 `CANCELED`，耗时按实际执行时长回填。前端调试面板的「停止」也会调用该接口。

### 8.1 断点续跑

- 同步 `/run` 与流式 `/execute` 都支持 `resumeRunId`，只能指向同工作流已结束且有一致性指纹的失败/取消执行。
- 平台服务检查用户、输入、实际图及内联子图、下发模型/MCP 配置和请求 mock 选项。不兼容、源记录未结束、历史记录无指纹或可复用输出损坏时，返回 409，不创建新 RUNNING 记录；越权仍返回 404。
- 缓存只复用类型一致的成功节点，排除 input、失败/未执行节点及其依赖下游；依赖包括分支配置、模板引用和 merge sources。
- Python 命中缓存直接复用输出（包括空对象），事件增加 `cacheHit: true`。平台服务不重复累计历史 usage 的 token/成本；详情节点返回 `cacheHit`，执行详情返回 `resumeRunId` 来源。
- 位置/显示名/边 ID/版本计数与整体执行超时不参与身份；修改输入、执行定义或下发配置需完整重跑。运行环境及外部资源变化不在指纹覆盖范围内，仍不等同于持久化 checkpoint 或 exactly-once。
- 入口：调试面板失败后出现「从失败点续跑」；执行记录详情页失败/取消记录有「去编辑器续跑」。

详细规则与数据库升级见[续跑一致性](execution-resume.md)。

## 9. 智能体工具

`react_agent` 节点使用 OpenAI 兼容 function calling，循环上限 `maxSteps`（1-8）。

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| read_input | 无 | 返回本次运行输入 JSON |
| load_skill | name | 返回技能正文（三级加载的详情层） |
| knowledge_search | query, top_k? | 走 平台服务 `/internal/knowledge/search`，节点需挂载 knowledgeBaseId |
| web_fetch | url | 抓取公网 http/https 并转纯文本；校验 DNS，拒绝回环/内网/保留地址 |
| web_search | query, limit? | Tavily 联网搜索，返回标题、链接与摘要；未配置 Key 时返回可读错误 |

未配置模型 Key 时节点进入 mock：只做本地说明并（若挂载知识库）执行一次 knowledge_search，便于验证链路。

### 9.1 长期记忆

- `memory_write`：按 `scope` 写入记忆。`workflow` 只携带 workflowId，`user` 携带 userId，`global` 不限制归属；标签写入前去重并截断到 10 个。
- `memory_retrieve`：召回上限 20 条，按「向量余弦 + 词法」混合排序；未配置 embedding（provider=mock 或调用失败）时退化为字符 bigram + IDF，零分记录会被过滤。
- `llm` 节点可选 `memoryScope/memoryTopK/memoryProvider/memoryModel`：执行前按用户提示词召回记忆并拼进系统提示词；召回异常只写 `node_log` 告警，不阻断主流程。
- 记忆表由平台服务独占，AI 服务只通过 `/internal/memory/*` 读写；执行 payload 会下发 `userId`，子工作流与触发器复用同一归属。
- 公开管理接口 `GET /api/memories`（可按 scope / workflowId 过滤）与 `DELETE /api/memories/{id}`；非管理员只能看到并删除自己的记忆，全局记忆所有人可读。

### 9.2 人工审批

- `human_approval` 节点调用 平台服务 `/internal/approvals` 创建待办，随后每 2 秒轮询状态；SSE 连接保持。
- 待办状态：`PENDING` / `APPROVED` / `REJECTED` / `EXPIRED`；过期在读取时惰性标记。
- 平台服务提交执行时会扫描审批节点，把执行级 `options.timeoutMs` 提升到 `waitSeconds + 30s` 以上。
- 公开接口：`GET /api/approvals?status=`、`POST /api/approvals/{id}/decide {approved, comment}`；普通用户仅能处理自己的待办，管理员可处理全部。
- `AI_MOCK_MODE=always` 或节点 `autoApprove=true` 时不创建待办，直接返回通过；详见 [人工审批](human-approval.md)。

## 10. 多模态

- `image_generate`：OpenAI 兼容 `/images/generations`；无 Key 或 mock 时生成确定性纯色占位 PNG。产物落在 ai-service 媒体目录，经 `/files/{name}` → 平台服务 `/api/files/{name}` 代理访问。
- `vision_analyze`：本地 `/files/...` 图片会转成 base64 data URL 再发给多模态模型；mock 模式返回占位分析。
- 文件代理按扩展名返回 MIME（png/jpeg/webp/gif/svg/mp3/wav）。

- `image_generate` 厂商适配：OpenAI / AiPing 走 OpenAI 兼容接口；StepFun 走 `/v1/images/generations`（`step-image-edit-*` 走 `/step_plan/v1`）；火山方舟走 `/images/generations`。支持 `referenceImageUrl` 参考图。
- `video_generate`：通用厂商走 `POST {base}/video/generations` → `GET {base}/video/generations/{id}`；Agnes 走 `/v1/videos`（轮询 `/agnesapi?video_id=...`）；火山方舟走 `/contents/generations/tasks`。mock 生成占位海报。
- 知识检索打分为混合重排：向量余弦（0.7）+ 词法覆盖（0.3），无向量时退化为纯词法（`KnowledgeScorer`）。
- 服务商 Key 落库使用 AES-256-GCM 加密（`enc:v1:` 前缀，密钥 `CRYPTO_KEY`），历史明文在下一次保存时自动转为密文。

## 11. 文件 IO

工作流的文件读写与文件中心共用 ai-service 的存储实现（`AI_FILE_DIR`，留空回退 `AI_OUTPUT_DIR`），但按 `.users/{userId}` 分区。相对路径只在执行用户目录内解析，绝对/越界路径、控制字符与符号链接均拒绝，不回退到共享根。

### 11.1 对外接口（平台服务 `/api/files`）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/files?prefix=&limit= | 列出本人文件，按更新时间倒序；管理员可显式选择 ownerUserId 或 legacy=true |
| POST | /api/files 或 /api/files/upload | multipart 上传，字段 file，可选 name 指定落盘路径 |
| POST | /api/files/text | 写入文本 { name, content, encoding?, overwrite?, append? } |
| GET | /api/files/{path} | JWT / API Key 下载；?download=true 触发附件，活动内容强制附件 |
| DELETE | /api/files/{path} | 删除文件并清理空目录（需登录或 API Key） |

返回元数据为 { name, fileName, originalName, path, url, size, contentType, createdAt, updatedAt }。path 是用户相对路径，url 形如 `/files/users/1/reports/today.md`，同用户节点可直接消费；浏览器带 JWT 获取 Blob 后预览，SDK 下载需继续携带鉴权。无凭证返回 401，普通用户跨目录访问返回 404。Python 文件及执行/取消接口要求内部令牌，存储身份仅由平台服务提供。

管理员历史区只读入口为 `/api/files?legacy=true` 和 `/api/files/legacy/{path}`，不自动迁移旧文件。完整说明见[文件隔离](file-isolation.md)。

### 11.2 节点行为

- `file_read`：`path` 支持模板（如 `reports/{{input.date}}.md`）；留空时自动取上游输出中的 `/files/...` 产物。超过 `maxChars` 会截断并置 `truncated=true`。
- `file_write`：`path` 默认 `output-{nodeId}.txt`，允许子目录；`content` 留空时取上游最后一个节点的结果。`append=true` 追加，`overwrite=false` 时目标已存在会报错。
- `file_list`：按前缀列出文件，最多 `limit`（1-5000，默认 200）条，结果同时给出 JSON 字符串 `text` 便于下游模板引用。
- `file`：通用节点，`action` 为 read（默认）/ write / append / list，等价于上面三个节点。
- `react_agent` 可挂载 `file_read` / `file_write` / `file_list` 工具，参数与节点配置一致。

## 12. 触发器

每个工作流可以有多个触发器，类型为 `CRON`（定时）或 `WEBHOOK`（外部调用）。触发执行与手动执行共用同一套执行记录（execution_record / execution_node_log），因此同样支持取消、断点续跑与执行中心查看。

### 12.1 管理接口（需登录或 API Key）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/workflows/{id}/triggers | 列出工作流的触发器（含最近状态与下次运行时间） |
| POST | /api/workflows/{id}/triggers | 创建：{ name, type, cronExpression?, timezone?, input?, enabled? } |
| PUT | /api/triggers/{triggerId} | 更新（type 可在 CRON / WEBHOOK 间切换） |
| DELETE | /api/triggers/{triggerId} | 删除并取消调度 |
| POST | /api/triggers/{triggerId}/run | 立即异步运行一次（不要求 enabled） |
| POST | /api/triggers/{triggerId}/rotate-token | 重置 Webhook 令牌，旧地址立即失效 |

### 12.2 CRON

- 表达式支持 5 段（分 时 日 月 周）或 6 段（秒 分 时 日 月 周），5 段会自动补 `0 ` 前缀。
- `timezone` 默认 `Asia/Shanghai`；创建/更新时校验表达式与时区，并计算 `nextRunAt`。
- 同一个 CRON 触发器上一次执行尚未结束时，本轮会被跳过，避免任务堆积。
- 服务重启后从数据库重新注册所有 enabled 的 CRON 触发器。多实例部署时每个实例都会注册，需要额外做分布式锁（当前版本未实现）。

### 12.3 Webhook

- 创建后返回 `webhookPath`：`/api/triggers/webhook/wh_xxx`，令牌为 32 位随机串，仅在触发器管理中展示。
- 调用方式：`POST {base}/api/triggers/webhook/{token}`，Content-Type: application/json，**无需登录或 API Key**。
- 请求体为 JSON 对象时逐字段合并进触发器静态 `input`（同名覆盖）；非对象则放入 `input.body`。
- 立即返回 `{ runId, status: "ACCEPTED" }`，执行在后台完成，可通过 `GET /api/executions/{runId}` 查询结果。
- 删除触发器或重置令牌后旧地址立即返回 404。当前未做调用频率限制，令牌泄露时请立即重置。

### 12.4 存储

触发器保存在 `workflow_trigger` 表；删除工作流时级联删除其触发器并取消内存中的定时任务。

## 13. 节点编排

### 13.1 并行与合并

- 一个节点可以连出多条边，LangGraph 会并行执行后续分支。
- `merge` 节点会等待所有直接上游完成（或 `sources` 指定的节点），再按 `mode` 合并：
  - `object`（默认）：`{ nodeId: value }`
  - `array`：按 sources 顺序输出值数组
  - `text`：用 `joinWith`（默认换行）拼接
  - `first`：取第一个非空值
- `sources` 留空时自动取该节点的所有直接上游。

### 13.2 子工作流

- `subflow` 节点通过 `workflowId` 引用另一条已保存的工作流；执行前 平台服务递归内联其 flow，因此子工作流修改后下一次执行立即生效。
- `input` 为 JSON 输入映射，支持模板（如 `{"topic": "{{input.topic}}"}`）；留空则透传父级 input。
- 输出为 `{ value, output, text, outputs, subflowId, nodeCount, elapsedMs }`，其中 `value/output` 是子流程最终输出。
- 限制：嵌套最多 5 层、单次执行最多内联 20 条子工作流，存在循环引用时执行前直接报错。

### 13.3 循环遍历

- `foreach` 对 `items`（模板表达式或 JSON 数组）逐项执行 `bodyWorkflowId` 指向的工作流。
- 单项输入可用 `item`（可用 `itemKey` 改名）、`index`、`total`，也可用 `input` 自定义映射。
- `concurrency` 1-5 控制并发；`itemTimeoutMs` 控制单项超时。
- 单项失败不会中断其他项，结果数组包含 `{ index, ok, output?, error?, elapsedMs }`，并汇总 `successCount / failedCount`。

### 13.4 画布操作

- 撤销 / 重做：Ctrl/Cmd+Z、Ctrl/Cmd+Shift+Z（或 Ctrl+Y）
- 复制 / 粘贴节点：选中后 Ctrl/Cmd+C、Ctrl/Cmd+V
- 多选：Ctrl/Cmd+点击；Shift+拖动框选
- 自动布局：按拓扑层级排列节点并自适应画布

所有画布能力只影响编排数据，最终仍以保存的 flow JSON 为准。

## 14. 可观测性与成本

### 14.1 指标

平台服务提供 Prometheus 兼容指标接口：

| 路径 | 用途 |
| --- | --- |
| GET /actuator/health | 聚合健康状态 |
| GET /actuator/health/liveness | 应用存活，独立于数据库 / AI 依赖 |
| GET /actuator/health/readiness | 应用就绪 + 数据库 + AI 服务；不可用返回 503 |
| GET /actuator/metrics | Micrometer 指标列表 |
| GET /actuator/prometheus | Prometheus 抓取格式 |

主要指标：

| 指标 | 类型 | 标签 |
| --- | --- | --- |
| agentflow.executions | Counter | status=SUCCESS/FAILED/CANCELED |
| agentflow.execution.duration | Timer | status |
| agentflow.executions.running | Gauge | 无 |
| agentflow.execution.pool.active | Gauge | 无；共用执行线程池活动线程数 |
| agentflow.execution.pool.queued | Gauge | 无；等待队列长度 |
| agentflow.execution.rejected | Counter | 无；入队拒绝次数 |
| agentflow.execution.persistence.failures | Counter | 无；最终收尾持久化失败次数 |
| agentflow.execution.resume.node.hits | Counter | 无；复用历史节点输出次数 |
| agentflow.execution.transport.timeouts | Counter | 无；平台上游连接/读取期限超时次数 |
| agentflow.nodes | Counter | type, status |
| agentflow.node.duration | Timer | type, status |
| agentflow.llm.tokens | Counter | model, kind=prompt/completion |

`agentflow.executions.running` 包含排队及尚未完成收尾的执行。同步、SSE 和触发器共用有界线程池，容量饱和返回 503。节点状态转换增量提交；平台服务的 SSE 运行终态及 `done` 在最终收尾后发送，收尾持久化失败改为 `run_failed`，不会先发布 `run_finished`。这不意味着数据库故障期间终态一定已落库。Actuator 指标接口应限制为内网访问。

工作流请求 `timeoutMs` 为 1–3600000ms，默认 120000ms，审批会调整有效预算；平台服务另加上游读取宽限，超时失败事件使用 `RUN_TIMEOUT`。Python 超限事件错误码为 `EVENT_TOO_LARGE` / `EVENT_BUFFER_OVERFLOW`，流中注释心跳不是业务事件。Python 准入饱和返回 503，活动 runId 重复返回 409；平台服务 接收到这些上游拒绝时将已创建执行标记为 FAILED。详见[执行资源保护](execution-protection.md)。

### 14.2 Token 与成本

- 执行记录新增 prompt_tokens、completion_tokens、total_tokens、cost_usd。
- 平台服务从节点输出的 usage 字段汇总（兼容 promptTokens / prompt_tokens / input_tokens 等命名）。
- 成本按模型单价估算，费率在 application.yml 配置：

    agentflow:
      pricing:
        default-input-per-1k: 0
        default-output-per-1k: 0
        models:
          gpt-4o-mini:
            input-per-1k: 0.00015
            output-per-1k: 0.0006

未知模型使用 default 费率（默认 0），仅做成本参考，不作为计费依据。执行列表与详情展示 token 与估算成本。

### 14.3 日志关联

- 平台服务日志格式追加 [runId:...]，执行线程内通过 MDC 注入，SSE 与同步执行都生效。
- Python 日志通过 ContextVar 注入同一个 runId，便于跨服务串联一次执行。

## 15. 版本与发布

每次保存工作流都会写入一条不可变的 `workflow_version` 快照（创建时为 v1，之后每次保存版本号 +1）。发布（publish）只是把某个版本标记为线上版本，不复制 flow。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/workflows/{id}/versions | 版本列表（不含完整 flow），含 current / published 标记 |
| GET | /api/workflows/{id}/versions/{version} | 版本详情，返回该版本的完整 flow |
| POST | /api/workflows/{id}/versions/{version}/rollback | 把历史版本复制为新的当前版本（版本号 +1），历史不删除 |
| POST | /api/workflows/{id}/publish | 发布当前版本，写入 publishedVersion / publishedAt |
| POST | /api/workflows/{id}/unpublish | 取消发布，触发器回退为执行当前草稿 |

语义：

- **手动运行**（`/execute`、`/run`、编辑器调试）始终执行当前草稿。
- **触发器运行**（Cron / Webhook / 立即运行）优先执行 `publishedVersion` 对应快照；未发布时回退当前草稿。
- **回滚**会生成新版本，不会改写历史版本，也不会自动改变 publishedVersion；需要让线上版本回退时，回滚后再发布。
- `execution_record.flow_version` 记录本次执行实际使用的版本号，便于审计。
- `status`：1=草稿（含已发布版本时的草稿编辑态），2=已发布（存在 publishedVersion）；保存草稿不会清除已发布版本。
## MCP 与 Skills 扩展

执行请求可携带内部字段 `mcpServers`：`serverId -> {url, headers, allowedTools, timeoutMs}`。该字段由平台服务按当前用户权限、启用状态及根流程 / 子流程引用构建，不由浏览器传入，也不写进工作流快照。携带 MCP 配置的 Python 执行入口要求 `X-Internal-Token`；服务端凭据不能回显到浏览器。

工作流节点配置：`mcp_tool` 使用 `serverId`、`toolName`、`arguments`；`react_agent` 使用 `mcpServerIds` 与 `skillIds`；`llm` 使用 `skillIds`。技能管理和 MCP 配置的 REST 接口、权限及限制见 [MCP 与 Skills 配置](mcp-skills.md)。
