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
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
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
            Thread.currentThread().interrupt();
            throw new BizException("无法连接 AI 服务: " + ex.getMessage());
        }
    }

    public JsonNode postData(String path) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + path))
                .timeout(Duration.ofMillis(properties.getAi().getTimeoutMs()))
                .header("Accept", "application/json")
                .POST(HttpRequest.BodyPublishers.noBody())
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 300) {
                throw new BizException("AI 服务返回错误: HTTP " + response.statusCode());
            }
            return objectMapper.readTree(response.body());
        } catch (IOException | InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new BizException("无法连接 AI 服务: " + ex.getMessage());
        }
    }

    public JsonNode postJson(String path, Object body) {
        try {
            String json = objectMapper.writeValueAsString(body);
            HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + path))
                    .timeout(Duration.ofMillis(properties.getAi().getTimeoutMs()))
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 300) {
                throw new BizException("AI 服务返回错误: HTTP " + response.statusCode() + " " + response.body());
            }
            return objectMapper.readTree(response.body());
        } catch (IOException | InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new BizException("无法连接 AI 服务: " + ex.getMessage());
        }
    }

    public InputStream openExecution(String payload) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl() + "/v1/executions"))
                .timeout(Duration.ofMillis(properties.getAi().getTimeoutMs()))
                .header("Content-Type", "application/json")
                .header("Accept", "text/event-stream")
                .POST(HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8))
                .build();
        try {
            HttpResponse<InputStream> response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
            if (response.statusCode() >= 300) {
                String body = new String(response.body().readAllBytes(), StandardCharsets.UTF_8);
                throw new BizException("AI 服务拒绝执行: HTTP " + response.statusCode() + " " + body);
            }
            return response.body();
        } catch (IOException | InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new BizException("提交执行失败: " + ex.getMessage());
        }
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
            Thread.currentThread().interrupt();
            throw new BizException("读取文件失败: " + ex.getMessage());
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

    private String baseUrl() {
        String base = properties.getAi().getBaseUrl();
        return base.endsWith("/") ? base.substring(0, base.length() - 1) : base;
    }
}
