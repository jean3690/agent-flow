package com.agentflow.sdk;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class IntegrationClientTest {
    private final ObjectMapper json = new ObjectMapper();
    private final List<Call> calls = new ArrayList<>();
    private HttpServer server;
    private AgentFlowClient client;
    private String response = "{\"code\":0,\"data\":{\"id\":7,\"ok\":true,\"tools\":[]}}";
    private int status = 200;

    private record Call(String method, String path, JsonNode body, String apiKey, String bearer) {}

    @BeforeEach
    void setup() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/", this::handle);
        server.start();
        client = new AgentFlowClient("http://127.0.0.1:" + server.getAddress().getPort(), "af_platform");
    }

    private void handle(HttpExchange exchange) throws IOException {
        try (exchange) {
            byte[] request = exchange.getRequestBody().readAllBytes();
            calls.add(new Call(exchange.getRequestMethod(), exchange.getRequestURI().getRawPath(),
                    request.length == 0 ? null : json.readTree(request),
                    exchange.getRequestHeaders().getFirst("X-API-Key"),
                    exchange.getRequestHeaders().getFirst("Authorization")));
            byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            exchange.getResponseBody().write(bytes);
        }
    }

    @AfterEach
    void cleanup() {
        server.stop(0);
    }

    @Test
    void mcpLifecycleUsesCorrectRoutesAndNeverConfusesPlatformAndRemoteCredentials() throws Exception {
        client.listMcpServers();
        client.createMcpServer("中文服务", "https://tools.example/mcp", Map.of("Authorization", "Bearer REMOTE"));
        assertTrue(client.discoverMcpTools(7).path("ok").asBoolean());
        client.updateMcpServer(7, new McpServerSettings("中文服务", "https://tools.example/mcp", List.of("echo"), 1000, false));
        client.listMcpTools(7);
        client.deleteMcpServer(7);
        assertEquals(List.of("GET", "POST", "POST", "PUT", "GET", "DELETE"), calls.stream().map(Call::method).toList());
        assertEquals(List.of("/api/mcp-servers", "/api/mcp-servers", "/api/mcp-servers/7/discover", "/api/mcp-servers/7", "/api/mcp-servers/7/tools", "/api/mcp-servers/7"), calls.stream().map(Call::path).toList());
        for (Call call : calls) {
            assertEquals("af_platform", call.apiKey());
            assertNull(call.bearer());
        }
        assertTrue(calls.get(1).body().path("allowedTools").isEmpty());
        assertEquals("Bearer REMOTE", calls.get(1).body().path("headers").path("Authorization").asText());
        assertEquals("中文服务", calls.get(3).body().path("name").asText());
        assertFalse(calls.get(3).body().path("enabled").asBoolean());
        assertEquals(1000, calls.get(3).body().path("timeoutMs").asInt());
        assertFalse(calls.get(3).body().has("headers"));
    }

    @Test
    void explicitSecretClearingAndCustomCreationSettingsArePreserved() throws Exception {
        client.createMcpServer(new McpServerSettings("server", "https://tools.example/mcp", List.of(), 1000, false));
        client.updateMcpServer(7, new McpServerSettings("server", "https://tools.example/mcp", List.of(), 1000, false, null, true));
        assertFalse(calls.get(0).body().path("enabled").asBoolean());
        assertEquals(1000, calls.get(0).body().path("timeoutMs").asInt());
        assertTrue(calls.get(1).body().path("clearHeaders").asBoolean());
        assertFalse(calls.get(1).body().has("headers"));
        assertThrows(IllegalArgumentException.class, () -> client.createMcpServer(new McpServerSettings("server", "https://tools.example/mcp", List.of("echo"), 15000, true)));
        assertEquals(2, calls.size());
    }

    @Test
    void mcpSettingsSnapshotMutableCollections() {
        List<String> allowed = new ArrayList<>(List.of("echo"));
        Map<String, String> headers = new java.util.HashMap<>(Map.of("Authorization", "Bearer REMOTE"));
        McpServerSettings settings = new McpServerSettings("server", "https://tools.example/mcp", allowed, 15000, true, headers, false);
        allowed.clear();
        headers.clear();
        assertEquals(List.of("echo"), settings.allowedTools());
        assertEquals("Bearer REMOTE", settings.headers().get("Authorization"));
        assertFalse(settings.toString().contains("REMOTE"));
    }

    @Test
    void skillsSupportAllManagementMethodsAndUtf8Content() throws Exception {
        String content = "---\nname: report-helper\ndescription: 中文说明\n---\n内容\n";
        client.listSkills();
        client.getSkill("report-helper");
        client.saveSkill("report-helper", content);
        client.getSkillReference("report-helper", "guide.v1.md");
        client.reloadSkills();
        client.deleteSkill("report-helper");
        assertEquals(List.of("GET", "GET", "PUT", "GET", "POST", "DELETE"), calls.stream().map(Call::method).toList());
        assertEquals("/api/skills/report-helper/references/guide.v1.md", calls.get(3).path());
        assertEquals("/api/skills/reload", calls.get(4).path());
        assertEquals(content, calls.get(2).body().path("content").asText());
    }

    @ParameterizedTest
    @ValueSource(strings = {"../secret", "UPPER", "a/b", "", "x?token=y"})
    void invalidSkillNamesNeverReachNetwork(String name) {
        assertThrows(IllegalArgumentException.class, () -> client.getSkill(name));
        assertTrue(calls.isEmpty());
    }

    @Test
    void invalidReferencePathsAndMcpIdsNeverReachNetwork() {
        assertThrows(IllegalArgumentException.class, () -> client.getSkillReference("report-helper", "../guide.md"));
        assertThrows(IllegalArgumentException.class, () -> client.listMcpTools(0));
        assertThrows(IllegalArgumentException.class, () -> client.deleteMcpServer(-1));
        assertTrue(calls.isEmpty());
    }

    @Test
    void permissionErrorsRemainApiExceptionsAndFailedProbesAreInspectable() throws Exception {
        status = 403;
        response = "{\"code\":4030,\"message\":\"forbidden\"}";
        assertEquals(403, assertThrows(ApiException.class, () -> client.saveSkill("report-helper", "content")).getCode());
        status = 200;
        response = "{\"code\":0,\"data\":{\"ok\":false,\"tools\":[],\"message\":\"connection failed\"}}";
        assertFalse(client.discoverMcpTools(7).path("ok").asBoolean());
    }
}
