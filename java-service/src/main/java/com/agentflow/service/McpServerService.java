package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.McpServerRequest;
import com.agentflow.entity.McpServer;
import com.agentflow.mapper.McpServerMapper;
import com.agentflow.security.CurrentUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.net.URI;
import java.util.*;
import java.util.regex.Pattern;

@Service
@RequiredArgsConstructor
public class McpServerService {
    private static final Pattern HEADER = Pattern.compile("^[A-Za-z0-9!#$%&'*+.^_`|~-]+$");
    private final McpServerMapper mapper;
    private final CryptoService crypto;
    private final ObjectMapper json;
    private final AiClient ai;

    public List<Map<String, Object>> list(CurrentUser user) {
        return mapper.selectList(new LambdaQueryWrapper<McpServer>()
                .eq(!admin(user), McpServer::getUserId, user.id()).orderByDesc(McpServer::getId))
                .stream().map(this::view).toList();
    }

    @Transactional
    public Map<String, Object> save(Long id, McpServerRequest request, CurrentUser user) {
        validate(request);
        McpServer server = id == null ? new McpServer() : require(id, user);
        Set<String> available = new HashSet<>();
        read(server.getTools(), "[]").forEach(tool -> available.add(tool.path("name").asText()));
        if (!available.containsAll(request.getAllowedTools())) {
            throw new BizException("请先测试连接，再从已发现的工具中选择授权项");
        }
        if (id == null) {
            server.setUserId(user.id());
            server.setTools("[]");
        }
        server.setName(request.getName().trim());
        String oldUrl = server.getUrl();
        server.setUrl(request.getUrl().trim());
        // A changed destination must not silently receive the old host's secret.
        if (oldUrl != null && !oldUrl.equals(server.getUrl())) {
            server.setHeadersCipher(null);
            server.setTools("[]");
            if (!request.getAllowedTools().isEmpty()) throw new BizException("地址变更后需重新发现并授权工具");
        }
        if (request.isClearHeaders()) server.setHeadersCipher(null);
        if (request.getHeaders() != null && !request.getHeaders().isEmpty()) {
            server.setHeadersCipher(crypto.encrypt(write(request.getHeaders())));
        }
        server.setAllowedTools(write(new LinkedHashSet<>(request.getAllowedTools())));
        server.setTimeoutMs(request.getTimeoutMs());
        server.setEnabled(request.isEnabled() ? 1 : 0);
        if (id == null) mapper.insert(server); else mapper.updateById(server);
        return view(server);
    }

    public void delete(Long id, CurrentUser user) {
        mapper.deleteById(require(id, user).getId());
    }

    public JsonNode discover(Long id, CurrentUser user) {
        McpServer server = require(id, user);
        JsonNode result = ai.postJson("/v1/mcp/discover", credentials(server)).path("data");
        if (result.path("ok").asBoolean(false)) {
            JsonNode tools = result.path("tools");
            if (!tools.isArray() || tools.size() > 100 || tools.toString().length() > 200000) {
                throw new BizException("MCP 工具声明无效或过大");
            }
            LambdaUpdateWrapper<McpServer> update = new LambdaUpdateWrapper<McpServer>()
                    .eq(McpServer::getId, id).eq(McpServer::getUrl, server.getUrl())
                    .set(McpServer::getTools, tools.toString());
            if (server.getHeadersCipher() == null) update.isNull(McpServer::getHeadersCipher);
            else update.eq(McpServer::getHeadersCipher, server.getHeadersCipher());
            if (mapper.update(null, update) == 0) throw new BizException("配置已变更，请重新测试连接");
        }
        return result;
    }

    public List<JsonNode> tools(Long id, CurrentUser user) {
        McpServer server = require(id, user);
        Set<String> allowed = new HashSet<>();
        read(server.getAllowedTools(), "[]").forEach(item -> allowed.add(item.asText()));
        List<JsonNode> tools = new ArrayList<>();
        read(server.getTools(), "[]").forEach(item -> { if (allowed.contains(item.path("name").asText())) tools.add(item); });
        return tools;
    }

    /** Only referenced, enabled and accessible servers enter execution payloads. */
    public Map<String, Object> forRun(Collection<JsonNode> flows, CurrentUser user) {
        Set<Long> ids = new LinkedHashSet<>();
        for (JsonNode flow : flows) {
            for (JsonNode node : flow.path("nodes")) {
                JsonNode config = node.path("config");
                if ("mcp_tool".equals(node.path("type").asText())) {
                    ids.add(serverId(config.path("serverId")));
                } else if ("react_agent".equals(node.path("type").asText())) {
                    JsonNode selected = config.path("mcpServerIds");
                    if (!selected.isMissingNode() && !selected.isArray()) throw new BizException("mcpServerIds 必须是数组");
                    selected.forEach(value -> ids.add(serverId(value)));
                }
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        for (Long id : ids) {
            McpServer server = require(id, user);
            if (!Integer.valueOf(1).equals(server.getEnabled())) throw new BizException("MCP 服务已禁用");
            result.put(String.valueOf(id), credentials(server));
        }
        for (JsonNode flow : flows) {
            for (JsonNode node : flow.path("nodes")) {
                if (!"mcp_tool".equals(node.path("type").asText())) continue;
                JsonNode config = node.path("config");
                JsonNode entry = json.valueToTree(result.get(String.valueOf(serverId(config.path("serverId")))));
                boolean allowed = false;
                for (JsonNode item : entry.path("allowedTools")) {
                    if (item.asText().equals(config.path("toolName").asText())) allowed = true;
                }
                if (!allowed) throw new BizException("MCP 工具未授权");
            }
        }
        return result;
    }

    private McpServer require(Long id, CurrentUser user) {
        McpServer server = mapper.selectById(id);
        if (server == null || (!admin(user) && !Objects.equals(server.getUserId(), user.id()))) {
            throw BizException.notFound("MCP 服务不存在");
        }
        return server;
    }

    private Map<String, Object> credentials(McpServer server) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("url", server.getUrl());
        String cipher = server.getHeadersCipher();
        value.put("headers", read(cipher == null ? null : crypto.decrypt(cipher), "{}"));
        value.put("allowedTools", read(server.getAllowedTools(), "[]"));
        value.put("timeoutMs", server.getTimeoutMs());
        return value;
    }

    private Map<String, Object> view(McpServer server) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("id", server.getId()); value.put("name", server.getName()); value.put("url", server.getUrl());
        value.put("enabled", Integer.valueOf(1).equals(server.getEnabled())); value.put("timeoutMs", server.getTimeoutMs());
        value.put("hasCredentials", server.getHeadersCipher() != null && !server.getHeadersCipher().isBlank());
        value.put("allowedTools", read(server.getAllowedTools(), "[]")); value.put("tools", read(server.getTools(), "[]"));
        return value;
    }

    private void validate(McpServerRequest request) {
        try {
            URI uri = URI.create(request.getUrl().trim());
            if (!Set.of("http", "https").contains(uri.getScheme()) || uri.getHost() == null || uri.getRawUserInfo() != null
                    || uri.getRawQuery() != null || uri.getRawFragment() != null) throw new IllegalArgumentException();
        } catch (IllegalArgumentException ex) { throw new BizException("MCP 只支持不含账号密码、查询参数的 HTTP(S) 地址"); }
        Map<String, String> headers = request.getHeaders();
        if (headers != null) {
            if (write(headers).length() > 20000) throw new BizException("请求头过大");
            for (var item : headers.entrySet()) {
                String key = item.getKey(), value = item.getValue();
                if (!HEADER.matcher(key).matches() || Set.of("host", "connection", "content-length", "transfer-encoding").contains(key.toLowerCase(Locale.ROOT))
                        || value == null || value.contains("\r") || value.contains("\n") || value.length() > 8192) throw new BizException("请求头无效");
            }
        }
        if (request.getAllowedTools().stream().anyMatch(item -> item == null || item.isBlank() || item.length() > 128)) {
            throw new BizException("工具名称无效");
        }
    }

    private Long serverId(JsonNode value) {
        try { long id = Long.parseLong(value.asText()); if (id > 0) return id; }
        catch (NumberFormatException ignored) { }
        throw new BizException("请配置有效的 MCP 服务 ID");
    }
    private boolean admin(CurrentUser user) { return "ADMIN".equals(user.role()); }
    private JsonNode read(String text, String fallback) {
        try { return json.readTree(text == null || text.isBlank() ? fallback : text); }
        catch (Exception ex) { throw new BizException("MCP 配置数据损坏"); }
    }
    private String write(Object value) {
        try { return json.writeValueAsString(value); }
        catch (Exception ex) { throw new BizException("MCP 配置无法序列化"); }
    }
}
