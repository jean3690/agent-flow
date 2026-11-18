package com.agentflow.sdk.example;

import com.agentflow.sdk.AgentFlowClient;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.util.Map;

/**
 * Minimal demonstration of calling Agent Flow as a service from Java.
 * Requires AGENTFLOW_BASE_URL and AGENTFLOW_API_KEY environment variables.
 */
public class Quickstart {

    public static void main(String[] args) throws Exception {
        String baseUrl = System.getenv().getOrDefault("AGENTFLOW_BASE_URL", "http://127.0.0.1:8084");
        String apiKey = System.getenv("AGENTFLOW_API_KEY");
        AgentFlowClient client = new AgentFlowClient(baseUrl, apiKey);
        ObjectMapper mapper = new ObjectMapper();

        ObjectNode flow = buildFlow(mapper);
        JsonNode created = client.createWorkflow("sdk-demo", flow, "quickstart", "langgraph", 1);
        long id = created.get("id").asLong();
        System.out.println("created workflow id=" + id);

        Map<String, Object> input = Map.of("topic", "LangGraph");
        JsonNode result = client.runWorkflow(id, input);
        System.out.println("run status: " + result.get("status").asText());
        System.out.println("outputs: " + result.get("outputs"));

        client.deleteWorkflow(id);
        System.out.println("deleted workflow");
    }

    private static ObjectNode buildFlow(ObjectMapper mapper) {
        ObjectNode flow = mapper.createObjectNode();
        ArrayNode nodes = mapper.createArrayNode();

        ObjectNode inConfig = mapper.createObjectNode();
        inConfig.set("variables", mapper.createArrayNode().add("topic"));
        nodes.add(node(mapper, "in", "input", "input", inConfig));

        ObjectNode llmConfig = mapper.createObjectNode();
        llmConfig.put("provider", "mock");
        llmConfig.put("model", "agentflow-mock");
        llmConfig.put("prompt", "introduce {{input.topic}}");
        nodes.add(node(mapper, "llm", "llm", "llm", llmConfig));

        nodes.add(node(mapper, "out", "output", "output", mapper.createObjectNode()));
        flow.set("nodes", nodes);

        ArrayNode edges = mapper.createArrayNode();
        edges.add(edge(mapper, "e1", "in", "llm"));
        edges.add(edge(mapper, "e2", "llm", "out"));
        flow.set("edges", edges);
        return flow;
    }

    private static ObjectNode node(ObjectMapper mapper, String id, String type, String name, ObjectNode config) {
        ObjectNode n = mapper.createObjectNode();
        n.put("id", id);
        n.put("type", type);
        n.put("name", name);
        n.put("position", mapper.createObjectNode().put("x", 0).put("y", 0));
        n.set("config", config);
        return n;
    }

    private static ObjectNode edge(ObjectMapper mapper, String id, String source, String target) {
        ObjectNode e = mapper.createObjectNode();
        e.put("id", id);
        e.put("source", source);
        e.put("target", target);
        return e;
    }
}
