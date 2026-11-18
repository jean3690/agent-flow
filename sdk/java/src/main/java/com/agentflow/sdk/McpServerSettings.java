package com.agentflow.sdk;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** Full configuration update. Null headers preserve credentials; clearHeaders removes them. */
public record McpServerSettings(
        String name, String url, List<String> allowedTools, int timeoutMs, boolean enabled,
        Map<String, String> headers, boolean clearHeaders) {

    public McpServerSettings {
        Objects.requireNonNull(name, "name");
        Objects.requireNonNull(url, "url");
        allowedTools = List.copyOf(allowedTools);
        if (headers != null) headers = Map.copyOf(headers);
    }

    public McpServerSettings(String name, String url, List<String> allowedTools, int timeoutMs, boolean enabled) {
        this(name, url, allowedTools, timeoutMs, enabled, null, false);
    }

    Map<String, Object> requestBody() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("name", name);
        body.put("url", url);
        body.put("allowedTools", allowedTools);
        body.put("timeoutMs", timeoutMs);
        body.put("enabled", enabled);
        body.put("clearHeaders", clearHeaders);
        if (headers != null) body.put("headers", headers);
        return body;
    }

    @Override
    public String toString() {
        return "McpServerSettings[name=" + name + ", allowedTools=" + allowedTools
                + ", timeoutMs=" + timeoutMs + ", enabled=" + enabled
                + ", headersConfigured=" + (headers != null) + ", clearHeaders=" + clearHeaders + "]";
    }
}
