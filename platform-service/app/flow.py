from __future__ import annotations

import hashlib
import json
from typing import Any

from app.errors import BizError


def _nodes(flow: Any) -> list[dict[str, Any]]:
    if not isinstance(flow, dict):
        raise BizError("工作流 flow 必须是 JSON 对象")
    nodes = flow.get("nodes")
    if not isinstance(nodes, list):
        raise BizError("工作流 nodes 必须是数组")
    return nodes


def _collect_types(flow: dict[str, Any]) -> dict[str, str]:
    types: dict[str, str] = {}
    for node in _nodes(flow):
        if not isinstance(node, dict):
            raise BizError("节点定义必须是对象")
        node_id = str(node.get("id") or "")
        node_type = str(node.get("type") or "")
        if not node_id.strip():
            raise BizError("节点 id 不能为空")
        if not node_type.strip():
            raise BizError(f"节点 {node_id} 缺少 type")
        if node_id in types:
            raise BizError(f"节点 id 重复: {node_id}")
        types[node_id] = node_type
    return types


def _adjacency(types: dict[str, str], edges: Any) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in types}
    if isinstance(edges, list):
        for edge in edges:
            source = str(edge.get("source") or "") if isinstance(edge, dict) else ""
            target = str(edge.get("target") or "") if isinstance(edge, dict) else ""
            if source not in types or target not in types:
                raise BizError(f"边引用了不存在的节点: {source} -> {target}")
            adjacency[source].add(target)
    return adjacency


def _find_config(flow: dict[str, Any], node_id: str) -> dict[str, Any]:
    for node in flow.get("nodes") or []:
        if str(node.get("id") or "") == node_id:
            config = node.get("config")
            return config if isinstance(config, dict) else {}
    return {}


def _router_targets(config: dict[str, Any]) -> list[str]:
    routes = config.get("routes")
    if isinstance(routes, str):
        try:
            routes = json.loads(routes)
        except ValueError as exc:
            raise BizError("意图路由分支表不是合法 JSON") from exc
    targets: list[str] = []
    if isinstance(routes, list):
        for item in routes:
            target = str(item.get("target") or "").strip() if isinstance(item, dict) else ""
            if target and target not in targets:
                targets.append(target)
    fallback = str(config.get("fallbackTarget") or "").strip()
    if fallback and fallback not in targets:
        targets.append(fallback)
    return targets


def _effective(
    flow: dict[str, Any], types: dict[str, str], adjacency: dict[str, set[str]], strict: bool
) -> dict[str, list[str]]:
    effective: dict[str, list[str]] = {}
    for node_id, node_type in types.items():
        targets: list[str] = []
        if node_type == "condition":
            config = _find_config(flow, node_id)
            true_branch = str(config.get("trueBranch") or "")
            false_branch = str(config.get("falseBranch") or "")
            if true_branch.strip():
                targets.append(true_branch)
            if false_branch.strip():
                targets.append(false_branch)
            if not targets:
                targets = list(adjacency.get(node_id, ()))
            if not targets:
                if strict:
                    raise BizError(f"条件节点 {node_id} 未配置分支目标")
                effective[node_id] = targets
                continue
            for target in targets:
                if target not in types:
                    raise BizError(f"条件分支指向不存在的节点: {target}")
        elif node_type == "llm_router":
            targets = _router_targets(_find_config(flow, node_id))
            if not targets:
                targets = list(adjacency.get(node_id, ()))
            if not targets:
                if strict:
                    raise BizError(f"意图路由节点 {node_id} 未配置分支目标")
                effective[node_id] = targets
                continue
            for target in targets:
                if target not in types:
                    raise BizError(f"路由分支指向不存在的节点: {target}")
        else:
            targets = list(adjacency.get(node_id, ()))
        effective[node_id] = targets
    return effective


def _assert_acyclic(types: dict[str, str], effective: dict[str, list[str]]) -> None:
    indegree = {node_id: 0 for node_id in types}
    for targets in effective.values():
        for target in targets:
            indegree[target] = indegree.get(target, 0) + 1
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for nxt in effective.get(current, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited != len(types):
        raise BizError("工作流中存在环，LangGraph 引擎要求有向无环图")


def validate(flow: Any) -> None:
    if not isinstance(flow, dict):
        raise BizError("工作流 flow 必须是 JSON 对象")
    nodes = flow.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise BizError("工作流至少需要一个节点")
    types = _collect_types(flow)
    adjacency = _adjacency(types, flow.get("edges"))
    effective = _effective(flow, types, adjacency, True)
    _assert_acyclic(types, effective)
    targets: set[str] = set()
    for values in effective.values():
        targets.update(values)
    entries = [node_id for node_id in types if node_id not in targets]
    if not entries:
        raise BizError("工作流缺少入口节点（所有节点都有上游）")
    if len(entries) > 1:
        raise BizError("工作流存在多个入口节点: " + ", ".join(entries))


def validate_structure(flow: Any) -> None:
    if not isinstance(flow, dict):
        raise BizError("工作流 flow 必须是 JSON 对象")
    nodes = flow.get("nodes")
    if not isinstance(nodes, list):
        raise BizError("工作流 nodes 必须是数组")
    if not nodes:
        return
    types = _collect_types(flow)
    adjacency = _adjacency(types, flow.get("edges"))
    _assert_acyclic(types, _effective(flow, types, adjacency, False))


def execution_graph(flow: dict[str, Any]) -> dict[str, list[str]]:
    types = _collect_types(flow)
    return _effective(flow, types, _adjacency(types, flow.get("edges")), True)


def count_nodes(flow: Any) -> int:
    nodes = flow.get("nodes") if isinstance(flow, dict) else None
    return len(nodes) if isinstance(nodes, list) else 0


def _runtime_flow(flow: Any) -> dict[str, Any]:
    source = flow if isinstance(flow, dict) else {}
    engine = source.get("engineType") or source.get("engine_type") or "langgraph"
    nodes: list[dict[str, Any]] = []
    for node in source.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        nodes.append(
            {
                "id": node.get("id"),
                "type": node.get("type"),
                "config": config if isinstance(config, dict) else {},
            }
        )
    edges: list[dict[str, Any]] = []
    for edge in source.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        edges.append(
            {
                "source": edge.get("source"),
                "target": edge.get("target"),
                "sourceHandle": edge.get("sourceHandle") if "sourceHandle" in edge else edge.get("source_handle"),
            }
        )
    return {"engineType": engine, "nodes": nodes, "edges": edges}


def fingerprint(payload: dict[str, Any]) -> str:
    context: dict[str, Any] = {"storagePolicy": "per-user-v1"}
    for field in ("workflowId", "userId", "input", "providers", "mcpServers"):
        context[field] = payload.get(field)
    context["flow"] = _runtime_flow(payload.get("flow"))
    context["subflows"] = {
        str(key): _runtime_flow(value) for key, value in (payload.get("subflows") or {}).items()
    }
    context["mock"] = (payload.get("options") or {}).get("mock")
    canonical = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "v2:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
