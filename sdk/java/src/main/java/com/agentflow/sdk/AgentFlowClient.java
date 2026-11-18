package com.agentflow.sdk;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.function.Consumer;

/**
 * Java client for the Agent Flow service.
 *
 * Authenticate with an API Key (X-API-Key) for machine-to-machine calls, or a JWT bearer token.
 * All JSON responses follow { code: 0, message, data } and are unwrapped to the data node.
 */
public class AgentFlowClient {

    private final String baseUrl;
    private final String apiKey;
    private final String token;
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final HttpClient httpClient = HttpClient.newHttpClient();

    public AgentFlowClient(String baseUrl, String apiKey, String token) {
        this.baseUrl = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        this.apiKey = apiKey;
        this.token = token;
    }

    public AgentFlowClient(String baseUrl, String apiKey) {
        this(baseUrl, apiKey, null);
    }

    public record Event(String name, JsonNode data) {
    }

    private HttpRequest.Builder authHeaders(HttpRequest.Builder builder) {
        if (apiKey != null) {
            builder.header("X-API-Key", apiKey);
        } else if (token != null) {
            builder.header("Authorization", "Bearer " + token);
        }
        return builder;
    }

    private JsonNode handle(String body) throws ApiException {
        try {
            JsonNode root = objectMapper.readTree(body);
            int code = root.path("code").asInt(0);
            if (code != 0) {
                throw new ApiException(code, root.path("message").asText("error"));
            }
            return root.get("data");
        } catch (java.io.IOException e) {
            throw new ApiException(0, "invalid json: " + e.getMessage());
        }
    }

    /** Generic request. jsonBody may be null for requests without a body. */
    public JsonNode request(String method, String path, Map<String, Object> jsonBody) throws ApiException {
        try {
            HttpRequest.Builder builder = authHeaders(HttpRequest.newBuilder().uri(URI.create(baseUrl + path)));
            builder.header("Accept", "application/json");
            HttpRequest.BodyPublisher body = HttpRequest.BodyPublishers.noBody();
            if (jsonBody != null) {
                builder.header("Content-Type", "application/json");
                body = HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(jsonBody));
            }
            builder.method(method, body);
            HttpResponse<String> resp = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400) {
                throw new ApiException(resp.statusCode(), resp.body());
            }
            return handle(resp.body());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiException(0, e.getMessage());
        } catch (java.io.IOException e) {
            throw new ApiException(0, e.getMessage());
        }
    }

    // ---- workflows ----
    public JsonNode listWorkflows(int page, int size, String keyword) throws ApiException {
        String path = "/api/workflows?page=" + page + "&size=" + size
                + (keyword != null ? "&keyword=" + URLEncoder.encode(keyword, StandardCharsets.UTF_8) : "");
        return request("GET", path, null);
    }

    public JsonNode getWorkflow(long id) throws ApiException {
        return request("GET", "/api/workflows/" + id, null);
    }

    public JsonNode createWorkflow(String name, JsonNode flow, String description,
                                   String engineType, Integer status) throws ApiException {
        Map<String, Object> body = new java.util.HashMap<>();
        body.put("name", name);
        body.put("description", description == null ? "" : description);
        body.put("engineType", engineType == null ? "langgraph" : engineType);
        body.put("status", status == null ? 1 : status);
        body.put("flow", flow);
        return request("POST", "/api/workflows", body);
    }

    public JsonNode deleteWorkflow(long id) throws ApiException {
        return request("DELETE", "/api/workflows/" + id, null);
    }

    /** Synchronous execution: returns the aggregated run result. */
    public JsonNode runWorkflow(long id, Map<String, Object> input) throws ApiException {
        Map<String, Object> body = new java.util.HashMap<>();
        body.put("input", input == null ? Map.of() : input);
        return request("POST", "/api/workflows/" + id + "/run", body);
    }

    /** Streaming execution: each SSE event is delivered to onEvent as it arrives. */
    public void executeWorkflowStream(long id, Map<String, Object> input, Consumer<Event> onEvent)
            throws ApiException {
        try {
            Map<String, Object> body = new java.util.HashMap<>();
            body.put("input", input == null ? Map.of() : input);
            HttpRequest.Builder builder = authHeaders(
                    HttpRequest.newBuilder().uri(URI.create(baseUrl + "/api/workflows/" + id + "/execute")));
            builder.header("Content-Type", "application/json");
            builder.header("Accept", "text/event-stream");
            builder.POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)));
            HttpResponse<InputStream> resp =
                    httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofInputStream());
            try (InputStream bodyStream = resp.body()) {
                if (resp.statusCode() >= 400) {
                    throw new ApiException(resp.statusCode(), new String(bodyStream.readAllBytes(), StandardCharsets.UTF_8));
                }
                BufferedReader reader = new BufferedReader(new InputStreamReader(bodyStream, StandardCharsets.UTF_8));
                String event = null;
                java.util.List<String> data = new java.util.ArrayList<>();
                boolean firstLine = true;
                String line;
                while ((line = reader.readLine()) != null) {
                    if (firstLine) {
                        if (line.startsWith("\ufeff")) line = line.substring(1);
                        firstLine = false;
                    }
                    if (line.isEmpty()) {
                        emitEvent(event, data, onEvent);
                        event = null;
                        data.clear();
                    } else if (!line.startsWith(":")) {
                        int colon = line.indexOf(':');
                        String field = colon < 0 ? line : line.substring(0, colon);
                        String value = colon < 0 ? "" : line.substring(colon + 1);
                        if (value.startsWith(" ")) value = value.substring(1);
                        if ("event".equals(field)) event = value;
                        if ("data".equals(field)) data.add(value);
                    }
                }
                emitEvent(event, data, onEvent);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiException(0, e.getMessage());
        } catch (java.io.IOException e) {
            throw new ApiException(0, e.getMessage());
        }
    }

    private void emitEvent(String name, java.util.List<String> data, Consumer<Event> onEvent)
            throws java.io.IOException {
        if (name == null && data.isEmpty()) return;
        String json = String.join("\n", data);
        JsonNode payload = json.isEmpty() ? null : objectMapper.readTree(json);
        onEvent.accept(new Event(name == null || name.isEmpty() ? "message" : name, payload));
    }

    // ---- knowledge bases ----
    public JsonNode listKnowledgeBases() throws ApiException {
        return request("GET", "/api/knowledge-bases", null);
    }

    public JsonNode createKnowledgeBase(String name, String description,
                                        String embeddingProvider, String embeddingModel,
                                        Integer chunkSize, Integer chunkOverlap) throws ApiException {
        Map<String, Object> body = new java.util.HashMap<>();
        body.put("name", name);
        body.put("description", description == null ? "" : description);
        body.put("embeddingProvider", embeddingProvider == null ? "mock" : embeddingProvider);
        body.put("embeddingModel", embeddingModel == null ? "text-embedding-3-small" : embeddingModel);
        body.put("chunkSize", chunkSize == null ? 600 : chunkSize);
        body.put("chunkOverlap", chunkOverlap == null ? 80 : chunkOverlap);
        return request("POST", "/api/knowledge-bases", body);
    }

    public JsonNode deleteKnowledgeBase(long id) throws ApiException {
        return request("DELETE", "/api/knowledge-bases/" + id, null);
    }

    public JsonNode searchKnowledgeBase(long id, String query, int topK) throws ApiException {
        Map<String, Object> body = new java.util.HashMap<>();
        body.put("query", query);
        body.put("topK", topK);
        return request("POST", "/api/knowledge-bases/" + id + "/search", body);
    }

    // ---- skills ----
    public JsonNode listSkills() throws ApiException {
        return request("GET", "/api/skills", null);
    }

    public JsonNode getSkill(String name) throws ApiException {
        return request("GET", skillPath(name), null);
    }

    /** Create/update a custom SKILL.md; the authenticated owner must be an administrator. */
    public JsonNode saveSkill(String name, String content) throws ApiException {
        return request("PUT", skillPath(name), Map.of("content", content));
    }

    public JsonNode deleteSkill(String name) throws ApiException {
        return request("DELETE", skillPath(name), null);
    }

    public JsonNode getSkillReference(String name, String file) throws ApiException {
        if (file == null || !file.matches("[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}\\.md")) {
            throw new IllegalArgumentException("invalid Markdown reference filename");
        }
        return request("GET", skillPath(name) + "/references/" + encodePath(file), null);
    }

    public JsonNode reloadSkills() throws ApiException {
        return request("POST", "/api/skills/reload", null);
    }

    // ---- MCP configurations (platform REST API, not direct MCP transport) ----
    public JsonNode listMcpServers() throws ApiException {
        return request("GET", "/api/mcp-servers", null);
    }

    /** New configurations deliberately have no authorized tools. */
    public JsonNode createMcpServer(String name, String url, Map<String, String> headers) throws ApiException {
        return createMcpServer(new McpServerSettings(name, url, java.util.List.of(), 15000, true, headers, false));
    }

    public JsonNode createMcpServer(String name, String url) throws ApiException {
        return createMcpServer(name, url, null);
    }

    public JsonNode createMcpServer(McpServerSettings settings) throws ApiException {
        if (!settings.allowedTools().isEmpty()) {
            throw new IllegalArgumentException("discover tools before granting permissions on a new server");
        }
        return request("POST", "/api/mcp-servers", settings.requestBody());
    }

    public JsonNode updateMcpServer(long id, McpServerSettings settings) throws ApiException {
        return request("PUT", mcpPath(id), settings.requestBody());
    }

    /** Check the returned ok field; an unsuccessful probe is not necessarily an HTTP error. */
    public JsonNode discoverMcpTools(long id) throws ApiException {
        return request("POST", mcpPath(id) + "/discover", null);
    }

    public JsonNode listMcpTools(long id) throws ApiException {
        return request("GET", mcpPath(id) + "/tools", null);
    }

    public JsonNode deleteMcpServer(long id) throws ApiException {
        return request("DELETE", mcpPath(id), null);
    }

    private String skillPath(String name) {
        if (name == null || !name.matches("[a-z][a-z0-9_-]{0,63}")) {
            throw new IllegalArgumentException("invalid skill identifier");
        }
        return "/api/skills/" + encodePath(name);
    }

    private String mcpPath(long id) {
        if (id <= 0) throw new IllegalArgumentException("server id must be positive");
        return "/api/mcp-servers/" + id;
    }

    private String encodePath(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20");
    }
}
