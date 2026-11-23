from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from . import agent_plan, knowledge, llm, llm_config_service, mcp, tts
from .db import first_text, jdump, jload, text_or_none, to_float, to_int, truthy
from .media_clients import agnes_video_client, openai_image_client, stepfun_image_client
from .minio_client import minio_service
from .skills import skill_registry
from .tools import ToolContext, get_required_tool, get_tools

logger = logging.getLogger("agentflow.executors")

Progress = Optional[Callable[[str, Any], None]]
FENCE = chr(96) * 3


def _as_text(value: Any) -> Optional[str]:
    return text_or_none(value)


class BaseExecutor:
    supported_type = ""

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        raise NotImplementedError


class AbstractAgentPlanExecutor(BaseExecutor):
    def text_value(self, node_data: dict, input_data: dict, field: str, fallback_field: Optional[str]) -> Optional[str]:
        node_value = node_data.get(field)
        if _as_text(node_value):
            return _as_text(node_value)
        input_value = input_data.get(field)
        if _as_text(input_value):
            return _as_text(input_value)
        if fallback_field:
            fallback_value = input_data.get(fallback_field)
            if _as_text(fallback_value):
                return _as_text(fallback_value)
        output = input_data.get("output")
        return _as_text(output) if _as_text(output) else None

    def configured_text_input(self, node_data: dict, input_data: dict, param_name: str) -> Optional[str]:
        params = node_data.get("inputParams")
        if not isinstance(params, list):
            return None
        for param in params:
            if not isinstance(param, dict) or str(param.get("name")) != param_name:
                continue
            param_type = param.get("type")
            if param_type == "input":
                return _as_text(param.get("value"))
            if param_type == "reference":
                reference = param.get("referenceNode")
                if not reference:
                    continue
                key = str(reference).split(".")[-1]
                value = _as_text(input_data.get(key))
                if value:
                    return value
                if key == "user_input":
                    return _as_text(input_data.get("input"))
        return None

    def apply_output_params(self, node_data: dict, output: dict) -> None:
        params = node_data.get("outputParams")
        if not isinstance(params, list):
            return
        for param in params:
            if not isinstance(param, dict):
                continue
            name = _as_text(param.get("name"))
            if not name:
                continue
            source_field = _as_text(param.get("value"))
            value = output.get(source_field) if source_field else output.get(name)
            if value is not None:
                output[name] = value

    def string_data(self, node_data: dict, field: str, default: Optional[str] = None) -> Optional[str]:
        value = _as_text(node_data.get(field))
        return value if value else default

    def int_data(self, node_data: dict, field: str, default: int) -> int:
        value = node_data.get(field)
        parsed = to_int(value, None)
        if parsed is not None:
            return parsed
        text = _as_text(value)
        if text:
            try:
                return int(text)
            except ValueError:
                return default
        return default

    def double_data(self, node_data: dict, field: str, default: float) -> float:
        value = node_data.get(field)
        parsed = to_float(value, None)
        return default if parsed is None else parsed


class InputExecutor(BaseExecutor):
    supported_type = "input"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        return dict(input_data)


class OutputExecutor(BaseExecutor):
    supported_type = "output"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        response_content = node_data.get("responseContent")
        if not response_content:
            return {"output": input_data.get("output") if input_data.get("output") is not None else input_data.get("input")}

        output_params = node_data.get("outputParams") or []
        param_values: dict[str, str] = {}
        for param in output_params:
            if not isinstance(param, dict):
                continue
            name = param.get("name")
            param_type = param.get("type")
            if param_type == "input":
                value = param.get("value")
                param_values[str(name)] = "" if value is None else str(value)
            elif param_type == "reference":
                reference = param.get("referenceNode")
                if not reference or "." not in str(reference):
                    continue
                parts = str(reference).split(".")
                ref_node_id = parts[0]
                ref_param_name = parts[-1]
                ref_value = None
                node_outputs = input_data.get("__nodeOutputs__")
                if isinstance(node_outputs, dict) and ref_node_id in node_outputs:
                    ref_value = (node_outputs.get(ref_node_id) or {}).get(ref_param_name)
                if ref_value is None:
                    ref_value = input_data.get(ref_param_name)
                if ref_value is None and ref_param_name == "user_input":
                    ref_value = input_data.get("input")
                if ref_value is not None:
                    param_values[str(name)] = str(ref_value)

        result = str(response_content)
        for match in re.finditer(r"\{\{(.*?)\}\}", str(response_content)):
            name = match.group(1).strip()
            result = result.replace("{{" + name + "}}", param_values.get(name, ""))
        return {"output": result}


class ConditionExecutor(BaseExecutor):
    supported_type = "condition"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        conditions = node_data.get("conditions") or []
        selected_branch = "default"
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            condition_id = condition.get("id")
            field = condition.get("field")
            operator = condition.get("operator")
            expected = condition.get("value")
            actual = self._resolve_field(input_data, field)
            if self._evaluate(actual, operator, expected):
                selected_branch = condition_id
                break
        output = dict(input_data)
        output["__selectedBranch__"] = selected_branch
        output["__conditionNodeId__"] = node.get("id")
        return output

    def _resolve_field(self, input_data: dict, field: Optional[str]) -> Any:
        if not field:
            return None
        result = self._resolve_from_map(input_data, field)
        if result is not None:
            return result
        input_value = input_data.get("input")
        if isinstance(input_value, str):
            try:
                parsed = json.loads(input_value)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return self._resolve_from_map(parsed, field)
        return None

    @staticmethod
    def _resolve_from_map(mapping: dict, field: str) -> Any:
        current: Any = mapping
        for part in field.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _evaluate(self, actual: Any, operator: Optional[str], expected: Any) -> bool:
        if operator is None:
            return False
        if operator == "eq":
            return self._is_equal(actual, expected)
        if operator == "neq":
            return not self._is_equal(actual, expected)
        if operator in ("gt", "gte", "lt", "lte"):
            compared = self._compare_numbers(actual, expected)
            return {"gt": compared > 0, "gte": compared >= 0, "lt": compared < 0, "lte": compared <= 0}[operator]
        if operator == "contains":
            return actual is not None and str(expected) in str(actual)
        if operator == "notContains":
            return not (actual is not None and str(expected) in str(actual))
        if operator == "startsWith":
            return actual is not None and str(actual).startswith(str(expected))
        if operator == "endsWith":
            return actual is not None and str(actual).endswith(str(expected))
        if operator == "isEmpty":
            return self._is_empty(actual)
        if operator == "isNotEmpty":
            return not self._is_empty(actual)
        return False

    @staticmethod
    def _is_numeric(value: Any) -> bool:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        try:
            float(str(value))
            return True
        except (TypeError, ValueError):
            return False

    def _is_equal(self, actual: Any, expected: Any) -> bool:
        if actual is None and expected is None:
            return True
        if actual is None or expected is None:
            return False
        if self._is_numeric(actual) and self._is_numeric(expected):
            return float(actual) == float(expected)
        return str(actual) == str(expected)

    @staticmethod
    def _compare_numbers(actual: Any, expected: Any) -> int:
        if actual is None or expected is None:
            return -1 if actual is None else 1
        try:
            left = float(actual)
            right = float(expected)
        except (TypeError, ValueError):
            left_text = str(actual)
            right_text = str(expected)
            return (left_text > right_text) - (left_text < right_text)
        return (left > right) - (left < right)

    @staticmethod
    def _is_empty(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value == ""
        if isinstance(value, (dict, list)):
            return len(value) == 0
        return False


class LlmNodeExecutor(AbstractAgentPlanExecutor):
    supported_type = "llm"

    def __init__(self) -> None:
        self.react_executor = ReActExecutor()

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        if self._is_react_enabled(node_data):
            return self.react_executor.execute(db, node, input_data, progress)
        return self._execute_llm(db, node, input_data, progress, node.get("type") or "llm")

    @staticmethod
    def _is_react_enabled(node_data: dict) -> bool:
        strategy = node_data.get("agentStrategy")
        if strategy is not None and str(strategy).strip().lower() == "react":
            return True
        tools = node_data.get("tools")
        if isinstance(tools, list):
            return len(tools) > 0
        return isinstance(tools, str) and bool(tools.strip())

    def _extract_config(self, db: Session, node: dict) -> dict:
        node_data = node.get("data") or {}
        config_id = to_int(node_data.get("configId"))
        provider = None
        api_url = None
        api_key = None
        model = None

        if config_id is not None:
            global_config = llm_config_service.get_by_id(db, config_id)
            if global_config is not None:
                api_url = text_or_none(global_config.api_url)
                api_key = text_or_none(global_config.api_key)
                model = text_or_none(global_config.model)
                provider = llm.normalize_provider(text_or_none(global_config.provider))
            else:
                provider = llm.normalize_provider(text_or_none(node_data.get("provider")))
                api_url = text_or_none(node_data.get("apiUrl"))
                api_key = text_or_none(node_data.get("apiKey"))
                model = text_or_none(node_data.get("model"))
        else:
            provider = llm.normalize_provider(text_or_none(node_data.get("provider")))
            api_url = text_or_none(node_data.get("apiUrl"))
            api_key = text_or_none(node_data.get("apiKey"))
            model = text_or_none(node_data.get("model"))

        temperature = to_float(node_data.get("temperature"), 0.7)
        if not provider:
            if node.get("type") == "llm":
                provider = None
            else:
                provider = llm.normalize_provider(node.get("type"))

        return {
            "configId": config_id,
            "provider": provider,
            "apiUrl": api_url,
            "apiKey": api_key,
            "model": model,
            "temperature": 0.7 if temperature is None else temperature,
            "prompt": node_data.get("prompt"),
            "inputParams": node_data.get("inputParams") or [],
            "outputParams": node_data.get("outputParams") or [],
            "streaming": truthy(node_data.get("streaming")),
            "skillName": text_or_none(node_data.get("skillName")),
        }

    @staticmethod
    def _validate_config(config: dict, node_type: str) -> None:
        if not config.get("provider"):
            raise ValueError("LLM 节点缺少有效的提供商配置，请先选择供应商或全局配置")
        if not (config.get("apiUrl") and config.get("apiKey") and config.get("model")):
            raise ValueError(f"{node_type.upper()} 节点缺少有效的模型配置，请检查全局配置或节点配置")

    def _execute_llm(self, db: Session, node: dict, input_data: dict, progress: Progress, node_type: str) -> dict:
        config = self._extract_config(db, node)
        self._validate_config(config, node_type)

        skill = None
        skill_references: dict[str, str] = {}
        if config["skillName"]:
            skill = skill_registry.get_skill(config["skillName"])
            if skill is not None:
                skill_references = skill_registry.load_all_references(config["skillName"])

        system_prompt = ""
        if skill is not None:
            system_prompt = skill.full_execution_prompt(skill_references) + "\n\n---\n\n"

        user_prompt = llm.prompt_template_service.process_template(config["prompt"], config["inputParams"], input_data)
        context_query = self._resolve_context_query(config["inputParams"], input_data, user_prompt)
        context_prompt = self._build_context_prompt(db, node, context_query)
        if context_prompt:
            user_prompt = context_prompt + "\n\n---\n\n用户任务:\n" + user_prompt

        messages: list[dict] = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        on_chunk = None
        if config["streaming"] and progress is not None:
            def on_chunk(chunk: str, accumulated: str) -> None:
                progress("生成中...", {"chunk": chunk, "accumulated": accumulated})

        llm_response = llm.chat_completion(
            config["provider"],
            config["apiUrl"],
            config["apiKey"],
            config["model"],
            config["temperature"],
            messages,
            on_chunk=on_chunk,
        )
        return self._build_output(llm_response, config["outputParams"])

    @staticmethod
    def _resolve_context_query(input_params: list[dict], input_data: dict, user_prompt: str) -> str:
        for param in input_params or []:
            if str(param.get("type")) != "reference":
                continue
            reference_node = param.get("referenceNode")
            if reference_node is None:
                continue
            reference = str(reference_node)
            ref_param_name = reference.rsplit(".", 1)[-1] if "." in reference else reference
            ref_value = input_data.get(ref_param_name)
            if ref_value is None and ref_param_name == "user_input":
                ref_value = input_data.get("input")
            text = "" if ref_value is None else str(ref_value).strip()
            if text:
                return text
        direct_input = input_data.get("input")
        text = "" if direct_input is None else str(direct_input).strip()
        return text if text else user_prompt

    def _build_context_prompt(self, db: Session, node: dict, query: str) -> str:
        node_data = node.get("data") or {}
        parts: list[str] = []
        if truthy(node_data.get("memoryEnabled")):
            try:
                top_k = self.int_data(node_data, "memoryTopK", 5)
                embedding: list[float] = []
                memory_config = agent_plan.resolve(db, node_data, "memory")
                if memory_config.api_url and memory_config.api_key and memory_config.model:
                    embedding = agent_plan.agent_plan_client.create_embedding(memory_config, query)
                memory_result = agent_plan.memory_service.retrieve(query, "workflow", [], embedding, top_k)
                memory_context = str(memory_result.get("context") or "").strip()
                if memory_context:
                    parts.append("相关记忆:\n" + memory_context + "\n\n")
            except Exception as exc:
                logger.warning("记忆召回失败: %s", exc)

        knowledge_base_id = text_or_none(node_data.get("knowledgeBaseId"))
        if knowledge_base_id:
            try:
                top_k = self.int_data(node_data, "knowledgeTopK", 5)
                threshold = self.double_data(node_data, "knowledgeScoreThreshold", 0.2)
                knowledge_result = knowledge.search_runtime(db, knowledge_base_id, query, top_k, threshold)
                knowledge_context = str(knowledge_result.get("context") or "").strip()
                if knowledge_context:
                    parts.append("知识库上下文:\n" + knowledge_context + "\n\n")
            except Exception as exc:
                logger.warning("知识库召回失败: %s", exc)

        if not parts:
            return ""
        return (
            "以下是可用于回答当前任务的上下文。若上下文与任务无关，请忽略；若相关，请优先依据上下文回答。\n\n"
            + "".join(parts).strip()
        )

    @staticmethod
    def _build_output(response: dict, output_params: list[dict]) -> dict:
        content = response.get("content")
        output: dict[str, Any] = {}
        if output_params:
            for param in output_params:
                output[str(param.get("name"))] = content
        else:
            output["output"] = content
        total = response.get("totalTokens") or 0
        output["inputTokens"] = response.get("inputTokens") or 0
        output["outputTokens"] = response.get("outputTokens") or 0
        output["totalTokens"] = total
        output["tokens"] = total
        return output


class ReActExecutor(AbstractAgentPlanExecutor):
    supported_type = "react_agent"
    DEFAULT_MAX_STEPS = 5
    MAX_ALLOWED_STEPS = 20

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        llm_executor = LlmNodeExecutor()
        config = llm_executor._extract_config(db, node)
        if not config.get("provider"):
            raise ValueError("ReAct Agent 缺少有效的提供商配置")
        if not (config.get("apiUrl") and config.get("apiKey") and config.get("model")):
            raise ValueError("ReAct Agent 缺少有效的模型配置，请检查全局配置或节点配置")
        if not config.get("prompt"):
            raise ValueError("ReAct Agent 缺少任务提示词")

        goal_prompt = llm.prompt_template_service.process_template(config["prompt"], config["inputParams"], input_data)
        max_steps = self._resolve_max_steps(node_data)
        tool_names = self._resolve_tool_names(node_data)
        available_tools = get_tools(tool_names)
        if not available_tools:
            raise ValueError("ReAct Agent 至少需要启用一个工具")

        system_prompt = self._build_system_prompt(node_data, config, available_tools)
        trace: list[dict] = []
        totals = {"input": 0, "output": 0, "total": 0}
        tool_context = ToolContext(
            db=db,
            node_id=str(node.get("id")),
            node_type=str(node.get("type")),
            node_data=node_data,
            current_input=input_data,
        )

        for step in range(1, max_steps + 1):
            user_prompt = jdump(
                {
                    "goal": goal_prompt,
                    "currentInput": input_data,
                    "previousSteps": trace,
                    "step": step,
                    "maxSteps": max_steps,
                }
            )
            response = llm.chat_completion(
                config["provider"],
                config["apiUrl"],
                config["apiKey"],
                config["model"],
                config["temperature"],
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            totals["input"] += response.get("inputTokens") or 0
            totals["output"] += response.get("outputTokens") or 0
            totals["total"] += response.get("totalTokens") or 0
            content = response.get("content") or ""
            decision = self._parse_decision(content)

            trace_item: dict[str, Any] = {
                "step": step,
                "action": decision["action"],
                "reasoningSummary": decision["reasoningSummary"],
            }
            if decision["action"] == "final_answer":
                trace_item["finalAnswer"] = decision["finalAnswer"]
                trace.append(trace_item)
                if progress:
                    progress("ReAct 完成", trace_item)
                return self._build_output(decision["finalAnswer"], trace, totals, False, None)

            if decision["action"] != "tool_call":
                trace_item["finalAnswer"] = content
                trace.append(trace_item)
                if progress:
                    progress("ReAct 返回非标准动作，按最终答案处理", trace_item)
                return self._build_output(content, trace, totals, False, None)

            tool_name = decision["toolName"]
            tool = get_required_tool(tool_name)
            tool_input = decision["toolInput"]
            try:
                observation = tool.execute(tool_input, tool_context)
            except Exception as exc:
                logger.warning("ReAct 工具调用失败: node=%s tool=%s error=%s", node.get("id"), tool_name, exc)
                observation = {"error": str(exc), "recoverable": True}

            trace_item["toolName"] = tool_name
            trace_item["toolInput"] = tool_input
            trace_item["observation"] = observation
            trace.append(trace_item)
            if progress:
                progress(f"ReAct 工具调用: {tool_name}", trace_item)

        message = f"达到最大 ReAct 步数限制: {max_steps}"
        return self._build_output(message, trace, totals, True, message)

    def _build_system_prompt(self, node_data: dict, config: dict, available_tools: list) -> str:
        parts = [
            "你是一个运行在 AgentFlow 工作流节点里的 ReAct Agent。\n",
            "你必须通过 JSON 决策进行工具调用或给出最终答案，不要输出 Markdown 代码块。\n",
            "不要暴露完整隐藏推理链，只在 reasoningSummary 字段给一句简短行动理由。\n\n",
        ]
        if text_or_none(node_data.get("knowledgeBaseId")):
            parts.append(
                "当前节点已配置知识库。回答项目资料、实现计划、配置字段或节点说明相关问题时，"
                "必须先调用 knowledge_retrieve 检索知识库，再基于 observation 回答。\n\n"
            )
        skill_name = config.get("skillName")
        if skill_name:
            skill = skill_registry.get_skill(skill_name)
            if skill is not None:
                parts.append(f"当前节点关联 Skill: {skill.name}\n")
                parts.append(skill.summary() + "\n\n")
        parts.append("可用工具:\n")
        for tool in available_tools:
            parts.append(f"- name: {tool.name}\n")
            parts.append(f"  description: {tool.description}\n")
            parts.append(f"  inputSchema: {tool.input_schema}\n")
        parts.append(
            "\n每次只返回下面两种 JSON 之一：\n"
            '{"action":"tool_call","reasoningSummary":"为什么需要这个工具","toolName":"工具名","toolInput":{}}\n'
            '{"action":"final_answer","reasoningSummary":"为什么可以结束","finalAnswer":"最终答案"}\n'
        )
        return "".join(parts)

    def _parse_decision(self, content: Optional[str]) -> dict:
        cleaned = self._strip_code_fence(content)
        try:
            payload = json.loads(cleaned)
            action = self._normalize_action(payload.get("action"))
            reasoning = payload.get("reasoningSummary") or ""
            tool_name = first_text(payload.get("toolName"), payload.get("tool_name"))
            tool_input = payload.get("toolInput", payload.get("tool_input", payload.get("arguments")))
            if not isinstance(tool_input, dict):
                tool_input = {}
            final_answer = payload.get("finalAnswer", payload.get("final_answer", payload.get("answer", payload.get("content"))))
            return {
                "action": action,
                "reasoningSummary": str(reasoning),
                "toolName": tool_name,
                "toolInput": tool_input,
                "finalAnswer": "" if final_answer is None else str(final_answer),
            }
        except Exception:
            logger.warning("ReAct 响应不是合法 JSON，按最终答案处理")
            return {
                "action": "final_answer",
                "reasoningSummary": "模型直接返回了最终内容",
                "toolName": None,
                "toolInput": {},
                "finalAnswer": content or "",
            }

    @staticmethod
    def _strip_code_fence(content: Optional[str]) -> str:
        if content is None:
            return ""
        trimmed = content.strip()
        if not trimmed.startswith(FENCE):
            return trimmed
        first_newline = trimmed.find("\n")
        last_fence = trimmed.rfind(FENCE)
        if first_newline >= 0 and last_fence > first_newline:
            return trimmed[first_newline + 1 : last_fence].strip()
        return trimmed

    @staticmethod
    def _normalize_action(action: Any) -> str:
        if action is None or not str(action).strip():
            return "final_answer"
        normalized = str(action).strip().lower()
        if normalized in ("tool", "call_tool", "function_call"):
            return "tool_call"
        if normalized in ("final", "answer"):
            return "final_answer"
        return normalized

    def _resolve_max_steps(self, node_data: dict) -> int:
        value = node_data.get("maxSteps")
        if value is None:
            return self.DEFAULT_MAX_STEPS
        parsed = to_int(value, self.DEFAULT_MAX_STEPS) or self.DEFAULT_MAX_STEPS
        return max(1, min(self.MAX_ALLOWED_STEPS, parsed))

    def _resolve_tool_names(self, node_data: dict) -> list[str]:
        value = node_data.get("tools")
        if value is None:
            tool_names: list[str] = []
        elif isinstance(value, list):
            tool_names = [str(item) for item in value if str(item).strip()]
        else:
            tool_names = [part.strip() for part in str(value).split(",") if part.strip()]
        if text_or_none(node_data.get("knowledgeBaseId")) and "knowledge_retrieve" not in tool_names:
            tool_names = list(tool_names) + ["knowledge_retrieve"]
        if "web_search" in tool_names and "web_fetch" not in tool_names:
            tool_names = list(tool_names) + ["web_fetch"]
        return tool_names

    @staticmethod
    def _build_output(final_answer: str, trace: list[dict], totals: dict, max_steps_reached: bool, stop_reason: Optional[str]) -> dict:
        output = {
            "output": final_answer,
            "finalAnswer": final_answer,
            "toolTrace": trace,
            "steps": len(trace),
            "maxStepsReached": max_steps_reached,
        }
        if stop_reason:
            output["stopReason"] = stop_reason
        output["inputTokens"] = totals["input"]
        output["outputTokens"] = totals["output"]
        output["totalTokens"] = totals["total"]
        output["tokens"] = totals["total"]
        return output

class TtsExecutor(BaseExecutor):
    supported_type = "tts"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        return tts.synthesize(db, node_data, input_data, progress)


class ImageGenerateExecutor(AbstractAgentPlanExecutor):
    supported_type = "image_generate"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        prompt = self.configured_text_input(node_data, input_data, "prompt")
        if prompt is None:
            prompt = self.text_value(node_data, input_data, "prompt", "input")
        if prompt is None:
            raise ValueError("图片生成节点缺少 prompt")

        config = agent_plan.resolve_image_config(db, node_data)
        agent_plan.validate_api_config(config, "图片生成")

        reference_image_url = self.string_data(node_data, "referenceImageUrl", None)
        size = self.string_data(node_data, "size", "2K")
        count = self.int_data(node_data, "count", 1)
        negative_prompt = self.string_data(node_data, "negativePrompt", None)
        style = self.string_data(node_data, "style", None)
        steps = self.int_data(node_data, "steps", 0)
        cfg_scale = self.double_data(node_data, "cfgScale", 0)
        seed = self.int_data(node_data, "seed", 0)
        text_mode = truthy(node_data.get("textMode", True))

        if config.provider == "volcengine_agent_plan":
            result = agent_plan.agent_plan_client.generate_image(
                config, prompt, reference_image_url, size, count, negative_prompt, style
            )
        elif config.provider == "step":
            result = stepfun_image_client.generate_image(
                config, prompt, reference_image_url, size, count, negative_prompt, style, steps, cfg_scale, seed, text_mode
            )
        else:
            result = openai_image_client.generate_image(
                config, prompt, reference_image_url, size, count, negative_prompt, style
            )

        source_urls = result.get("imageUrls") or []
        timestamp = int(time.time() * 1000)
        persisted: list[str] = []
        for source_url in source_urls:
            persisted.append(self._persist_media(source_url, f"images/generated-{timestamp}.png", "image/png"))

        output = {
            "imageUrl": persisted[0] if persisted else None,
            "imageUrls": persisted,
            "prompt": prompt,
            "model": config.model,
            "metadata": result.get("metadata"),
            "output": persisted[0] if persisted else None,
        }
        self.apply_output_params(node_data, output)
        return output

    @staticmethod
    def _persist_media(source_url: Optional[str], object_name: str, content_type: str) -> Optional[str]:
        if not source_url:
            return source_url
        try:
            if source_url.startswith("data:image/"):
                comma = source_url.find(",")
                if comma > 0:
                    data = base64.b64decode(source_url[comma + 1 :])
                    return minio_service.upload_from_bytes(data, object_name, content_type)
            return minio_service.upload_from_url(source_url, object_name, content_type)
        except Exception as exc:
            logger.warning("图片转存 MinIO 失败，保留原始 URL: %s", exc)
            return source_url


class VideoGenerateExecutor(AbstractAgentPlanExecutor):
    supported_type = "video_generate"
    MAX_POLLS = 60
    POLL_INTERVAL_SECONDS = 5

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        prompt = self.configured_text_input(node_data, input_data, "prompt")
        if prompt is None:
            prompt = self.text_value(node_data, input_data, "prompt", "input")
        if prompt is None:
            raise ValueError("视频生成节点缺少 prompt")

        reference_image_url = self.configured_text_input(node_data, input_data, "referenceImageUrl")
        if reference_image_url is None:
            reference_image_url = self.string_data(node_data, "referenceImageUrl", None)

        config = agent_plan.resolve(db, node_data, "video")
        agent_plan.validate_api_config(config, "视频生成")

        agnes_provider = bool(config.provider and config.provider.strip().lower() == "agnes")
        duration = self.int_data(node_data, "duration", 5)
        resolution = self.string_data(node_data, "resolution", None)
        ratio = self.string_data(node_data, "ratio", "adaptive")
        camera_motion = self.string_data(node_data, "cameraMotion", None)

        node_id = str(node.get("id"))
        node_type = str(node.get("type"))

        def emit(message: str, data: Any) -> None:
            if progress:
                progress(message, data)

        emit(
            "视频任务提交中: provider="
            + str(config.provider)
            + ", model="
            + str(config.model)
            + ", 时长="
            + str(duration)
            + "s"
            + ", 首帧="
            + ("有" if reference_image_url else "无"),
            {
                "provider": config.provider,
                "model": config.model,
                "duration": duration,
                "hasFirstFrame": bool(reference_image_url),
            },
        )

        if agnes_provider:
            task_id = agnes_video_client.create_video_task(
                config, prompt, reference_image_url, duration, resolution, ratio, camera_motion
            )
        else:
            task_id = agent_plan.agent_plan_client.create_video_task(
                config, prompt, reference_image_url, duration, resolution, ratio, camera_motion
            )
        if not task_id:
            raise RuntimeError("视频生成接口未返回 taskId")
        emit(f"视频任务已提交: taskId={self._short_id(task_id)}", {"taskId": task_id})

        task: dict = {"status": "running"}
        started_at = time.time()
        for poll in range(1, self.MAX_POLLS + 1):
            time.sleep(self.POLL_INTERVAL_SECONDS)
            if agnes_provider:
                task = agnes_video_client.get_video_task(config, task_id)
            else:
                task = agent_plan.agent_plan_client.get_video_task(config, task_id)
            status = str(task.get("status", ""))
            message = self._polling_message(task_id, poll, status, task.get("progress"), started_at)
            data = self._polling_data(task_id, poll, status, task.get("progress"), started_at)
            emit(message, data)
            if self._is_success(status):
                emit(self._complete_message(task_id, status, task.get("progress")), data)
                break
            if self._is_failed(status):
                raise RuntimeError(f"视频生成失败: {task}")

        video_url = _as_text(task.get("videoUrl"))
        cover_url = _as_text(task.get("coverUrl"))
        if not video_url:
            raise RuntimeError(f"视频生成超时或未返回 videoUrl: {task}")

        emit(f"视频转存中: taskId={self._short_id(task_id)}", {"taskId": task_id, "sourceUrl": video_url})
        persisted_video_url = self._persist_media(video_url, f"videos/generated-{task_id}.mp4", "video/mp4")

        output = {
            "taskId": task_id,
            "status": "succeeded",
            "videoUrl": persisted_video_url,
            "coverUrl": cover_url,
            "model": config.model,
            "metadata": task.get("raw"),
            "output": persisted_video_url,
        }
        self.apply_output_params(node_data, output)
        return output

    def _polling_message(self, task_id: str, poll: int, status: str, progress: Any, started_at: float) -> str:
        message = (
            f"视频生成中: 第 {poll}/{self.MAX_POLLS} 次查询, 已等待 {self._elapsed_seconds(started_at)}s, "
            f"状态={status or 'unknown'}"
        )
        progress_text = self._format_progress(progress)
        if progress_text:
            message += f", 进度={progress_text}"
        return message + f", taskId={self._short_id(task_id)}"

    def _complete_message(self, task_id: str, status: str, progress: Any) -> str:
        message = f"视频生成完成: 状态={status or 'completed'}"
        progress_text = self._format_progress(progress)
        if progress_text:
            message += f", 进度={progress_text}"
        return message + f", taskId={self._short_id(task_id)}"

    def _polling_data(self, task_id: str, poll: int, status: str, progress: Any, started_at: float) -> dict:
        data = {
            "taskId": task_id,
            "poll": poll,
            "maxPolls": self.MAX_POLLS,
            "elapsedSeconds": self._elapsed_seconds(started_at),
            "status": status,
        }
        if progress is not None:
            data["progress"] = progress
        return data

    @staticmethod
    def _elapsed_seconds(started_at: float) -> int:
        return max(0, int(time.time() - started_at))

    @staticmethod
    def _format_progress(progress: Any) -> Optional[str]:
        if progress is None:
            return None
        if isinstance(progress, (int, float)) and not isinstance(progress, bool):
            value = float(progress)
            if value <= 1.0:
                value *= 100
            if abs(value - round(value)) < 0.0001:
                return f"{int(round(value))}%"
            return f"{value:.1f}%"
        text = str(progress).strip()
        if not text:
            return None
        return text if text.endswith("%") else text + "%"

    @staticmethod
    def _short_id(task_id: str) -> str:
        if not task_id or len(task_id) <= 16:
            return task_id
        return task_id[:8] + "..." + task_id[-6:]

    @staticmethod
    def _is_success(status: str) -> bool:
        normalized = status.lower()
        return "success" in normalized or "succeed" in normalized or "completed" in normalized

    @staticmethod
    def _is_failed(status: str) -> bool:
        normalized = status.lower()
        return "fail" in normalized or "error" in normalized or "cancel" in normalized

    @staticmethod
    def _persist_media(source_url: str, object_name: str, content_type: str) -> str:
        try:
            return minio_service.upload_from_url(source_url, object_name, content_type)
        except Exception as exc:
            logger.warning("视频转存 MinIO 失败，保留原始 URL: %s", exc)
            return source_url


class MemoryWriteExecutor(AbstractAgentPlanExecutor):
    supported_type = "memory_write"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        content = self.text_value(node_data, input_data, "content", "output")
        if content is None:
            raise ValueError("写入记忆节点缺少 content")

        config = agent_plan.resolve(db, node_data, "memory")
        embedding: list[float] = []
        if config.api_url and config.api_key and config.model:
            embedding = agent_plan.agent_plan_client.create_embedding(config, content)

        return agent_plan.memory_service.write(
            content,
            self.string_data(node_data, "memoryType", "fact") or "fact",
            self.string_data(node_data, "scope", "workflow") or "workflow",
            agent_plan.memory_service.split_tags(self.string_data(node_data, "tags", "")),
            str(node.get("id")),
            embedding,
            config.model,
        )


class MemoryRetrieveExecutor(AbstractAgentPlanExecutor):
    supported_type = "memory_retrieve"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        query = self.text_value(node_data, input_data, "query", "input")
        if query is None:
            raise ValueError("召回记忆节点缺少 query")

        config = agent_plan.resolve(db, node_data, "memory")
        embedding: list[float] = []
        if config.api_url and config.api_key and config.model:
            embedding = agent_plan.agent_plan_client.create_embedding(config, query)

        output = agent_plan.memory_service.retrieve(
            query,
            self.string_data(node_data, "scope", "workflow") or "workflow",
            agent_plan.memory_service.split_tags(self.string_data(node_data, "tags", "")),
            embedding,
            self.int_data(node_data, "topK", 5),
        )
        output["output"] = output.get("context")
        return output


class KnowledgeUpsertExecutor(AbstractAgentPlanExecutor):
    supported_type = "knowledge_upsert"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        content = self.text_value(node_data, input_data, "content", "output")
        if content is None:
            raise ValueError("写入知识库节点缺少 content")

        config = agent_plan.resolve(db, node_data, "knowledge")
        embedding: list[float] = []
        if config.api_url and config.api_key and config.model:
            embedding = agent_plan.agent_plan_client.create_embedding(config, content)

        output = knowledge.upsert(
            db,
            self.string_data(node_data, "knowledgeBaseId", "default") or "default",
            self.string_data(node_data, "title", None),
            content,
            self.string_data(node_data, "sourceUrl", None),
            agent_plan.memory_service.split_tags(self.string_data(node_data, "tags", "")),
            embedding,
            config.model,
        )
        output["output"] = output.get("contentId")
        return output


class KnowledgeRetrieveExecutor(AbstractAgentPlanExecutor):
    supported_type = "knowledge_retrieve"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        query = self.text_value(node_data, input_data, "query", "input")
        if query is None:
            raise ValueError("检索知识库节点缺少 query")

        config = agent_plan.resolve(db, node_data, "knowledge")
        embedding: list[float] = []
        if config.api_url and config.api_key and config.model:
            embedding = agent_plan.agent_plan_client.create_embedding(config, query)

        output = knowledge.retrieve(
            db,
            self.string_data(node_data, "knowledgeBaseId", "default") or "default",
            query,
            embedding,
            self.int_data(node_data, "topK", 5),
            self.double_data(node_data, "scoreThreshold", 0.2),
        )
        output["output"] = output.get("context")
        return output


class WebSearchExecutor(AbstractAgentPlanExecutor):
    supported_type = "web_search"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        query = self.text_value(node_data, input_data, "query", "input")
        if query is None:
            raise ValueError("联网搜索节点缺少 query")

        limit = self.int_data(node_data, "limit", 5)
        freshness = self.string_data(node_data, "freshness", None)
        language = self.string_data(node_data, "language", "zh")
        selected = mcp.resolve_first_enabled_web_search(db, node_data.get("mcpToolIds"))
        if selected is None:
            raise ValueError("联网搜索节点未配置，请先在 MCP 工具中添加 Agent Plan 联网搜索，并在当前节点选择它")

        search_result = mcp.web_search(
            selected,
            query,
            limit,
            self._normalize_time_range(freshness),
            None,
            "image" if (language or "").lower() == "image" else "web",
        )
        return {
            "query": query,
            "summary": search_result.get("summary"),
            "results": search_result.get("results"),
            "citations": search_result.get("citations"),
            "output": search_result.get("summary"),
            "metadata": search_result.get("raw"),
        }

    @staticmethod
    def _normalize_time_range(freshness: Optional[str]) -> Optional[str]:
        if not freshness:
            return None
        mapping = {
            "day": "OneDay",
            "OneDay": "OneDay",
            "week": "OneWeek",
            "OneWeek": "OneWeek",
            "month": "OneMonth",
            "OneMonth": "OneMonth",
            "year": "OneYear",
            "OneYear": "OneYear",
        }
        return mapping.get(freshness, freshness)


class WebFetchExecutor(AbstractAgentPlanExecutor):
    supported_type = "web_fetch"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        urls_text = self.text_value(node_data, input_data, "urls", "url")
        if urls_text is None:
            raise ValueError("网页读取节点缺少 urls")

        pages: list[dict] = []
        content_parts: list[str] = []
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
            for url in re.split(r"[,，\n\s]+", urls_text):
                if not url.strip():
                    continue
                response = client.get(url.strip(), headers={"User-Agent": "AgentFlow/1.0"})
                text = response.text[:8000]
                pages.append({"url": url.strip(), "content": text})
                content_parts.append(f"URL: {url.strip()}\n{text}\n\n")
        content = "".join(content_parts).strip()
        return {
            "pages": pages,
            "content": content,
            "citations": [page["url"] for page in pages],
            "output": content,
        }


class VisionAnalyzeExecutor(AbstractAgentPlanExecutor):
    supported_type = "vision_analyze"

    def execute(self, db: Session, node: dict, input_data: dict, progress: Progress = None) -> dict:
        node_data = node.get("data") or {}
        image_url = self.text_value(node_data, input_data, "imageUrl", "imageUrl")
        video_url = self.text_value(node_data, input_data, "videoUrl", "videoUrl")
        criteria = self.string_data(node_data, "criteria", "判断素材是否满足输入要求，给出问题列表和 0-100 分。")
        if image_url is None and video_url is None:
            raise ValueError("视觉质检节点缺少 imageUrl 或 videoUrl")

        config = agent_plan.resolve(db, node_data, "vision")
        agent_plan.validate_api_config(config, "视觉质检")

        prompt = (
            "请对下面的视觉素材做质检。\n"
            f"质检要求：{criteria}\n"
            f"图片 URL：{image_url or ''}\n"
            f"视频 URL：{video_url or ''}\n\n"
            "请用中文返回简洁结论，包含：描述、分数、问题列表、是否通过。\n"
        )
        response = llm.chat_completion(
            config.provider,
            config.api_url,
            config.api_key,
            config.model,
            0.2,
            [{"role": "user", "content": prompt}],
        )
        description = response.get("content")
        score = 60 if (description and "不通过" in description) else 85
        passed = score >= 80 and (description is None or "不通过" not in description)
        return {
            "description": description,
            "score": score,
            "issues": [] if passed else [description],
            "pass": passed,
            "output": description,
        }


_LLM_EXECUTOR = LlmNodeExecutor()
_REACT_EXECUTOR = ReActExecutor()

_EXECUTORS: dict[str, BaseExecutor] = {
    "input": InputExecutor(),
    "output": OutputExecutor(),
    "condition": ConditionExecutor(),
    "llm": _LLM_EXECUTOR,
    "react_agent": _REACT_EXECUTOR,
    "openai": _LLM_EXECUTOR,
    "deepseek": _LLM_EXECUTOR,
    "qwen": _LLM_EXECUTOR,
    "step": _LLM_EXECUTOR,
    "zhipu": _LLM_EXECUTOR,
    "ai_ping": _LLM_EXECUTOR,
    "tts": TtsExecutor(),
    "image_generate": ImageGenerateExecutor(),
    "video_generate": VideoGenerateExecutor(),
    "memory_write": MemoryWriteExecutor(),
    "memory_retrieve": MemoryRetrieveExecutor(),
    "knowledge_upsert": KnowledgeUpsertExecutor(),
    "knowledge_retrieve": KnowledgeRetrieveExecutor(),
    "web_search": WebSearchExecutor(),
    "web_fetch": WebFetchExecutor(),
    "vision_analyze": VisionAnalyzeExecutor(),
}


def get_executor(node_type: str) -> BaseExecutor:
    executor = _EXECUTORS.get(node_type)
    if executor is None:
        raise ValueError(f"不支持的节点类型: {node_type}")
    return executor
