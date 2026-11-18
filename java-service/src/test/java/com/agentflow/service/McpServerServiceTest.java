package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.config.AgentFlowProperties;
import com.agentflow.dto.McpServerRequest;
import com.agentflow.entity.McpServer;
import com.agentflow.mapper.McpServerMapper;
import com.agentflow.security.CurrentUser;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class McpServerServiceTest {
    @Mock McpServerMapper mapper;
    @Mock AiClient ai;
    private final ObjectMapper json = new ObjectMapper();
    private final CryptoService crypto = new CryptoService(new AgentFlowProperties());
    private McpServerService service;
    private final CurrentUser owner = new CurrentUser(1L, "owner", "USER");
    private final CurrentUser other = new CurrentUser(2L, "other", "USER");

    @BeforeEach void setup() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), "test"), McpServer.class);
        service = new McpServerService(mapper, crypto, json, ai);
    }
    private McpServer server() {
        McpServer item = new McpServer(); item.setId(4L); item.setUserId(1L); item.setName("test");
        item.setUrl("https://example.com/mcp"); item.setAllowedTools("[\"echo\"]");
        item.setTools("[{\"name\":\"echo\",\"inputSchema\":{}}]"); item.setEnabled(1); item.setTimeoutMs(15000);
        return item;
    }
    private McpServerRequest request() {
        McpServerRequest request = new McpServerRequest(); request.setName("test"); request.setUrl("https://example.com/mcp"); return request;
    }

    @Test void storesEncryptedHeadersAndNeverReturnsPlaintext() {
        McpServerRequest request = request(); request.setHeaders(Map.of("Authorization", "Bearer SECRET"));
        doAnswer(call -> { McpServer saved = call.getArgument(0); saved.setId(4L); assertThat(saved.getHeadersCipher()).startsWith("enc:v1:").doesNotContain("SECRET"); return 1; }).when(mapper).insert(any(McpServer.class));
        Map<String,Object> result = service.save(null, request, owner);
        assertThat(result).containsEntry("hasCredentials", true).doesNotContainKeys("headers", "headersCipher");
        assertThat(json.valueToTree(result).toString()).doesNotContain("SECRET");
    }
    @ParameterizedTest @ValueSource(strings={"tools", "discover", "delete", "run"})
    void hidesAnotherUsersConfig(String action) throws Exception {
        when(mapper.selectById(4L)).thenReturn(server());
        assertThatThrownBy(() -> {
            switch(action) {
                case "tools" -> service.tools(4L, other);
                case "discover" -> service.discover(4L, other);
                case "delete" -> service.delete(4L, other);
                default -> service.forRun(List.of(json.readTree("{\"nodes\":[{\"type\":\"mcp_tool\",\"config\":{\"serverId\":4,\"toolName\":\"echo\"}}]}")), other);
            }
        }).isInstanceOfSatisfying(BizException.class, ex -> assertThat(ex.getStatus()).isEqualTo(HttpStatus.NOT_FOUND));
        verifyNoInteractions(ai);
    }
    @Test void payloadIncludesOnlyReferencedCredentials() throws Exception {
        McpServer server = server(); server.setHeadersCipher(crypto.encrypt("{\"Authorization\":\"Bearer SECRET\"}"));
        when(mapper.selectById(4L)).thenReturn(server);
        var result = service.forRun(List.of(json.readTree("{\"nodes\":[{\"type\":\"mcp_tool\",\"config\":{\"serverId\":4,\"toolName\":\"echo\"}}]}")), owner);
        assertThat(result).containsOnlyKeys("4");
        assertThat(json.valueToTree(result).path("4").path("headers").path("Authorization").asText()).isEqualTo("Bearer SECRET");
    }
    @Test void disabledServersAndUnapprovedToolsCannotExecute() throws Exception {
        McpServer server = server(); when(mapper.selectById(4L)).thenReturn(server);
        var flow = json.readTree("{\"nodes\":[{\"type\":\"mcp_tool\",\"config\":{\"serverId\":4,\"toolName\":\"delete_all\"}}]}");
        assertThatThrownBy(() -> service.forRun(List.of(flow), owner)).hasMessageContaining("未授权");
        server.setEnabled(0);
        assertThatThrownBy(() -> service.forRun(List.of(flow), owner)).hasMessageContaining("已禁用");
    }
    @Test void changedUrlClearsOldSecretsAndDiscovery() {
        McpServer server = server(); server.setHeadersCipher(crypto.encrypt("{\"Authorization\":\"Bearer SECRET\"}"));
        when(mapper.selectById(4L)).thenReturn(server);
        McpServerRequest request = request(); request.setUrl("https://other.example/mcp");
        service.save(4L, request, owner);
        assertThat(server.getHeadersCipher()).isNull(); assertThat(server.getTools()).isEqualTo("[]");
        assertThat(server.getAllowedTools()).isEqualTo("[]");
    }
    @Test void blankHeadersRetainCredentialsButExplicitClearRemovesThem() {
        McpServer server = server(); server.setHeadersCipher("enc:v1:stored"); when(mapper.selectById(4L)).thenReturn(server);
        service.save(4L, request(), owner); assertThat(server.getHeadersCipher()).isEqualTo("enc:v1:stored");
        McpServerRequest request = request(); request.setClearHeaders(true); service.save(4L, request, owner);
        assertThat(server.getHeadersCipher()).isNull();
    }
    @Test void toolsMustBeDiscoveredBeforeGrantingPermission() {
        McpServerRequest request = request(); request.setAllowedTools(List.of("invented"));
        assertThatThrownBy(() -> service.save(null, request, owner)).hasMessageContaining("先测试连接");
        verify(mapper, never()).insert(any(McpServer.class));
    }
    @Test void discoveryUsesConditionalUpdateAndReportsConcurrentChanges() throws Exception {
        when(mapper.selectById(4L)).thenReturn(server());
        when(ai.postJson(eq("/v1/mcp/discover"), any())).thenReturn(json.readTree("{\"data\":{\"ok\":true,\"tools\":[]}}"));
        when(mapper.update(isNull(), any())).thenReturn(0);
        assertThatThrownBy(() -> service.discover(4L, owner)).hasMessageContaining("配置已变更");
        verify(mapper, never()).updateById(any(McpServer.class));
    }
    @ParameterizedTest @ValueSource(strings={"file:///etc/passwd", "https://user:secret@example.com/mcp", "https://example.com/mcp?token=secret"})
    void validatesUnsafeUrls(String url) {
        McpServerRequest request = request(); request.setUrl(url);
        assertThatThrownBy(() -> service.save(null, request, owner)).isInstanceOf(BizException.class);
        verifyNoInteractions(mapper, ai);
    }
}
