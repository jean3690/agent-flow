# Agent 范式节点

把常见 Agent 范式收敛成独立节点，每个节点内部负责多步推理，外部仍是一张可编排的 DAG。这样既能复用已有条件分支、子流程、记忆与知识库，又不必为每种范式单独写一套运行时。

| 节点 | 范式 | 内部行为 | 主要输出 |
| --- | --- | --- | --- |
| `react_agent` | ReAct | 模型 + 工具循环，最多 `maxSteps` 轮 | text / steps / toolCalls |
| `plan_execute` | Plan-and-Execute | 规划 → 逐步执行 → 汇总 | text / plan / results |
| `reflection` | Reflexion / Evaluator-Optimizer | 初稿 → 评审打分 → 按意见修改 | text / score / history |
| `multi_agent` | 多智能体讨论 / 辩论 | 多角色按轮发言 → 主持人综合 | text / transcript |
| `orchestrator` | Orchestrator-Workers | 选择子工作流执行 → 汇总 | text / selectedWorkers / results |
| `evaluator` | LLM-as-Judge | 按评分标准打分并给反馈 | passed / score / feedback |
| `self_consistency` | Self-Consistency | 多次采样 → 聚合或投票 | text / candidates / agreement |
| `llm_router` | Routing | LLM 选择分支并跳转到目标节点 | route / target / reason / confidence |

所有节点统一字段：`provider`、`model`，未配置 Key 时进入 mock 并给出确定性输出，工作流仍可离线跑通。

## 计划执行（plan_execute）

```
goal ──> 规划器 ──> 步骤 1..N ──> 汇总器 ──> text
```

- `goal`：总体目标，默认 `{{input}}`。
- `maxSteps`：1–8，规划结果超出会截断。
- `synthesize`：关闭时直接把各步结果拼成文本，适合只想要中间产物。
- 三个提示词字段留空使用内置提示词；自定义时规划器必须只输出 JSON 字符串数组。

适用：调研报告、方案拆解、多步内容生产。需要外部资料时，把上游接 `web_search` / `knowledge` 的输出拼进 `goal`。

## 反思迭代（reflection）

```
prompt ──> 初稿 ──> 评审(JSON) ──> 未达标? ──> 修改 ──> 再评审 ...
```

- `maxRounds`：0–3，0 表示只生成初稿并评审一次。
- `threshold`：评审分数达到即停止，避免无效迭代。
- 评审器返回 `{score, issues, suggestions}`；解析失败时会从文本里提取分数，提取不到按 0 处理并继续修改。

适用：文案、报告、代码说明等「能自我检查」的任务。

## 多智能体（multi_agent）

- `agents`：JSON 数组，每项 `{name, role}`，至少 2 个、最多 6 个，支持模板变量。
- `rounds`：1–3 轮；每轮所有角色依次发言，能看到前文摘要。
- 结束后由主持人输出共识、分歧与结论。

适用：方案评审、正反方辩论、跨角色风险识别。角色差异要写在 `role` 里，否则容易得到同质化发言。

## 协调执行（orchestrator）

- `workers`：JSON 数组，每项 `{name, description, workflowId}`；`workflowId` 指向已保存的子工作流，最多 6 个。
- `maxWorkers`：1–4，由模型从候选中选择；未选中时按候选顺序截取。
- `concurrency`：1–3，并行执行多个子工作流。
- `aggregate`：关闭时直接拼接各执行者输出，省一次模型调用。
- 单个执行者失败不会拖垮整体，结果里带 `error`；全部失败才让节点失败。

平台服务在提交执行时会把 `workers` 引用的子工作流内联进 payload，并检查循环引用与数量上限（单次最多 20 个）。

和 `multi_agent` 的区别：`multi_agent` 是同一模型扮演多个角色讨论；`orchestrator` 真正运行独立子工作流，子流程里可以继续用工具、文件、知识库、审批节点。

## 结果评审（evaluator）

- `content`：留空自动取直接上游输出，也支持模板引用。
- `rubric`：评分标准；`threshold`：通过线。
- `failOnLow` 关闭时输出 `passed=false`，交给下游条件分支；开启时直接让节点失败。

适用：发布前质量门、自动验收、把「不合格」路由回 `reflection` 重试。

## 自洽投票（self_consistency）

- `samples`：2–7 次采样，温度固定偏高以产生差异。
- 聚合器比较候选并输出最终答案；`agreement` 为完全相同候选的占比，仅作参考，不适用于长文本。

适用：分类、抽取、短答案问答等对稳定性要求高的场景。长文本生成更适合 `reflection`。

## 意图路由（llm_router）

- §routes§：JSON 数组，每项 §{name, description, target}§；§target§ 填目标节点 ID，最多 6 个分支。
- §fallbackTarget§：未匹配到任何分支时跳转；留空则流程结束。
- 编译器按 §target§ 生成条件边，画布上可以只连一条示意边，也可以把分支都连出来；路由节点不会被无条件全部执行。

适用：客服分流、任务分派、按问题类型选择不同 Agent / 子流程。和 §condition§ 的区别是：§condition§ 走表达式，§llm_router§ 走向量语义。

## 意图路由（llm_router）

- `routes`：JSON 数组，每项 `{name, description, target}`；`target` 填目标节点 ID，最多 6 个分支。
- `fallbackTarget`：未匹配到任何分支时跳转；留空则流程结束。
- 编译器按 `target` 生成条件边，画布上可以只连一条示意边，也可以把分支都连出来；路由节点不会把下游全部执行。

适用：客服分流、任务分派、按问题类型选择不同 Agent / 子流程。和 `condition` 的区别是：`condition` 走表达式，`llm_router` 走语义判断。

## 组合示例

**高质量长文**

`self_consistency`（确定提纲） → `reflection`（成稿打磨） → `evaluator`（质量门） → `condition`（不通过回退到反思或人工处理）

**研究型任务**

`web_search` / `knowledge` → `plan_execute`（按资料拆解） → `knowledge_upsert`（沉淀结果）

**方案决策**

`multi_agent`（产品 / 工程 / 批评者） → `evaluator`（按决策标准打分） → `output`

**按意图分派**

`llm_router`（技术 / 业务 / 其他） → `plan_execute` 或 `react_agent` 或 `multi_agent` → `evaluator`

**分头执行再合并**

`orchestrator`（调用调研 / 分析 / 撰写三个子流程，并发 2） → `evaluator`（质量门） → `human_approval`（发布前审批）

## 边界

- 节点内部循环不体现在画布上，单节点耗时和 token 消耗会更高；上限均已在配置中约束。
- 暂不提供 human-in-the-loop 中断审批；需要人工确认时，可先由 `evaluator` 输出 `passed`，再用 `condition` / `llm_router` 分流到 Webhook / 子流程。
- mock 输出只用于验证链路，不代表模型质量。
