package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.entity.LlmProviderConfig;
import com.agentflow.mapper.LlmProviderConfigMapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class LlmProviderServiceTest {

    @Mock
    private AiClient aiClient;

    @Mock
    private LlmProviderConfigMapper configMapper;

    @Mock
    private CryptoService cryptoService;

    private final ObjectMapper json = new ObjectMapper();
    private LlmProviderService service;

    @BeforeEach
    void setUp() {
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), "test"), LlmProviderConfig.class);
        service = new LlmProviderService(aiClient, configMapper, cryptoService);
    }

    private LlmProviderConfig stored(String apiKey, String baseUrl) {
        LlmProviderConfig config = new LlmProviderConfig();
        config.setProvider("openai");
        config.setApiKey(apiKey);
        config.setBaseUrl(baseUrl);
        config.setEnabled(1);
        return config;
    }

    @Test
    void forwardsDecryptedKeyInPostBodyAndReturnsData() throws Exception {
        when(configMapper.selectOne(any())).thenReturn(stored("enc:v1:cipher", "https://proxy.example/v1"));
        when(cryptoService.decrypt("enc:v1:cipher")).thenReturn("sk-plain");
        when(aiClient.postJson(anyString(), any())).thenReturn(
                json.readTree("{\"data\":{\"ok\":true,\"models\":[\"gpt-4o\"]}}"));

        JsonNode result = service.models("openai");

        ArgumentCaptor<String> path = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object> payload = ArgumentCaptor.forClass(Object.class);
        verify(aiClient).postJson(path.capture(), payload.capture());
        assertThat(path.getValue()).isEqualTo("/v1/providers/models");
        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) payload.getValue();
        assertThat(body.get("provider")).isEqualTo("openai");
        assertThat(body.get("apiKey")).isEqualTo("sk-plain");
        assertThat(body.get("baseUrl")).isEqualTo("https://proxy.example/v1");
        assertThat(result.path("models").get(0).asText()).isEqualTo("gpt-4o");
    }

    @Test
    void sendsEmptyCredentialsWhenNothingStored() throws Exception {
        when(configMapper.selectOne(any())).thenReturn(null);
        when(aiClient.postJson(anyString(), any())).thenReturn(
                json.readTree("{\"data\":{\"ok\":false,\"source\":\"static\",\"models\":[]}}"));

        service.models("openai");

        ArgumentCaptor<Object> payload = ArgumentCaptor.forClass(Object.class);
        verify(aiClient).postJson(anyString(), payload.capture());
        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) payload.getValue();
        assertThat(body.get("apiKey")).isEqualTo("");
        assertThat(body.get("baseUrl")).isEqualTo("");
    }

    @Test
    void rejectsIllegalProviderWithoutCallingAiService() {
        assertThatThrownBy(() -> service.models("../openai")).isInstanceOf(BizException.class);
        verifyNoInteractions(aiClient);
    }

    @Test
    void doesNotCallAiServiceWhenDecryptionFails() {
        when(configMapper.selectOne(any())).thenReturn(stored("enc:v1:broken", ""));
        when(cryptoService.decrypt(anyString())).thenThrow(new BizException("密文损坏"));

        assertThatThrownBy(() -> service.models("openai")).isInstanceOf(BizException.class);
        verifyNoInteractions(aiClient);
    }

    @Test
    void propagatesUpstreamErrors() {
        when(configMapper.selectOne(any())).thenReturn(stored("enc:v1:cipher", ""));
        when(cryptoService.decrypt(anyString())).thenReturn("sk-plain");
        when(aiClient.postJson(anyString(), any())).thenThrow(new BizException("AI 服务返回错误: HTTP 502"));

        assertThatThrownBy(() -> service.models("openai"))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("502");
    }
}
