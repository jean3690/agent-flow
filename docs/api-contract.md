# 服务间契约

Java ↔ Python 之间只有两个方向：**提交执行（含 flow）** 与 **回传 SSE 事件**。
本文件是唯一事实来源，改协议必须同步 ai-service/app/schemas/ 与 java-service 的 dto。

## 1. 工作流 Flow 结构

```jsonc
{
  "id": "12",                       // 可空，Java 侧传入用于埋点
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
| react_agent | provider, model, systemPrompt, prompt, maxSteps, knowledgeBaseId?, toolIds | { "text", "steps", "toolCalls" } |
| image_generate | provider, model, prompt, size | { "imageUrl", "provider", "model", "size" } |
| vision_analyze | provider, model, imageUrl, prompt | { "text", "imageUrl", "model" } |
| video_generate | provider, model, prompt | { "videoUrl", "posterUrl" } |
| tts | provider, voice, text, format | { "audioUrl", "durationMs", "format" } |
| http | method, url, headers, body, timeoutMs | { "status", "body", "headers" } |
| condition | expression, trueBranch, falseBranch | { "result", "branch" } |
| template | template | { "text" } |
| output | template?, key? | { "value" } |

模板语法：{{input}}、{{nodeId}}、{{nodeId.text}}、{{vars.name}}。
条件表达式：受限 AST 求值，可用 context（运行时上下文）、outputs、state，支持比较/布尔/算术/成员运算与 len、str、int、float、bool。

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
  "options": { "mock": false, "timeoutMs": 120000 }
}
```

`providers` 为可选字段：Java 在执行前把前端保存的服务商凭据随请求下发，Python 按「请求覆盖 → 环境变量」的优先级解析，不落盘。`resume` 为断点续跑缓存（Java 由 `resumeRunId` 从节点日志生成，`input` 节点不缓存），命中即跳过该节点执行。响应即为 SSE 流（text/event-stream）。

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

output 取最后一个 output 节点的 value；没有 output 节点时取所有节点输出。

## 5. 其他接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /health | 健康检查，返回 models 数量与 mock 状态 |
| GET | /v1/catalog/nodes | 节点目录（类型、名称、图标、configSchema） |
| GET | /v1/catalog/models | 可用模型列表（provider/model/是否已配置 key） |
| GET | /v1/providers | 服务商元数据（label/models/defaultModel/supportsTts/envConfigured） |
| POST | /v1/providers/test | 用给定或环境变量 Key 发一次最小请求，返回 `{ ok, latencyMs, message }` |
| GET | /v1/skills | 技能摘要列表 |
| GET | /v1/skills/{name} | 技能详情（含三级加载的正文与引用） |

## 6. 服务商凭据（前端可配置）

前端 → Java（`/api/llm-providers`，走登录鉴权），元数据由 ai-service 的 providers 注册表提供：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/llm-providers | 服务商列表，合并 DB 凭据与环境变量状态（只返回掩码 Key） |
| PUT | /api/llm-providers/{provider} | 保存 Key / 自定义 Base URL；`apiKey` 留空表示沿用已保存值，`baseUrl` 留空表示回退默认 |
| DELETE | /api/llm-providers/{provider} | 清除已保存凭据 |
| POST | /api/llm-providers/{provider}/test | 测试连接，可传临时 `apiKey`/`baseUrl` |

存储：`llm_provider_config`（Java 库）。执行时 Java 查表并注入提交请求的 `providers` 字段；Python 仅在内存中使用，不回写、不写日志。环境变量作为兜底，DB 配置优先。

## 7. 知识库

Java 持有知识库、文档与分片；embedding 由 ai-service 计算，检索打分在 Java 侧完成。

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
| POST | /internal/knowledge/search（Java） | 供 knowledge 节点执行期调用，头 `X-Internal-Token` 校验，入参 knowledgeBaseId/query/topK |

打分：真实 embedding 用余弦相似度；mock 或 embedding 不可用时退化为字符 bigram + IDF 的覆盖率打分（零分片段会被过滤）。

## 8. 执行记录

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/executions | 全局执行分页，参数 page/size/workflowId?/status? |
| GET | /api/executions/{runId} | 详情：输入、最终输出、节点日志 |
| POST | /api/executions/{runId}/cancel | 取消运行中的执行 |

取消链路：Java 通知 ai-service `POST /v1/executions/{runId}/cancel` 终止 LangGraph 任务，同时关闭上游 SSE 流；记录状态置为 `CANCELED`，耗时按实际执行时长回填。前端调试面板的「停止」也会调用该接口。

## 9. 智能体工具

`react_agent` 节点使用 OpenAI 兼容 function calling，循环上限 `maxSteps`（1-8）。

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| read_input | 无 | 返回本次运行输入 JSON |
| load_skill | name | 返回技能正文（三级加载的详情层） |
| knowledge_search | query, top_k? | 走 Java `/internal/knowledge/search`，节点需挂载 knowledgeBaseId |
| web_fetch | url | 抓取公网 http/https 并转纯文本；校验 DNS，拒绝回环/内网/保留地址 |

未配置模型 Key 时节点进入 mock：只做本地说明并（若挂载知识库）执行一次 knowledge_search，便于验证链路。

## 10. 多模态

- `image_generate`：OpenAI 兼容 `/images/generations`；无 Key 或 mock 时生成确定性纯色占位 PNG。产物落在 ai-service 媒体目录，经 `/files/{name}` → Java `/api/files/{name}` 代理访问。
- `vision_analyze`：本地 `/files/...` 图片会转成 base64 data URL 再发给多模态模型；mock 模式返回占位分析。
- 文件代理按扩展名返回 MIME（png/jpeg/webp/gif/svg/mp3/wav）。

### 8.1 断点续跑

- `POST /api/workflows/{id}/execute` 请求体新增 `resumeRunId`：指向同工作流的一次失败/取消执行。
- Java 校验记录归属后，把该次运行中所有 `SUCCESS` 节点的输出（`input` 节点除外）作为 `resume` 缓存随 payload 下发。
- Python 命中缓存的节点不执行，直接复用上次输出并打 `node_log`「复用上次执行结果（断点续跑）」。
- 注意：续跑复用的是节点输出快照，若两次运行的输入不同，缓存节点不会感知新输入；需要全量重算时不要传 `resumeRunId`。
- 入口：调试面板失败后出现「从失败点续跑」；执行记录详情页失败/取消记录有「去编辑器续跑」。

- `video_generate`：文生视频走「提交任务 + 轮询」的通用约定（`POST {base}/video/generations` → `GET {base}/video/generations/{id}`），不同厂商路径不一致时需适配；mock 生成占位海报。
- 知识检索打分为混合重排：向量余弦（0.7）+ 词法覆盖（0.3），无向量时退化为纯词法（`KnowledgeScorer`）。
- 服务商 Key 落库使用 AES-256-GCM 加密（`enc:v1:` 前缀，密钥 `CRYPTO_KEY`），历史明文在下一次保存时自动转为密文。
