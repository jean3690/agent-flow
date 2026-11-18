"""RAG 范式节点：多路召回、HyDE、LLM 重排与引用式问答。"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.core.errors import NodeExecutionError
from app.core.template import render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.agent_paradigms import _chat, _json_from_text, _merge_usage, _model_of
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.nodes.value_utils import names_for, render_deep
from app.rag_client import (
    chunks_to_text,
    normalize_chunks,
    rrf_merge,
    search_knowledge,
)
from app.schemas.flow import FlowNode

MAX_QUERIES = 5
MAX_TOP_K = 10


def _knowledge_base_id(node: FlowNode) -> str:
    knowledge_base_id = str((node.config or {}).get("knowledgeBaseId") or "").strip()
    if not knowledge_base_id:
        raise NodeExecutionError(node.id, "节点未选择知识库")
    return knowledge_base_id


def _clamp(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return fallback


def _upstream_chunks(node: FlowNode, state: FlowState, ctx: NodeContext,
                     key: str = "source") -> list[dict[str, Any]]:
    raw = (node.config or {}).get(key)
    if raw is not None and raw != "":
        return normalize_chunks(render_deep(raw, names_for(state)))
    outputs = state.get("outputs") or {}
    for edge in reversed(ctx.flow.incoming(node.id)):
        output = outputs.get(edge.source)
        if isinstance(output, dict):
            chunks = normalize_chunks(output.get("chunks"))
            if chunks:
                return chunks
    return []


async def _search_many(ctx: NodeContext, knowledge_base_id: str,
                       queries: list[str], top_k: int) -> list[tuple[str, list[dict[str, Any]]]]:
    results = await asyncio.gather(*[
        search_knowledge(ctx, knowledge_base_id, query, top_k) for query in queries
    ])
    return list(zip(queries, results))


@register
class MultiQueryRetrieveNodeExecutor(NodeExecutor):
    """RAG-Fusion：查询扩展 + 多路召回 + RRF 融合。"""

    type = "multi_query_retrieve"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        knowledge_base_id = _knowledge_base_id(node)
        query = render(str(config.get("query") or "{{input}}"), names_for(state), strict=True).strip()
        if not query:
            raise NodeExecutionError(node.id, "多路召回节点缺少查询")
        num_queries = _clamp(config.get("numQueries"), 1, MAX_QUERIES, 3)
        per_query_top = _clamp(config.get("topK"), 1, MAX_TOP_K, 4)
        final_top = _clamp(config.get("finalTopK"), 1, MAX_TOP_K, 5)
        mock = ctx.mock_for(provider)
        usage: dict = {}

        if mock:
            expansions = [query, f"{query} 关键点", f"{query} 示例"][:num_queries]
            queries = list(dict.fromkeys(expansions))
        else:
            try:
                system = str(config.get("systemPrompt") or "").strip() or (
                    f"你是检索查询扩展器。围绕用户问题生成最多 {num_queries} 条不同角度的检索语句，"
                    "只输出 JSON 字符串数组，不要解释。"
                )
                answer, usage = await _chat(ctx, provider, model, system, query, temperature=0.4)
                parsed = _json_from_text(answer)
                queries = [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []
                queries = list(dict.fromkeys([query, *queries]))[:num_queries]
            except Exception as exc:  # noqa: BLE001 - 扩展失败时退回原查询
                ctx.emit("node_log", nodeId=node.id, level="warn", message=f"查询扩展失败，使用原查询: {exc}")
                queries = [query]
        try:
            groups = await _search_many(ctx, knowledge_base_id, queries, per_query_top)
        except Exception as exc:  # noqa: BLE001
            raise NodeExecutionError(node.id, f"多路召回失败: {exc}") from exc

        chunks = rrf_merge(groups, final_top)
        ctx.emit("node_log", nodeId=node.id, level="info",
                 message=f"{len(queries)} 路召回，融合后保留 {len(chunks)} 个片段")
        return {
            "text": chunks_to_text(chunks),
            "chunks": chunks,
            "queries": queries,
            "count": len(chunks),
            "knowledgeBaseId": knowledge_base_id,
            "provider": "mock" if mock else provider,
            "model": model,
            "usage": usage if not mock else {},
            "mock": mock,
        }


@register
class HydeRetrieveNodeExecutor(NodeExecutor):
    """HyDE：先生成假设性资料段落，再用原问题与假设段落做双路召回。"""

    type = "hyde_retrieve"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        knowledge_base_id = _knowledge_base_id(node)
        query = render(str(config.get("query") or "{{input}}"), names_for(state), strict=True).strip()
        if not query:
            raise NodeExecutionError(node.id, "HyDE 节点缺少查询")
        top_k = _clamp(config.get("topK"), 1, MAX_TOP_K, 4)
        final_top = _clamp(config.get("finalTopK"), 1, MAX_TOP_K, 5)
        mock = ctx.mock_for(provider)
        usage: dict = {}

        if mock:
            hypothetical = f"[mock] 关于「{query}」的假设性资料段落。"
        else:
            try:
                system = str(config.get("systemPrompt") or "").strip() or (
                    "你是知识库作者。写一段可能回答用户问题的资料段落，只输出段落正文，不要解释。"
                )
                hypothetical, usage = await _chat(ctx, provider, model, system, query, temperature=0.5)
            except Exception as exc:  # noqa: BLE001 - 生成失败时只用原查询
                ctx.emit("node_log", nodeId=node.id, level="warn", message=f"假设段落生成失败，使用原查询: {exc}")
                hypothetical = ""

        queries = list(dict.fromkeys([query, hypothetical])) if hypothetical.strip() else [query]
        try:
            groups = await _search_many(ctx, knowledge_base_id, queries, top_k)
        except Exception as exc:  # noqa: BLE001
            raise NodeExecutionError(node.id, f"HyDE 召回失败: {exc}") from exc
        chunks = rrf_merge(groups, final_top)
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"HyDE 双路召回保留 {len(chunks)} 个片段")
        return {
            "text": chunks_to_text(chunks),
            "chunks": chunks,
            "queries": queries,
            "hypothetical": hypothetical,
            "count": len(chunks),
            "knowledgeBaseId": knowledge_base_id,
            "provider": "mock" if mock else provider,
            "model": model,
            "usage": usage if not mock else {},
            "mock": mock,
        }


@register
class RerankNodeExecutor(NodeExecutor):
    """LLM 重排：按查询给候选片段打分并保留前 K 个。"""

    type = "rerank"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        query = render(str(config.get("query") or "{{input}}"), names_for(state), strict=True).strip()
        if not query:
            raise NodeExecutionError(node.id, "重排节点缺少查询")
        chunks = _upstream_chunks(node, state, ctx)
        if not chunks:
            raise NodeExecutionError(node.id, "重排节点没有可用的检索片段，请上游连接知识检索 / 多路召回")
        top_k = _clamp(config.get("topK"), 1, MAX_TOP_K, 5)
        mock = ctx.mock_for(provider)
        usage: dict = {}

        if mock:
            reranked = chunks[:top_k]
            for index, chunk in enumerate(reranked):
                chunk["rerankScore"] = round(10 - index * 0.5, 2)
        else:
            listing = "\n".join(
                f"[{index}] {item.get('title') or '片段'}\n{item['content'][:800]}"
                for index, item in enumerate(chunks)
            )
            try:
                system = str(config.get("systemPrompt") or "").strip() or (
                    "你是检索重排器。根据用户问题给每个候选片段打 0-10 分，"
                    "只输出 JSON 数组：[{\"index\": 0, \"score\": 9, \"reason\": \"简短原因\"}]，index 从 0 开始。"
                )
                answer, usage = await _chat(
                    ctx, provider, model, system,
                    f"问题：{query}\n\n候选片段：\n{listing}", temperature=0.1,
                )
                scored = _json_from_text(answer)
                scores: dict[int, float] = {}
                if isinstance(scored, list):
                    for item in scored:
                        if not isinstance(item, dict):
                            continue
                        try:
                            index = int(item.get("index"))
                            score = float(item.get("score"))
                        except (TypeError, ValueError):
                            continue
                        if 0 <= index < len(chunks):
                            scores[index] = max(0.0, min(10.0, score))
                if not scores:
                    raise ValueError("模型未返回有效评分")
                reranked = sorted(
                    [
                        {**chunk, "rerankScore": round(scores.get(index, 0.0), 2)}
                        for index, chunk in enumerate(chunks)
                    ],
                    key=lambda item: item["rerankScore"],
                    reverse=True,
                )[:top_k]
            except Exception as exc:  # noqa: BLE001 - 重排失败保留原顺序
                ctx.emit("node_log", nodeId=node.id, level="warn", message=f"重排失败，保留原顺序: {exc}")
                reranked = chunks[:top_k]

        ctx.emit("node_log", nodeId=node.id, level="info",
                 message=f"重排 {len(chunks)} 个片段，保留 {len(reranked)} 个")
        return {
            "text": chunks_to_text(reranked),
            "chunks": reranked,
            "count": len(reranked),
            "inputCount": len(chunks),
            "provider": "mock" if mock else provider,
            "model": model,
            "usage": usage if not mock else {},
            "mock": mock,
        }


@register
class RagAnswerNodeExecutor(NodeExecutor):
    """引用式问答：只依据检索片段回答，并标注来源编号。"""

    type = "rag_answer"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider, model = _model_of(config)
        query = render(str(config.get("query") or "{{input}}"), names_for(state), strict=True).strip()
        if not query:
            raise NodeExecutionError(node.id, "RAG 问答节点缺少问题")
        top_k = _clamp(config.get("topK"), 1, MAX_TOP_K, 4)
        require_citations = bool(config.get("requireCitations", True))

        knowledge_base_id = str(config.get("knowledgeBaseId") or "").strip()
        if knowledge_base_id:
            try:
                chunks = await search_knowledge(ctx, knowledge_base_id, query, top_k)
            except Exception as exc:  # noqa: BLE001
                raise NodeExecutionError(node.id, f"检索失败: {exc}") from exc
        else:
            chunks = _upstream_chunks(node, state, ctx)
        if not chunks:
            raise NodeExecutionError(node.id, "没有可用的检索片段，请连接知识检索 / 多路召回或选择知识库")

        mock = ctx.mock_for(provider)
        usage: dict = {}
        if mock:
            text = (
                f"[mock:{model}] 根据 {len(chunks)} 个检索片段整理的回答：\n"
                + "\n".join(f"[{index + 1}] {item['content'][:120]}" for index, item in enumerate(chunks[:3]))
            )
            cited = True
            citations = [
                {"index": index + 1, "title": item.get("title") or "", "chunkId": item.get("chunkId"),
                 "score": item.get("score")}
                for index, item in enumerate(chunks)
            ]
        else:
            documents = "\n\n".join(
                f"[{index + 1}] {item.get('title') or '片段'}\n{item['content'][:1500]}"
                for index, item in enumerate(chunks)
            )
            system = str(config.get("systemPrompt") or "").strip() or (
                "你只能依据给定资料回答。每个关键结论后用 [编号] 标注来源；"
                "资料不足时明确说“资料中没有相关信息”，不得编造。"
            )
            try:
                text, usage = await _chat(
                    ctx, provider, model, system,
                    f"问题：{query}\n\n资料：\n{documents}", temperature=0.2,
                )
            except Exception as exc:  # noqa: BLE001
                raise NodeExecutionError(node.id, f"RAG 问答失败: {exc}") from exc
            used = sorted({int(match) for match in re.findall(r"\[(\d+)\]", text)})
            citations = [
                {"index": index, "title": chunks[index - 1].get("title") or "",
                 "chunkId": chunks[index - 1].get("chunkId"), "score": chunks[index - 1].get("score")}
                for index in used if 1 <= index <= len(chunks)
            ]
            cited = bool(citations)
            if require_citations and not cited:
                ctx.emit("node_log", nodeId=node.id, level="warn", message="回答未包含来源编号，请检查提示词或模型")

        ctx.emit("node_log", nodeId=node.id, level="info",
                 message=f"基于 {len(chunks)} 个片段生成回答，引用 {len(citations)} 处")
        return {
            "text": text,
            "citations": citations,
            "chunks": chunks,
            "count": len(chunks),
            "cited": cited,
            "provider": "mock" if mock else provider,
            "model": model,
            "usage": usage if not mock else {},
            "mock": mock,
        }
