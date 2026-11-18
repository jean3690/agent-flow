# AgentFlow：简历项目介绍

> 以下按“个人项目 / 主要开发者”口吻组织。投递前请按你的真实参与范围调整职责，补充项目时间和仓库地址；不要把协作、参考或辅助开发的部分写成独立原创。推荐 Java 后端岗位优先使用第一版。

## 一、Java 后端岗位版（可直接改后粘贴）

### AgentFlow — AI 工作流编排与执行平台

**技术栈：** Java 21、Spring Boot 3.4、MyBatis-Plus、MySQL / H2、Python、FastAPI、LangGraph、Vue 3、TypeScript、SSE、Docker Compose。

**项目简介：** 面向知识问答与内容生成场景的可视化 AI 工作流平台，将模型调用、知识检索和工具执行组合为可复用流程。采用 Java 业务服务 + Python AI 执行服务的双服务架构，提供工作流编排、版本发布、自动触发、实时调试和多语言 SDK 接入。

**主要工作：**

- 设计 Java / Python 职责边界，以工作流 JSON 和 SSE 事件作为主执行契约；Java 管理认证、业务数据及执行留痕，Python 基于 LangGraph 动态构图，支持条件分支、并行合并、子工作流和循环遍历。
- 实现工作流版本快照、发布/回滚及 Cron / Webhook 触发，区分编辑器草稿与触发器发布版本；将同步调用与流式调用统一到执行记录和节点日志体系。
- 完善执行生命周期管理，基于有界线程池实现异步调度与排队取消，对任务拒绝、上游中断及未完成节点统一收尾；通过 JWT / API Key 认证和 Service 层归属校验保护执行记录及子工作流引用。
- 实现模型凭据 AES-256-GCM 加密与 API Key 哈希存储，结合 runId 日志关联、Prometheus 指标、Token 汇总及成本估算，提供执行级排障和资源消耗查看能力。
- 完善 Python / TypeScript / Java SDK 的同步与 SSE 接入，修复实时回调、跨块 UTF-8 解码、超时及连接释放问题；构建覆盖服务与 SDK 的 **157 个自动化测试用例**，配套类型检查、构建及端到端验证流程。

> 简历版面有限时，保留第 1、3、4、5 条；知识检索可以在面试中展开，不必把全部节点类型写进简历。

## 二、AI 应用开发岗位版

### AgentFlow — 基于 LangGraph 的可视化 Agent 工作流平台

**技术栈：** Python、FastAPI、LangGraph、OpenAI 兼容协议、ReAct / Function Calling、RAG、Java Spring Boot、Vue 3、SSE。

**项目简介：** 将 LLM、RAG 与工具调用封装为可编排节点，支持通过画布构建、执行、调试和发布 AI 应用，并通过 REST / SDK 集成到外部系统。

**主要工作：**

- 基于节点注册表与 LangGraph 构建动态执行图，支持条件路由、异步并行、子流程及 foreach，结合节点重试、超时和失败继续策略控制执行行为。
- 封装 OpenAI 兼容模型接入与 ReAct 工具循环，提供输入读取、技能加载、知识检索、网页抓取及文件读写工具；使用 SKILL.md 摘要/详情/引用分层加载组织技能内容。
- 实现知识文档导入、分片、Embedding 与检索链路，以向量余弦相似度及字符 bigram + IDF 词法得分进行混合重排，无可用真实向量时回退词法检索。
- 打通 Python → Java → 前端的节点事件和 Token 流，提供实时调试、执行历史、取消及成功节点输出复用；完善三种语言 SDK 与 **157 个自动化测试用例**，支持无模型 Key 的 mock 链路验证。

## 三、约一分钟的面试介绍

“AgentFlow 是我做的一个 AI 工作流编排项目。它不是只封装一次大模型调用，而是把模型、知识检索和工具操作组合成流程，用户可以在画布中配置节点和连线，再运行、调试或发布。

架构上我把平台业务和 AI 执行拆开：Java 负责认证、工作流版本和执行记录，Python 使用 LangGraph 构图和调用模型，两边通过 JSON 和 SSE 对接。这样业务侧不用引入模型 SDK，AI 节点也能独立扩展。

我重点关注执行可靠性与接入体验。例如排队任务取消后不能再次启动，线程池拒绝或上游断流不能留下永久运行中的记录，执行记录和子工作流引用也要检查用户权限。SDK 则必须真正逐事件回调，而不是等响应结束再统一返回。

目前服务和 SDK 有 157 个自动化测试用例。我也明确区分了已完成的功能与生产化边界：当前适合单实例，分布式调度、崩溃恢复和大规模检索是后续要继续做的部分。”

## 四、技术亮点与代码依据

| 亮点 | 代码入口 | 面试可展开的问题 |
| --- | --- | --- |
| 跨语言职责拆分 | `java-service/.../service/ExecutionService.java`、`ai-service/app/graph/runner.py` | 为什么不是全部 Java 或全部 Python？协议变更如何协作？ |
| 动态图编排与节点扩展 | `ai-service/app/graph/compiler.py`、`app/graph/runtime.py`、`app/nodes/registry.py` | 条件路由、并行状态合并、节点扩展如何处理？ |
| 排队取消与异常终态 | `java-service/.../service/ExecutionService.java`、`.../ExecutionServiceTest.java` | 为什么要在入队前登记任务？上游还没建连接时取消怎么办？ |
| 记录与子工作流权限 | `controller/ExecutionController.java`、`service/ExecutionService.java` | 为什么鉴权不能只停留在“已登录”？如何避免 IDOR？ |
| SSE 增量消费 | `java-service/.../util/SseReader.java`、`sdk/typescript/src/sse.ts`、三种 SDK client | UTF-8 / CRLF 跨块如何解析？提前退出时怎样释放资源？ |
| 发布与版本快照 | `java-service/.../service/WorkflowService.java` | 为什么保存草稿不能改变线上版本？回滚如何保留历史？ |
| 混合知识检索 | `java-service/.../util/KnowledgeScorer.java`、`service/KnowledgeBaseService.java` | 词法与语义检索如何互补？当前检索实现的规模边界是什么？ |
| 凭据保护与观测 | `service/CryptoService.java`、`ApiKeyService.java`、`ModelPricingService.java` | 为什么 API Key 哈希、供应商 Key 却加密？估算成本如何定价？ |

表中 `java-service/.../` 指 `java-service/src/main/java/com/agentflow/`；测试在对应的 `src/test/java/com/agentflow/`。

## 五、不要夸大的内容

- **项目参考了已有平台的设计思路**：强调你理解并完成的职责拆分、功能实现与工程改进，不写“从零原创全部架构”。
- **157 是自动化用例数，不是覆盖率**：没有覆盖率报告就不写“覆盖率 90%”；没有压测就不写 QPS、P95 或“性能提升 X%”。
- **未验证业务规模**：没有真实用户或生产数据，不写“服务数万用户”“企业生产落地”。
- **不是完整多租户平台**：执行记录与工作流有归属校验，但文件、知识库及模型配置仍有共享边界。
- **不是已实现的分布式高可用系统**：没有持久化任务队列、分布式调度锁和崩溃恢复，不写“保证 exactly-once”“支持无损故障转移”。
- **续跑不是完整 checkpoint**：目前复用成功节点输出，输入/定义变更不会自动使缓存失效。
- **RAG 不是向量数据库架构**：当前为关系库分片与应用侧打分，不写使用 Milvus / pgvector / Elasticsearch 或 ANN 索引。
- **成本是估算值**：不等同于供应商真实账单；mock 链路通过也不代表真实模型效果、所有多模态厂商兼容性已验证。

## 六、建议准备的演示

1. 创建“开始 → 知识检索 → 文本模板或模型 → 结束”流程，展示最终结果与节点输出。
2. 构造延迟/失败节点，展示取消、失败留痕及输出复用；解释输入变更时应全量重跑。
3. 发布 v1，保存 v2 草稿，用 Webhook 展示线上仍执行发布版本；再发布或回滚。
4. 使用一个 SDK 运行同一工作流，展示同步汇总与逐事件输出。
5. 运行 `make check`，展示测试与构建结果；说明仍待解决的分布式和规模化问题。
