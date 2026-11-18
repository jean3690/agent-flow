package com.agentflow.util;

import com.agentflow.common.BizException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class FlowValidatorTest {

    private final ObjectMapper mapper = new ObjectMapper();

    private JsonNode flow(String json) throws Exception {
        return mapper.readTree(json);
    }

    @Test
    void acceptsLinearFlow() throws Exception {
        JsonNode flow = flow("""
                {
                  "nodes": [
                    {"id": "a", "type": "input"},
                    {"id": "b", "type": "template"},
                    {"id": "c", "type": "output"}
                  ],
                  "edges": [
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "c"}
                  ]
                }
                """);
        FlowValidator.validate(flow);
        assertThat(FlowValidator.countNodes(flow)).isEqualTo(3);
    }

    @Test
    void acceptsConditionWithExplicitBranches() throws Exception {
        JsonNode flow = flow("""
                {
                  "nodes": [
                    {"id": "a", "type": "input"},
                    {"id": "gate", "type": "condition", "config": {"trueBranch": "yes", "falseBranch": "no"}},
                    {"id": "yes", "type": "template"},
                    {"id": "no", "type": "template"}
                  ],
                  "edges": [{"source": "a", "target": "gate"}]
                }
                """);
        FlowValidator.validate(flow);
    }

    @Test
    void acceptsRouterWithConfiguredTargets() throws Exception {
        ObjectNode flow = mapper.createObjectNode();
        ArrayNode nodes = flow.putArray("nodes");
        nodes.addObject().put("id", "a").put("type", "input");
        ObjectNode router = nodes.addObject().put("id", "router").put("type", "llm_router");
        ObjectNode config = router.putObject("config");
        config.put("routes", mapper.writeValueAsString(List.of(
                Map.of("name", "技术", "target", "tech"),
                Map.of("name", "生活", "target", "life"))));
        config.put("fallbackTarget", "life");
        nodes.addObject().put("id", "tech").put("type", "template");
        nodes.addObject().put("id", "life").put("type", "template");
        flow.putArray("edges").addObject().put("source", "a").put("target", "router");

        FlowValidator.validate(flow);
    }

    @Test
    void rejectsRouterWithUnknownTarget() throws Exception {
        ObjectNode flow = mapper.createObjectNode();
        ArrayNode nodes = flow.putArray("nodes");
        nodes.addObject().put("id", "a").put("type", "input");
        ObjectNode router = nodes.addObject().put("id", "router").put("type", "llm_router");
        router.putObject("config").put("routes", mapper.writeValueAsString(List.of(
                Map.of("name", "技术", "target", "ghost"))));
        flow.putArray("edges").addObject().put("source", "a").put("target", "router");

        assertThatThrownBy(() -> FlowValidator.validate(flow))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("路由分支指向不存在的节点");
    }

    @Test
    void rejectsCycle() throws Exception {
        JsonNode flow = flow("""
                {
                  "nodes": [
                    {"id": "a", "type": "template"},
                    {"id": "b", "type": "template"}
                  ],
                  "edges": [
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "a"}
                  ]
                }
                """);
        assertThatThrownBy(() -> FlowValidator.validate(flow))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("环");
    }

    @Test
    void rejectsMultipleEntries() throws Exception {
        JsonNode flow = flow("""
                {
                  "nodes": [
                    {"id": "a", "type": "template"},
                    {"id": "b", "type": "template"}
                  ],
                  "edges": []
                }
                """);
        assertThatThrownBy(() -> FlowValidator.validate(flow))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("多个入口");
    }

    @Test
    void rejectsDanglingEdge() throws Exception {
        JsonNode flow = flow("""
                {
                  "nodes": [{"id": "a", "type": "input"}],
                  "edges": [{"source": "a", "target": "missing"}]
                }
                """);
        assertThatThrownBy(() -> FlowValidator.validate(flow))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("不存在");
    }

    @Test
    void rejectsEmptyFlow() throws Exception {
        assertThatThrownBy(() -> FlowValidator.validate(flow("{\"nodes\": [], \"edges\": []}")))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("至少需要一个节点");
    }

    @Test
    void structureAcceptsEmptyFlow() throws Exception {
        // 新建/保存工作流允许空白画布，只有执行时才要求图非空且存在入口节点。
        FlowValidator.validateStructure(flow("{\"nodes\": [], \"edges\": []}"));
    }

    @Test
    void structureAcceptsUnconfiguredRouter() throws Exception {
        ObjectNode flow = mapper.createObjectNode();
        ArrayNode nodes = flow.putArray("nodes");
        nodes.addObject().put("id", "a").put("type", "input");
        nodes.addObject().put("id", "router").put("type", "llm_router");
        flow.putArray("edges");

        FlowValidator.validateStructure(flow);
    }

    @Test
    void structureAcceptsMultipleUnconnectedNodes() throws Exception {
        // 编排进行中可能出现多个未连接节点，保存时不应被入口节点规则拦截。
        JsonNode flow = flow("""
                {
                  "nodes": [
                    {"id": "a", "type": "input"},
                    {"id": "b", "type": "template"}
                  ],
                  "edges": []
                }
                """);
        FlowValidator.validateStructure(flow);
    }
}
