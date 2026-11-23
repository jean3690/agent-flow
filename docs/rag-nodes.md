# RAG 节点

知识库本身解决「存」和「查」，这组节点补齐 RAG 的召回增强、重排与可信回答，仍然保持「每一步可见、可替换」的编排方式。

| 节点 | 作用 | 何时用 |
| --- | --- | --- |
| `knowledge` | 单路向量 + 词法检索 | 问题明确、知识库不大 |
| `knowledge_upsert` | 运行期写入知识库并建索引 | 把执行结果沉淀回知识库 |
| `multi_query_retrieve` | 查询扩展 + 多路召回 + RRF 融合 | 问法模糊、同义词多、单路召回不稳 |
| `hyde_retrieve` | 生成假设段落，与原问题双路召回 | 短查询、术语稀疏、文档与问法差异大 |
| `rerank` | LLM 按问题给候选片段打分 | 召回数量多、需要压到 3–5 条再喂模型 |
| `rag_answer` | 只依据片段回答并标注 `[n]` | 需要可追溯、可核查的最终答案 |

## 多路召回（multi_query_retrieve）

1. 模型围绕原问题生成最多 5 条检索语句；
2. 每条语句分别调用 平台内部检索；
3. 用 Reciprocal Rank Fusion 合并：`score = Σ 1 / (60 + rank)`；
4. 输出融合后的 `chunks`、扩展后的 `queries` 和每个片段命中的 `matchedQueries`。

配置：`numQueries`（1–5）、`topK`（每路条数）、`finalTopK`（融合后保留）。

## HyDE 召回（hyde_retrieve）

先生成一段「可能回答问题的资料」，再把它和原问题一起检索并融合。适合问题很短、和文档措辞差异较大的场景。假设段落只用于检索，不作为答案输出。

## LLM 重排（rerank）

- 上游接 `knowledge` / `multi_query_retrieve` / `hyde_retrieve`，留空 `source` 自动取上游 `chunks`。
- 模型返回 `[{index, score, reason}]`，按分数保留前 `topK` 条。
- 重排失败时保留原顺序并写 `node_log` 告警，不阻断流程。

## 引用问答（rag_answer）

- 可以直接选知识库，也可以使用上游片段；
- 系统提示词强制「只依据资料回答 + `[n]` 标注来源」；
- 输出 `citations`（编号、标题、chunkId、原始分数）与 `cited`；
- 回答没有任何引用时只告警，不失败，方便用条件分支决定是否重试。

## 组合示例

**基础 RAG**：`knowledge` → `llm`（把 `text` 拼进提示词）

**高召回 + 高可信**：`multi_query_retrieve` → `rerank` → `rag_answer` → `evaluator`

**术语稀疏**：`hyde_retrieve` → `rerank` → `rag_answer`

**知识沉淀**：`web_fetch` / `plan_execute` → `knowledge_upsert` → 后续用 `multi_query_retrieve` 召回

## Mock 与验证

- 未配置模型 Key 时，查询扩展/假设段落/重排打分走确定性 mock，但仍会真实调用 平台服务 检索，便于离线验证链路。
- 重排与引用问答在没有片段时直接失败，避免空上下文编造答案。
- 当前引用只到片段级（标题 / chunkId），没有文档 URL；需要可点击来源时应在 平台侧补充文档地址。

## 边界

- 没有接入专用 cross-encoder 重排模型，`rerank` 使用 LLM 打分，成本和延迟高于向量检索。
- 多路召回会把检索次数放大到 `numQueries` 倍，知识库很大时要控制 `topK` 与并发。
- RRF 只做排名融合，不校准不同检索器的绝对分数。
