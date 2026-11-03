package com.agentflow.util;

import com.agentflow.common.BizException;
import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Business-side sanity check for a workflow definition.
 * The authoritative executor is the Python LangGraph service; this runs first so the
 * user gets immediate feedback and we never persist an obviously broken graph.
 */
public final class FlowValidator {

    private FlowValidator() {
    }

    /**
     * 严格校验：用于执行前。要求图非空、存在且仅存在一个入口节点，且无环。
     * 新建/保存工作流请使用 {@link #validateStructure}，允许空白画布与未完成的编排。
     */
    public static void validate(JsonNode flow) {
        if (flow == null || !flow.isObject()) {
            throw new BizException("工作流 flow 必须是 JSON 对象");
        }
        JsonNode nodes = flow.get("nodes");
        if (nodes == null || !nodes.isArray() || nodes.isEmpty()) {
            throw new BizException("工作流至少需要一个节点");
        }
        Map<String, String> types = collectTypes(flow);
        Map<String, Set<String>> adjacency = buildAdjacency(types, flow.get("edges"));
        Map<String, List<String>> effective = buildEffective(flow, types, adjacency);
        assertAcyclic(types.keySet(), effective);

        Set<String> targets = new HashSet<>();
        effective.values().forEach(targets::addAll);
        List<String> entries = types.keySet().stream().filter(id -> !targets.contains(id)).toList();
        if (entries.isEmpty()) {
            throw new BizException("工作流缺少入口节点（所有节点都有上游）");
        }
        if (entries.size() > 1) {
            throw new BizException("工作流存在多个入口节点: " + String.join(", ", entries));
        }
    }

    /**
     * 结构校验：用于新建/保存工作流。只检查图的完整性（id/type 非空、无重复、
     * 边与条件分支引用存在的节点、无环），允许空白画布与尚未连接完成的编排。
     */
    public static void validateStructure(JsonNode flow) {
        if (flow == null || !flow.isObject()) {
            throw new BizException("工作流 flow 必须是 JSON 对象");
        }
        JsonNode nodes = flow.get("nodes");
        if (nodes == null || !nodes.isArray()) {
            throw new BizException("工作流 nodes 必须是数组");
        }
        if (nodes.isEmpty()) {
            return;
        }
        Map<String, String> types = collectTypes(flow);
        Map<String, Set<String>> adjacency = buildAdjacency(types, flow.get("edges"));
        Map<String, List<String>> effective = buildEffective(flow, types, adjacency);
        assertAcyclic(types.keySet(), effective);
    }

    private static Map<String, String> collectTypes(JsonNode flow) {
        Map<String, String> types = new LinkedHashMap<>();
        for (JsonNode node : flow.get("nodes")) {
            String id = node.path("id").asText("");
            String type = node.path("type").asText("");
            if (id.isBlank()) {
                throw new BizException("节点 id 不能为空");
            }
            if (type.isBlank()) {
                throw new BizException("节点 " + id + " 缺少 type");
            }
            if (types.put(id, type) != null) {
                throw new BizException("节点 id 重复: " + id);
            }
        }
        return types;
    }

    private static Map<String, Set<String>> buildAdjacency(Map<String, String> types, JsonNode edges) {
        Map<String, Set<String>> adjacency = new HashMap<>();
        types.keySet().forEach(id -> adjacency.put(id, new LinkedHashSet<>()));
        if (edges != null && edges.isArray()) {
            for (JsonNode edge : edges) {
                String source = edge.path("source").asText("");
                String target = edge.path("target").asText("");
                if (!types.containsKey(source) || !types.containsKey(target)) {
                    throw new BizException("边引用了不存在的节点: " + source + " -> " + target);
                }
                adjacency.get(source).add(target);
            }
        }
        return adjacency;
    }

    private static Map<String, List<String>> buildEffective(JsonNode flow, Map<String, String> types, Map<String, Set<String>> adjacency) {
        Map<String, List<String>> effective = new LinkedHashMap<>();
        for (Map.Entry<String, String> entry : types.entrySet()) {
            String id = entry.getKey();
            List<String> targets = new ArrayList<>();
            if ("condition".equals(entry.getValue())) {
                JsonNode config = findConfig(flow, id);
                String trueBranch = config.path("trueBranch").asText("");
                String falseBranch = config.path("falseBranch").asText("");
                if (!trueBranch.isBlank()) {
                    targets.add(trueBranch);
                }
                if (!falseBranch.isBlank()) {
                    targets.add(falseBranch);
                }
                if (targets.isEmpty()) {
                    targets.addAll(adjacency.get(id));
                }
                if (targets.isEmpty()) {
                    throw new BizException("条件节点 " + id + " 未配置分支目标");
                }
                for (String target : targets) {
                    if (!types.containsKey(target)) {
                        throw new BizException("条件分支指向不存在的节点: " + target);
                    }
                }
            } else {
                targets.addAll(adjacency.get(id));
            }
            effective.put(id, targets);
        }
        return effective;
    }

    public static int countNodes(JsonNode flow) {
        JsonNode nodes = flow == null ? null : flow.get("nodes");
        return nodes != null && nodes.isArray() ? nodes.size() : 0;
    }

    private static JsonNode findConfig(JsonNode flow, String nodeId) {
        for (JsonNode node : flow.get("nodes")) {
            if (nodeId.equals(node.path("id").asText())) {
                return node.path("config");
            }
        }
        return com.fasterxml.jackson.databind.node.JsonNodeFactory.instance.objectNode();
    }

    private static void assertAcyclic(Set<String> ids, Map<String, List<String>> effective) {
        Map<String, Integer> indegree = new HashMap<>();
        ids.forEach(id -> indegree.put(id, 0));
        for (Map.Entry<String, List<String>> entry : effective.entrySet()) {
            for (String target : entry.getValue()) {
                indegree.merge(target, 1, Integer::sum);
            }
        }
        List<String> queue = new ArrayList<>();
        indegree.forEach((id, degree) -> {
            if (degree == 0) {
                queue.add(id);
            }
        });
        int visited = 0;
        while (!queue.isEmpty()) {
            String current = queue.remove(queue.size() - 1);
            visited++;
            for (String next : effective.getOrDefault(current, List.of())) {
                int degree = indegree.merge(next, -1, Integer::sum);
                if (degree == 0) {
                    queue.add(next);
                }
            }
        }
        if (visited != ids.size()) {
            throw new BizException("工作流中存在环，LangGraph 引擎要求有向无环图");
        }
    }
}
