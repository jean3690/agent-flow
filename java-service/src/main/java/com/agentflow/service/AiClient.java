package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.config.AgentFlowProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.WebSocket;
import java.util.concurrent.CompletableFuture;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

@Slf4j
@Component
@RequiredArgsConstructor
public class AiClient {

    private final AgentFlowProperties properties;
    private final ObjectMapper objectMapper;
    private HttpClient httpClient;

    @PostConstruct
    void init() {
        httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(properties.getAi().getConnectTimeoutMs()))
                .version(HttpClient.Version.HTTP_1_1)
                .build();
    }

    public JsonNode data(String path) {
        JsonNode body = get(path);
        return body.path("data");
    }

    public List<JsonNode> dataList(String path) {
        JsonNode body = get(path);
        List<JsonNode> items = new ArrayList<>();
        body.path("data").forEach(items::add);
        return items;
    }

    public JsonNode get(String path) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + path))
                .timeout(Duration.ofMillis(properties.getAi().getConnectTimeoutMs()))
                .header("Accept", "application/json")
                .GET()
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 300) {
                throw new BizException("AI 服务返回错误: HTTP " + response.statusCode() + " " + response.body());
            }
            return objectMapper.readTree(response.body());
        } catch (IOException | InterruptedException ex) {
            throw wrap("无法连接 AI 服务", ex);
        }
    }

    public JsonNode postData(String path) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + path))
                .timeout(Duration.ofMillis(properties.getAi().getTimeoutMs()))
                .header("Accept", "application/json")
                .header("X-Internal-Token", properties.getInternal().getToken())
                .POST(HttpRequest.BodyPublishers.noBody())
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 300) {
                throw new BizException("AI 服务返回错误: HTTP " + response.statusCode());
            }
            return objectMapper.readTree(response.body());
        } catch (IOException | InterruptedException ex) {
            throw wrap("无法连接 AI 服务", ex);
        }
    }

    public JsonNode postJson(String path, Object body) {
        try {
            String json = objectMapper.writeValueAsString(body);
            HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + path))
                    .timeout(Duration.ofMillis(properties.getAi().getTimeoutMs()))
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .header("X-Internal-Token", properties.getInternal().getToken())
                    .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 300) {
                throw new BizException("AI 服务返回错误: HTTP " + response.statusCode() + " " + response.body());
            }
            return objectMapper.readTree(response.body());
        } catch (IOException | InterruptedException ex) {
            throw wrap("无法连接 AI 服务", ex);
        }
    }

    public InputStream openExecution(String payload) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + "/v1/executions"))
                .timeout(Duration.ofMillis(properties.getAi().getTimeoutMs()))
                .header("Content-Type", "application/json")
                .header("X-Internal-Token", properties.getInternal().getToken())
                .header("Accept", "text/event-stream")
                .POST(HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8))
                .build();
        try {
            HttpResponse<InputStream> response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
            if (response.statusCode() >= 300) {
                try (InputStream errorStream = response.body()) {
                    String body = new String(errorStream.readAllBytes(), StandardCharsets.UTF_8);
                    throw new BizException("AI 服务拒绝执行: HTTP " + response.statusCode() + " " + body);
                }
            }
            return response.body();
        } catch (IOException | InterruptedException ex) {
            throw wrap("提交执行失败", ex);
        }
    }

    /** Live media goes to Python; vendor credentials never pass through the browser. */
    public CompletableFuture<WebSocket> openRealtime(WebSocket.Listener listener) {
        String url = baseUrl().replaceFirst("^http", "ws") + "/v1/translations/realtime/ws";
        return httpClient.newWebSocketBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .header("X-Internal-Token", properties.getInternal().getToken())
                .buildAsync(URI.create(url), listener);
    }

    public byte[] download(String path) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + path))
                .timeout(Duration.ofMillis(properties.getAi().getTimeoutMs()))
                .GET()
                .build();
        try {
            HttpResponse<byte[]> response = httpClient.send(request, HttpResponse.BodyHandlers.ofByteArray());
            if (response.statusCode() >= 300) {
                throw BizException.notFound("文件不存在: " + path);
            }
            return response.body();
        } catch (IOException | InterruptedException ex) {
            throw wrap("读取文件失败", ex);
        }
    }

    /** Upload raw bytes to ai-service; returns the file metadata node. */
    public JsonNode uploadFile(String name, byte[] content, String contentType) {
        String query = (name == null || name.isBlank())
                ? ""
                : "?name=" + URLEncoder.encode(name, StandardCharsets.UTF_8);
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + "/v1/files" + query))
                .timeout(Duration.ofMillis(properties.getAi().getTimeoutMs()))
                .header("Content-Type", contentType == null || contentType.isBlank()
                        ? "application/octet-stream" : contentType)
                .header("Accept", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(content))
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 300) {
                throw new BizException("上传文件失败: HTTP " + response.statusCode() + " " + response.body());
            }
            return objectMapper.readTree(response.body()).path("data");
        } catch (IOException | InterruptedException ex) {
            throw wrap("上传文件失败", ex);
        }
    }

    /** DELETE a stored file; returns the metadata of the removed file. */
    public JsonNode delete(String path) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + path))
                .timeout(Duration.ofMillis(properties.getAi().getTimeoutMs()))
                .header("Accept", "application/json")
                .header("X-Internal-Token", properties.getInternal().getToken())
                .DELETE()
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 300) {
                throw BizException.notFound("文件不存在: " + path);
            }
            return objectMapper.readTree(response.body()).path("data");
        } catch (IOException | InterruptedException ex) {
            throw wrap("删除文件失败", ex);
        }
    }

    public boolean healthy() {
        try {
            return "UP".equalsIgnoreCase(get("/health").path("status").asText());
        } catch (Exception ex) {
            log.warn("ai service health check failed: {}", ex.getMessage());
            return false;
        }
    }

    public JsonNode putJson(String path, Object body) {
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + path))
                    .timeout(Duration.ofMillis(properties.getAi().getTimeoutMs()))
                    .header("Content-Type", "application/json")
                    .header("X-Internal-Token", properties.getInternal().getToken())
                    .PUT(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 300) {
                JsonNode error = objectMapper.readTree(response.body());
                throw new BizException(error.path("detail").isTextual() ? error.path("detail").asText() : "AI 服务拒绝保存: HTTP " + response.statusCode());
            }
            return objectMapper.readTree(response.body()).path("data");
        } catch (IOException | InterruptedException ex) { throw wrap("保存失败", ex); }
    }

    /**
     * 统一包装 IO 异常：只有真正的 {@link InterruptedException} 才需要恢复中断标记，
     * 普通网络异常不应污染线程池线程的中断状态。
     */
    private BizException wrap(String action, Exception ex) {
        if (ex instanceof InterruptedException) {
            Thread.currentThread().interrupt();
        }
        return new BizException(action + ": " + ex.getMessage());
    }

    private String baseUrl() {
        String base = properties.getAi().getBaseUrl();
        return base.endsWith("/") ? base.substring(0, base.length() - 1) : base;
    }
}
