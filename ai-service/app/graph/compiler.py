from __future__ import annotations

import json

from langgraph.graph import END, START, StateGraph

from app.core.errors import FlowValidationError
from app.graph.context import NodeContext
from app.graph.runtime import execute_node
from app.graph.state import FlowState
from app.nodes.registry import get_executor
from app.schemas.flow import Flow, FlowNode


def _router_targets(node: FlowNode) -> list[str]:
    config = node.config or {}
    raw = config.get("routes")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    targets: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and item.get("target"):
            targets.append(str(item["target"]).strip())
    fallback = str(config.get("fallbackTarget") or "").strip()
    if fallback:
        targets.append(fallback)
    return list(dict.fromkeys(target for target in targets if target))


def _effective_targets(flow: Flow, node: FlowNode) -> list[str]:
    if node.type == "llm_router":
        configured = _router_targets(node)
        if configured:
            return configured
        return [edge.target for edge in flow.outgoing(node.id)]
    if node.type == "condition":
        config = node.config or {}
        explicit = [config.get("trueBranch"), config.get("falseBranch")]
        explicit = [target for target in explicit if target]
        if explicit:
            return explicit
        return [edge.target for edge in flow.outgoing(node.id)]
    return [edge.target for edge in flow.outgoing(node.id)]


def effective_edges(flow: Flow) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for node in flow.nodes:
        for target in _effective_targets(flow, node):
            if target and target != node.id:
                edges.append((node.id, target))
    return edges


def find_entry(flow: Flow) -> FlowNode:
    targets = {target for _, target in effective_edges(flow)}
    entries = [node for node in flow.nodes if node.id not in targets]
    if not entries:
        raise FlowValidationError("工作流缺少入口节点（所有节点都有上游）")
    if len(entries) > 1:
        names = ", ".join(node.name or node.id for node in entries)
        raise FlowValidationError(f"工作流存在多个入口节点: {names}")
    return entries[0]


def validate_flow(flow: Flow) -> None:
    if not flow.nodes:
        raise FlowValidationError("工作流至少需要一个节点")

    ids = [node.id for node in flow.nodes]
    if len(ids) != len(set(ids)):
        raise FlowValidationError("节点 id 重复")

    for node in flow.nodes:
        get_executor(node.type)
        if not node.id.strip():
            raise FlowValidationError("节点 id 不能为空")

    known = set(ids)
    for edge in flow.edges:
        if edge.source not in known or edge.target not in known:
            raise FlowValidationError(f"边引用了不存在的节点: {edge.source} -> {edge.target}")

    for node in flow.nodes:
        if node.type in {"condition", "llm_router"}:
            targets = _effective_targets(flow, node)
            if not targets:
                label = "条件节点" if node.type == "condition" else "意图路由节点"
                raise FlowValidationError(f"{label} {node.name or node.id} 未配置分支目标")
            for target in targets:
                if target not in known:
                    label = "条件分支" if node.type == "condition" else "路由分支"
                    raise FlowValidationError(f"{label}指向不存在的节点: {target}")

    _assert_acyclic(flow)
    find_entry(flow)


def _assert_acyclic(flow: Flow) -> None:
    edges = effective_edges(flow)
    adjacency: dict[str, list[str]] = {node.id: [] for node in flow.nodes}
    indegree: dict[str, int] = {node.id: 0 for node in flow.nodes}
    for source, target in edges:
        adjacency[source].append(target)
        indegree[target] += 1

    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for nxt in adjacency[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if visited != len(flow.nodes):
        raise FlowValidationError("工作流中存在环，LangGraph 引擎要求有向无环图")


def build_graph(flow: Flow, ctx: NodeContext):
    validate_flow(flow)
    builder = StateGraph(FlowState)

    for node in flow.nodes:
        builder.add_node(node.id, _make_node_callable(node, ctx))

    entry = find_entry(flow)
    builder.add_edge(START, entry.id)

    for node in flow.nodes:
        if node.type in {"condition", "llm_router"}:
            builder.add_conditional_edges(node.id, _make_router(node))
        else:
            for edge in flow.outgoing(node.id):
                if edge.target != node.id:
                    builder.add_edge(node.id, edge.target)
        if not _effective_targets(flow, node):
            builder.add_edge(node.id, END)

    return builder.compile()


def _make_node_callable(node: FlowNode, ctx: NodeContext):
    async def _run(state: FlowState):
        return await execute_node(node, state, ctx)

    return _run


def _make_router(node: FlowNode):
    def _route(state: FlowState) -> str:
        result = (state.get("outputs") or {}).get(node.id) or {}
        branch = result.get("target") or result.get("branch")
        return branch or END

    return _route
