"""AI Agent 范式节点：计划执行、反思迭代、多智能体、结果评审、自洽投票。

每个节点都遵循同一套约定：
- 未配置模型 Key（mock）时给出确定性输出，保证工作流可离线跑通；
- 真实调用只依赖 provider/model，不绑定具体厂商；
- 内部多步推理通过 node_log 暴露阶段，不向前端逐 token 刷屏。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from app.core.errors import NodeExecutionError
from app.core.template import build_names, render, stringify
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.graph.subflow import pick_output, run_subflow
from app.llm.factory import build_chat_model
from app.llm.providers import provider_spec
from app.nodes.base import NodeExecutor, extract_value
from app.nodes.registry import register
from app.nodes.value_utils import names_for, render_deep, source_value
from app.schemas.flow import FlowNode

MAX_STEPS = 8
MAX_AGENTS = 6
MAX_SAMPLES = 7
MAX_ROUNDS = 3


def _model_of(config: dict[str, Any]) -> tuple[str, str]:
    provider = str(config.get("provider") or "openai").lower()
    model = str(config.get("model") or provider_spec(provider).default_model)
    return provider, model


def _content(response: Any) -> str:
    content = getattr(response, "content", "")
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content or "")


async def _chat(ctx: NodeContext, provider: str, model: str, system: str, user: str,
                *, temperature: float = 0.3, max_tokens: int | None = None) -> tuple[str, dict]:
    api_key, base_url = ctx.credentials(provider)
    llm = build_chat_model(
        ctx.settings, provider, model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key or None,
        base_url=base_url or None,
    )
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=user))
    response = await llm.ainvoke(messages)
    return _content(response), dict(getattr(response, "usage_metadata", None) or {})


def _merge_usage(usages: list[dict]) -> dict:
    total: dict[str, int] = {}
    for usage in usages:
        for key in ("input_tokens", "output_tokens", "total_tokens", "promptTokens", "completionTokens"):
            value = usage.get(key) if isinstance(usage, dict) else None
            if isinstance(value, (int, float)):
                total[key] = total.get(key, 0) + int(value)
    return total


def _json_from_text(text: str) -> Any:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.rstrip().endswith("```"):
        cleaned = cleaned.rstrip()[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except (TypeError, ValueError):
        pass
    start = next((index for index, char in enumerate(cleaned) if char in "[{"), -1)
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        return value
    except ValueError:
        return None


def _score_of(value: Any, text: str = "") -> int:
    if isinstance(value, dict):
        raw = value.get("score")
        try:
            return max(0, min(100, int(float(raw))))
        except (TypeError, ValueError):
            pass
    match = re.search(r"(?:score|评分)\D{0,6}(\d{1,3})", text or "", re.IGNORECASE)
    return max(0, min(100, int(match.group(1)))) if match else 0


@register
class PlanExecuteNodeExecutor(NodeExecutor):
    """Plan-and-Execute：先出计划，再逐步执行，最后汇总交付。"""

    type = "plan_execute"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        names = names_for(state)
        goal = render(str(config.get("goal") or "{{input}}"), names, strict=True).strip()
        if not goal:
            raise NodeExecutionError(node.id, "计划执行节点缺少目标")
        max_steps = max(1, min(int(config.get("maxSteps") or 4), MAX_STEPS))
        synthesize = bool(config.get("synthesize", True))

        if ctx.mock_for(provider):
            result = self._mock(node, ctx, model, goal, max_steps)
            return result

        try:
            planner_system = str(config.get("plannerPrompt") or "").strip() or (
                "你是任务规划器。把目标拆成可独立执行的步骤，只输出 JSON 字符串数组，"
                f"最多 {max_steps} 项，不要输出解释或代码块。"
            )
            plan_text, usage_plan = await _chat(ctx, provider, model, planner_system, goal, temperature=0.2)
            steps = self._parse_plan(plan_text)[:max_steps]
            if not steps:
                raise NodeExecutionError(node.id, "规划结果为空，请检查规划提示词或模型输出")
            ctx.emit("node_log", nodeId=node.id, level="info", message=f"已生成 {len(steps)} 步计划")

            executor_system = str(config.get("executorPrompt") or "").strip() or (
                "你是执行者。围绕总体目标完成当前步骤，给出可核查的结果；信息不足时明确说明假设。"
            )
            results: list[dict[str, Any]] = []
            usages = [usage_plan]
            for index, step in enumerate(steps):
                history = "\n".join(
                    f"{item['step']}：{item.get('result', '')[:500]}" for item in results
                ) or "（暂无）"
                user = f"总体目标：{goal}\n已完成：\n{history}\n\n当前步骤：{step}"
                text, usage = await _chat(ctx, provider, model, executor_system, user, temperature=0.3)
                results.append({"step": step, "result": text.strip(), "status": "done"})
                usages.append(usage)
                ctx.emit("node_log", nodeId=node.id, level="info",
                         message=f"步骤 {index + 1}/{len(steps)} 完成：{step[:40]}")

            final = "\n\n".join(f"## {item['step']}\n{item['result']}" for item in results)
            if synthesize:
                synth_system = str(config.get("synthesizePrompt") or "").strip() or (
                    "你是汇总者。基于执行结果给出最终交付，结构清晰，不编造结果中没有的事实。"
                )
                final, usage = await _chat(
                    ctx, provider, model, synth_system,
                    f"总体目标：{goal}\n\n执行结果：\n{final}", temperature=0.2,
                )
                usages.append(usage)
            return {
                "plan": [item["step"] for item in results],
                "results": results,
                "stepCount": len(results),
                "text": final,
                "provider": provider,
                "model": model,
                "usage": _merge_usage(usages),
                "mock": False,
            }
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface model errors to the run
            raise NodeExecutionError(node.id, f"计划执行失败: {exc}") from exc

    def _parse_plan(self, text: str) -> list[str]:
        data = _json_from_text(text)
        if isinstance(data, dict):
            data = data.get("steps") or data.get("plan")
        steps: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    steps.append(item.strip())
                elif isinstance(item, dict):
                    value = item.get("step") or item.get("task") or item.get("title")
                    if value:
                        steps.append(str(value).strip())
        if not steps:
            for line in (text or "").splitlines():
                match = re.match(r"^\s*(?:\d+[.)、]|[-*])\s*(.+)$", line)
                if match:
                    steps.append(match.group(1).strip())
        return [item for item in steps if item]

    def _mock(self, node: FlowNode, ctx: NodeContext, model: str, goal: str, max_steps: int) -> dict[str, Any]:
        steps = ["拆解目标与约束", "收集并核对信息", "形成最终交付"][:max_steps]
        results = [
            {"step": step, "result": f"[mock] 第 {index + 1} 步的模拟结果：{step}", "status": "done"}
            for index, step in enumerate(steps)
        ]
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"模拟完成 {len(steps)} 步计划")
        return {
            "plan": steps,
            "results": results,
            "stepCount": len(steps),
            "text": f"[mock:{model}] 计划执行完成，共 {len(steps)} 步。目标：{goal}",
            "provider": "mock",
            "model": model,
            "usage": {},
            "mock": True,
        }


@register
class ReflectionNodeExecutor(NodeExecutor):
    """Reflexion：生成初稿 → 评审打分 → 按意见修改，循环到阈值或轮数上限。"""

    type = "reflection"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        names = names_for(state)
        prompt = render(str(config.get("prompt") or "{{input}}"), names, strict=True).strip()
        if not prompt:
            raise NodeExecutionError(node.id, "反思迭代节点缺少任务")
        system_prompt = render(str(config.get("systemPrompt") or ""), names).strip()
        max_rounds = max(0, min(int(config.get("maxRounds") or 2), MAX_ROUNDS))
        threshold = max(0, min(int(config.get("threshold") or 85), 100))

        if ctx.mock_for(provider):
            return self._mock(node, ctx, model, prompt, max_rounds, threshold)

        try:
            usage_list: list[dict] = []
            draft, usage = await _chat(ctx, provider, model, system_prompt, prompt, temperature=0.5)
            usage_list.append(usage)
            history: list[dict[str, Any]] = []
            score = 0
            for round_index in range(max_rounds + 1):
                critic_system = str(config.get("critiquePrompt") or "").strip() or (
                    "你是严格的评审者。从准确性、完整性、结构三个维度评审草稿，"
                    "只输出 JSON：{\"score\": 0-100, \"issues\": [\"问题\"], \"suggestions\": \"如何修改\"}。"
                )
                critique_text, usage = await _chat(
                    ctx, provider, model, critic_system,
                    f"任务：{prompt}\n\n草稿：\n{draft}", temperature=0.1,
                )
                usage_list.append(usage)
                critique = _json_from_text(critique_text)
                score = _score_of(critique, critique_text)
                issues = critique.get("issues") if isinstance(critique, dict) else []
                if not isinstance(issues, list):
                    issues = [str(issues)] if issues else []
                history.append({"round": round_index, "score": score, "issues": issues})
                ctx.emit("node_log", nodeId=node.id, level="info",
                         message=f"第 {round_index + 1} 次评审得分 {score}")
                if score >= threshold or round_index >= max_rounds:
                    break
                revise_system = str(config.get("revisePrompt") or "").strip() or (
                    "你是作者。根据评审意见改进草稿，直接输出修改后的完整内容，不要解释修改过程。"
                )
                suggestion = critique.get("suggestions") if isinstance(critique, dict) else critique_text
                draft, usage = await _chat(
                    ctx, provider, model, revise_system,
                    f"任务：{prompt}\n\n草稿：\n{draft}\n\n评审意见：{suggestion}",
                    temperature=0.4,
                )
                usage_list.append(usage)
            return {
                "text": draft,
                "score": score,
                "roundsUsed": len(history),
                "history": history,
                "provider": provider,
                "model": model,
                "usage": _merge_usage(usage_list),
                "mock": False,
            }
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise NodeExecutionError(node.id, f"反思迭代失败: {exc}") from exc

    def _mock(self, node: FlowNode, ctx: NodeContext, model: str, prompt: str,
              max_rounds: int, threshold: int) -> dict[str, Any]:
        history = []
        score = 0
        for round_index in range(max_rounds + 1):
            score = min(100, 60 + 15 * (round_index + 1))
            history.append({"round": round_index, "score": score, "issues": ["[mock] 结构与细节可继续打磨"]})
            if score >= threshold:
                break
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"模拟评审得分 {score}")
        return {
            "text": f"[mock:{model}] 反思迭代完成（{len(history)} 轮评审）。任务：{prompt}",
            "score": score,
            "roundsUsed": len(history),
            "history": history,
            "provider": "mock",
            "model": model,
            "usage": {},
            "mock": True,
        }


@register
class MultiAgentNodeExecutor(NodeExecutor):
    """多智能体：多个角色按轮次发言，最后由主持人综合共识与分歧。"""

    type = "multi_agent"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        names = names_for(state)
        topic = render(str(config.get("topic") or "{{input}}"), names, strict=True).strip()
        if not topic:
            raise NodeExecutionError(node.id, "多智能体节点缺少讨论主题")
        rounds = max(1, min(int(config.get("rounds") or 2), MAX_ROUNDS))
        agents = self._agents(config, names, node.id)

        if ctx.mock_for(provider):
            return self._mock(node, ctx, model, topic, agents, rounds)

        try:
            transcript: list[dict[str, Any]] = []
            usage_list: list[dict] = []
            for round_index in range(1, rounds + 1):
                for agent in agents:
                    prior = "\n".join(
                        f"[第{item['round']}轮] {item['agent']}：{item['content'][:400]}" for item in transcript[-12:]
                    ) or "（还没有发言）"
                    system = (
                        f"你是{agent['name']}。角色定位：{agent['role']}。"
                        "请从该角色出发给出观点，引用前文时保持一致，不要重复他人已说过的内容。"
                    )
                    text, usage = await _chat(
                        ctx, provider, model, system,
                        f"讨论主题：{topic}\n\n已有发言：\n{prior}\n\n请给出本轮观点。",
                        temperature=0.6,
                    )
                    transcript.append({"round": round_index, "agent": agent["name"],
                                       "role": agent["role"], "content": text.strip()})
                    usage_list.append(usage)
                    ctx.emit("node_log", nodeId=node.id, level="info",
                             message=f"第 {round_index} 轮：{agent['name']} 发言完成")

            moderator = str(config.get("moderatorPrompt") or "").strip() or (
                "你是主持人。综合各方观点，先列共识，再列分歧，最后给出可执行结论；不要编造发言内容。"
            )
            digest = "\n\n".join(
                f"第{item['round']}轮 · {item['agent']}（{item['role']}）：{item['content']}"
                for item in transcript
            )
            final, usage = await _chat(
                ctx, provider, model, moderator,
                f"讨论主题：{topic}\n\n完整发言：\n{digest}", temperature=0.2,
            )
            usage_list.append(usage)
            return {
                "text": final,
                "transcript": transcript,
                "rounds": rounds,
                "agentCount": len(agents),
                "provider": provider,
                "model": model,
                "usage": _merge_usage(usage_list),
                "mock": False,
            }
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise NodeExecutionError(node.id, f"多智能体讨论失败: {exc}") from exc

    def _agents(self, config: dict[str, Any], names: dict[str, Any], node_id: str) -> list[dict[str, str]]:
        raw = config.get("agents")
        if isinstance(raw, str):
            raw = _json_from_text(render(raw, names)) or []
        elif isinstance(raw, list):
            raw = render_deep(raw, names)
        agents: list[dict[str, str]] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            agents.append({"name": name[:40], "role": str(item.get("role") or "提供专业观点")[:200]})
            if len(agents) >= MAX_AGENTS:
                break
        if len(agents) < 2:
            raise NodeExecutionError(node_id, "多智能体节点至少需要 2 个有效角色（JSON: [{name, role}]）")
        return agents

    def _mock(self, node: FlowNode, ctx: NodeContext, model: str, topic: str,
              agents: list[dict[str, str]], rounds: int) -> dict[str, Any]:
        transcript = []
        for round_index in range(1, rounds + 1):
            for agent in agents:
                transcript.append({
                    "round": round_index,
                    "agent": agent["name"],
                    "role": agent["role"],
                    "content": f"[mock] {agent['name']} 第 {round_index} 轮观点：从「{agent['role']}」出发讨论「{topic}」。",
                })
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"模拟 {rounds} 轮讨论完成")
        return {
            "text": f"[mock:{model}] 多智能体讨论完成，共 {len(transcript)} 条发言。主题：{topic}",
            "transcript": transcript,
            "rounds": rounds,
            "agentCount": len(agents),
            "provider": "mock",
            "model": model,
            "usage": {},
            "mock": True,
        }


@register
class EvaluatorNodeExecutor(NodeExecutor):
    """结果评审：按评分标准给内容打分并给出可执行反馈，可作为质量门。"""

    type = "evaluator"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        content = self._content_of(node, state, ctx)
        if not content.strip():
            raise NodeExecutionError(node.id, "评审节点没有可评审的内容")
        rubric = render(str(config.get("rubric") or "内容准确、结构清晰、没有编造事实"), names_for(state))
        threshold = max(0, min(int(config.get("threshold") or 70), 100))
        fail_on_low = bool(config.get("failOnLow", False))
        usage: dict = {}

        if ctx.mock_for(provider):
            score, issues, feedback = 88, [], f"[mock:{model}] 评分 {88}，满足阈值 {threshold}。"
        else:
            try:
                system = str(config.get("systemPrompt") or "").strip() or (
                    "你是严格的评审员。只输出 JSON：{\"score\": 0-100, \"issues\": [\"问题\"], \"feedback\": \"修改建议\"}。"
                )
                text, usage = await _chat(
                    ctx, provider, model, system,
                    f"评分标准：{rubric}\n\n待评审内容：\n{content[:12000]}", temperature=0.1,
                )
                data = _json_from_text(text)
                score = _score_of(data, text)
                issues = data.get("issues") if isinstance(data, dict) else []
                if not isinstance(issues, list):
                    issues = [str(issues)] if issues else []
                feedback = str(data.get("feedback") or "") if isinstance(data, dict) else text[:1000]
            except NodeExecutionError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise NodeExecutionError(node.id, f"结果评审失败: {exc}") from exc

        passed = score >= threshold
        ctx.emit("node_log", nodeId=node.id,
                 level="info" if passed else "warn",
                 message=f"评审得分 {score}，阈值 {threshold}，{'通过' if passed else '未通过'}")
        if fail_on_low and not passed:
            raise NodeExecutionError(node.id, f"评审未通过（{score} < {threshold}）: {feedback}")
        return {
            "passed": passed,
            "score": score,
            "issues": issues,
            "feedback": feedback,
            "text": feedback,
            "provider": provider,
            "model": model,
            "usage": usage,
            "mock": ctx.mock_for(provider),
        }

    def _content_of(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> str:
        value = source_value(node, state, ctx, "content")
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        return json.dumps(value, ensure_ascii=False)


@register
class SelfConsistencyNodeExecutor(NodeExecutor):
    """Self-Consistency：多次采样后聚合/投票，降低单次生成波动。"""

    type = "self_consistency"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        prompt = render(str(config.get("prompt") or "{{input}}"), names_for(state), strict=True).strip()
        if not prompt:
            raise NodeExecutionError(node.id, "自洽投票节点缺少任务")
        samples = max(2, min(int(config.get("samples") or 3), MAX_SAMPLES))
        system_prompt = render(str(config.get("systemPrompt") or ""), names_for(state)).strip()

        if ctx.mock_for(provider):
            return self._mock(node, ctx, model, prompt, samples)

        try:
            async def one() -> tuple[str, dict]:
                max_tokens = config.get("maxTokens")
                return await _chat(ctx, provider, model, system_prompt, prompt,
                                   temperature=0.9,
                                   max_tokens=int(max_tokens) if max_tokens else None)

            outcomes = await asyncio.gather(*[one() for _ in range(samples)])
            candidates = [text.strip() for text, _ in outcomes]
            usages = [usage for _, usage in outcomes]
            normalized = [re.sub(r"\s+", " ", item).strip() for item in candidates]
            agreement = max(normalized.count(item) for item in normalized) / len(normalized) if normalized else 0

            aggregator = str(config.get("aggregatorPrompt") or "").strip() or (
                "你是汇总者。比较多个候选答案，保留共同正确的部分，修正分歧，输出最终答案；不要解释过程。"
            )
            digest = "\n\n".join(f"候选 {index + 1}：\n{item}" for index, item in enumerate(candidates))
            final, usage = await _chat(
                ctx, provider, model, aggregator,
                f"任务：{prompt}\n\n{digest}", temperature=0.2,
            )
            usages.append(usage)
            ctx.emit("node_log", nodeId=node.id, level="info",
                     message=f"完成 {samples} 次采样，一致率 {agreement:.2f}")
            return {
                "text": final,
                "candidates": candidates,
                "agreement": round(agreement, 3),
                "samples": samples,
                "provider": provider,
                "model": model,
                "usage": _merge_usage(usages),
                "mock": False,
            }
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise NodeExecutionError(node.id, f"自洽投票失败: {exc}") from exc

    def _mock(self, node: FlowNode, ctx: NodeContext, model: str, prompt: str,
              samples: int) -> dict[str, Any]:
        candidates = [f"[mock] 候选 {index + 1}：{prompt[:60]}" for index in range(samples)]
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"模拟 {samples} 次采样")
        return {
            "text": f"[mock:{model}] 自洽投票完成，共 {samples} 个候选。任务：{prompt}",
            "candidates": candidates,
            "agreement": 0,
            "samples": samples,
            "provider": "mock",
            "model": model,
            "usage": {},
            "mock": True,
        }


@register
class LlmRouterNodeExecutor(NodeExecutor):
    """LLM 意图路由：按语义选择分支，输出目标节点 ID 供编译器跳转。"""

    type = "llm_router"
    MAX_ROUTES = 6

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        names = names_for(state)
        text = render(str(config.get("input") or "{{input}}"), names, strict=True).strip()
        if not text:
            raise NodeExecutionError(node.id, "意图路由节点缺少输入")
        routes = self._routes(config, names, node.id)
        fallback = str(config.get("fallbackTarget") or "").strip() or None
        known = {item.id for item in ctx.flow.nodes}
        for route in routes:
            if route["target"] and route["target"] not in known:
                raise NodeExecutionError(node.id, f"路由目标不存在: {route['target']}")
        if fallback and fallback not in known:
            raise NodeExecutionError(node.id, f"兜底目标不存在: {fallback}")

        if ctx.mock_for(provider):
            chosen = next((item for item in routes if item["name"] in text), routes[0])
            reason = "[mock] 关键词命中" if chosen["name"] in text else "[mock] 默认选择首个分支"
            confidence = 0.9 if chosen["name"] in text else 0.5
            answer = ""
        else:
            try:
                system = str(config.get("systemPrompt") or "").strip() or (
                    "你是意图路由器。根据输入选择最匹配的一个分支，只输出 JSON："
                    "{\"route\": \"分支名称\", \"reason\": \"选择原因\", \"confidence\": 0-1}。"
                )
                listing = "\n".join(
                    f"- {item['name']}：{item['description'] or '未提供说明'}" for item in routes
                )
                answer, _usage = await _chat(
                    ctx, provider, model, system,
                    f"可选分支：\n{listing}\n\n输入：\n{text[:8000]}", temperature=0.1,
                )
                data = _json_from_text(answer)
                candidate = str(data.get("route") or "") if isinstance(data, dict) else ""
                if not candidate:
                    candidate = next((item["name"] for item in routes if item["name"] in answer), "")
                chosen = next((item for item in routes if item["name"] == candidate), None)
                if chosen is None:
                    chosen = next((item for item in routes if item["name"] in candidate), None)
                reason = str(data.get("reason") or "") if isinstance(data, dict) else ""
                try:
                    confidence = float(data.get("confidence")) if isinstance(data, dict) else 0.6
                except (TypeError, ValueError):
                    confidence = 0.6
            except NodeExecutionError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise NodeExecutionError(node.id, f"意图路由失败: {exc}") from exc

        if chosen is None:
            target = fallback
            route_name = ""
            reason = reason or "未匹配到分支"
            ctx.emit("node_log", nodeId=node.id, level="warn",
                     message=f"未匹配到分支，{'使用兜底 ' + fallback if fallback else '流程结束'}")
        else:
            target = chosen["target"] or fallback
            route_name = chosen["name"]
            ctx.emit("node_log", nodeId=node.id, level="info",
                     message=f"路由到 {route_name} → {target or 'END'}")

        return {
            "route": route_name,
            "target": target,
            "reason": reason,
            "confidence": round(max(0.0, min(confidence, 1.0)), 2),
            "text": route_name,
            "routes": [item["name"] for item in routes],
            "provider": "mock" if ctx.mock_for(provider) else provider,
            "model": model,
            "mock": ctx.mock_for(provider),
        }

    def _routes(self, config: dict[str, Any], names: dict[str, Any], node_id: str) -> list[dict[str, str]]:
        raw = config.get("routes")
        if isinstance(raw, str):
            raw = _json_from_text(render(raw, names))
        elif isinstance(raw, list):
            raw = render_deep(raw, names)
        routes: list[dict[str, str]] = []
        for index, item in enumerate(raw if isinstance(raw, list) else []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"分支{index + 1}").strip()
            routes.append({
                "name": name[:40],
                "description": str(item.get("description") or "").strip()[:200],
                "target": str(item.get("target") or "").strip(),
            })
            if len(routes) >= self.MAX_ROUTES:
                break
        if not routes:
            raise NodeExecutionError(node_id, "路由表不能为空，请填写 [{name, description, target}] 形式的 JSON 数组")
        return routes



@register
class OrchestratorNodeExecutor(NodeExecutor):
    """Orchestrator-Workers：按任务挑选若干子工作流执行，再汇总结果。"""

    type = "orchestrator"
    MAX_WORKERS = 6

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        names = names_for(state)
        task = render(str(config.get("task") or "{{input}}"), names, strict=True).strip()
        if not task:
            raise NodeExecutionError(node.id, "协调节点缺少任务")
        workers = self._workers(config, node.id)
        max_workers = max(1, min(int(config.get("maxWorkers") or 2), 4))
        concurrency = max(1, min(int(config.get("concurrency") or 2), 3))
        aggregate = bool(config.get("aggregate", True))

        for worker in workers:
            if worker["workflowId"] not in ctx.subflows:
                raise NodeExecutionError(
                    node.id, f"工作流 {worker['workflowId']} 未内联，请确认子流程存在且可访问")

        mock = ctx.mock_for(provider)
        usage_list: list[dict] = []
        reason = ""
        if mock:
            selected = workers[:max_workers]
            reason = "[mock] 默认选择前 " + str(len(selected)) + " 个执行者"
        else:
            try:
                planner = str(config.get("plannerPrompt") or "").strip() or (
                    "你是协调者。根据任务从候选执行者中挑选最合适的成员，最多 "
                    f"{max_workers} 个，只输出 JSON：{{\"workers\": [\"名称\"], \"reason\": \"原因\"}}。"
                )
                listing = "\n".join(
                    f"- {item['name']}：{item['description'] or '未提供说明'}" for item in workers
                )
                answer, usage = await _chat(
                    ctx, provider, model, planner,
                    f"任务：{task}\n\n候选执行者：\n{listing}", temperature=0.1,
                )
                usage_list.append(usage)
                selected, reason = self._select(workers, answer, max_workers)
            except NodeExecutionError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise NodeExecutionError(node.id, f"协调者选择执行者失败: {exc}") from exc

        ctx.emit("node_log", nodeId=node.id, level="info",
                 message=f"协调者选择 {len(selected)} 个执行者：{', '.join(item['name'] for item in selected)}")

        semaphore = asyncio.Semaphore(concurrency)
        started = time.perf_counter()

        async def run_worker(worker: dict[str, str]) -> dict[str, Any]:
            async with semaphore:
                flow = ctx.subflows.get(worker["workflowId"])
                try:
                    child_state, elapsed = await run_subflow(
                        flow,
                        {"task": task, "role": worker["description"], "worker": worker["name"]},
                        ctx,
                    )
                    output = pick_output(flow, child_state)
                    return {
                        "name": worker["name"],
                        "workflowId": worker["workflowId"],
                        "output": output,
                        "text": stringify(output),
                        "elapsedMs": elapsed,
                    }
                except Exception as exc:  # noqa: BLE001 - 单个执行者失败不拖垮整体
                    return {
                        "name": worker["name"],
                        "workflowId": worker["workflowId"],
                        "output": None,
                        "text": "",
                        "error": str(exc)[:500],
                    }

        results = list(await asyncio.gather(*[run_worker(worker) for worker in selected]))
        failures = [item for item in results if item.get("error")]
        if failures:
            ctx.emit("node_log", nodeId=node.id, level="warn",
                     message=f"{len(failures)} 个执行者失败：" + ", ".join(item["name"] for item in failures))
        if results and len(failures) == len(results):
            raise NodeExecutionError(node.id, "所有执行者都执行失败")

        digest = "\n\n".join(
            f"## {item['name']}\n{item.get('text') or ('错误：' + item['error'] if item.get('error') else '')}"
            for item in results
        )
        final = digest
        if aggregate and not mock:
            try:
                aggregator = str(config.get("aggregatorPrompt") or "").strip() or (
                    "你是协调者。综合各执行者的结果给出最终交付，指出冲突与依据，不编造结果中没有的内容。"
                )
                final, usage = await _chat(
                    ctx, provider, model, aggregator,
                    f"任务：{task}\n\n执行者结果：\n{digest[:24000]}", temperature=0.2,
                )
                usage_list.append(usage)
            except Exception as exc:  # noqa: BLE001 - 汇总失败时退回拼接结果
                ctx.emit("node_log", nodeId=node.id, level="warn", message=f"汇总失败，返回拼接结果: {exc}")
        elif mock:
            final = f"[mock:{model}] 协调完成，共 {len(results)} 个执行者。\n\n{digest}"

        elapsed = int((time.perf_counter() - started) * 1000)
        return {
            "text": final,
            "selectedWorkers": [item["name"] for item in selected],
            "results": results,
            "reason": reason,
            "workerCount": len(results),
            "elapsedMs": elapsed,
            "provider": "mock" if mock else provider,
            "model": model,
            "usage": _merge_usage(usage_list),
            "mock": mock,
        }

    def _workers(self, config: dict[str, Any], node_id: str) -> list[dict[str, str]]:
        raw = config.get("workers")
        if isinstance(raw, str):
            raw = _json_from_text(raw)
        workers: list[dict[str, str]] = []
        for index, item in enumerate(raw if isinstance(raw, list) else []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"执行者{index + 1}").strip()
            workflow_id = str(item.get("workflowId") or "").strip()
            if not workflow_id:
                continue
            workers.append({
                "name": name[:40],
                "description": str(item.get("description") or "").strip()[:200],
                "workflowId": workflow_id,
            })
            if len(workers) >= self.MAX_WORKERS:
                break
        if not workers:
            raise NodeExecutionError(node_id, "协调节点至少需要一个带 workflowId 的执行者")
        return workers

    def _select(self, workers: list[dict[str, str]], answer: str,
                max_workers: int) -> tuple[list[dict[str, str]], str]:
        data = _json_from_text(answer)
        names: list[str] = []
        reason = ""
        if isinstance(data, dict):
            raw_names = data.get("workers")
            reason = str(data.get("reason") or "")
            if isinstance(raw_names, list):
                names = [str(item) for item in raw_names if isinstance(item, (str, int))]
        elif isinstance(data, list):
            names = [str(item) for item in data if isinstance(item, (str, int))]
        if not names:
            names = [item["name"] for item in workers if item["name"] in answer]
        selected = [item for item in workers if item["name"] in names][:max_workers]
        if not selected:
            selected = workers[:max_workers]
            reason = reason or "未匹配到执行者，使用候选中的前几个"
        return selected, reason

