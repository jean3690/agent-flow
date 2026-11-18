package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.LlmProviderVO;
import com.agentflow.dto.ProviderTestRequest;
import com.agentflow.dto.SaveProviderRequest;
import com.agentflow.entity.LlmProviderConfig;
import com.agentflow.mapper.LlmProviderConfigMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * 服务商凭据的业务侧抽象：元数据来自 ai-service，密文与自定义地址落在 Java 库。
 * 执行时由 Java 把凭据下发给 ai-service，Python 侧不持久化任何 Key。
 */
@Service
@RequiredArgsConstructor
public class LlmProviderService {

    private static final Pattern PROVIDER_PATTERN = Pattern.compile("^[a-z][a-z0-9_-]{1,31}$");

    private final AiClient aiClient;
    private final LlmProviderConfigMapper configMapper;
    private final CryptoService cryptoService;

    public List<LlmProviderVO> list() {
        Map<String, LlmProviderConfig> stored = storedMap();
        List<LlmProviderVO> result = new ArrayList<>();
        for (JsonNode item : aiClient.data("/v1/providers")) {
            String provider = item.path("provider").asText();
            LlmProviderConfig config = stored.get(provider);
            boolean dbKey = config != null && hasText(config.getApiKey());
            boolean envKey = item.path("envConfigured").asBoolean(false);
            boolean mock = "mock".equals(provider);
            String baseUrl = config != null && hasText(config.getBaseUrl())
                    ? config.getBaseUrl()
                    : item.path("baseUrl").asText("");

            result.add(LlmProviderVO.builder()
                    .provider(provider)
                    .label(item.path("label").asText(provider))
                    .defaultModel(item.path("defaultModel").asText(""))
                    .models(textList(item.path("models")))
                    .supportsTts(item.path("supportsTts").asBoolean(false))
                    .configured(dbKey || envKey || mock)
                    .source(dbKey ? "DB" : envKey ? "ENV" : "NONE")
                    .baseUrl(baseUrl)
                    .apiKeyMasked(dbKey ? mask(cryptoService.decrypt(config.getApiKey())) : "")
                    .build());
        }
        return result;
    }

    @Transactional
    public void save(String provider, SaveProviderRequest request) {
        requireProvider(provider);
        String apiKey = trim(request.getApiKey());
        String baseUrl = trim(request.getBaseUrl());

        LlmProviderConfig existing = findEntity(provider);
        if (existing == null) {
            if (!hasText(apiKey)) {
                throw new BizException("请填写 API Key");
            }
            LlmProviderConfig config = new LlmProviderConfig();
            config.setProvider(provider);
            config.setApiKey(cryptoService.encrypt(apiKey));
            config.setBaseUrl(baseUrl);
            config.setEnabled(1);
            configMapper.insert(config);
            return;
        }

        if (hasText(apiKey)) {
            existing.setApiKey(cryptoService.encrypt(apiKey));
        }
        if (!hasText(existing.getApiKey())) {
            throw new BizException("请填写 API Key");
        }
        existing.setBaseUrl(baseUrl);
        existing.setEnabled(1);
        configMapper.updateById(existing);
    }

    @Transactional
    public void clear(String provider) {
        requireProvider(provider);
        configMapper.delete(new LambdaQueryWrapper<LlmProviderConfig>()
                .eq(LlmProviderConfig::getProvider, provider));
    }

    public JsonNode test(String provider, ProviderTestRequest request) {
        requireProvider(provider);
        LlmProviderConfig stored = findEntity(provider);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("provider", provider);
        payload.put("apiKey", hasText(request.getApiKey())
                ? request.getApiKey().trim()
                : stored == null ? "" : cryptoService.decrypt(stored.getApiKey()));
        payload.put("baseUrl", hasText(request.getBaseUrl())
                ? request.getBaseUrl().trim()
                : stored == null ? "" : stored.getBaseUrl());
        if (hasText(request.getModel())) {
            payload.put("model", request.getModel().trim());
        }
        return aiClient.postJson("/v1/providers/test", payload).path("data");
    }

    /** 拉取服务商实际可用模型；明文 Key 只在发给 ai-service 的 POST body 中，前端 GET 不带任何凭据。 */
    public JsonNode models(String provider) {
        requireProvider(provider);
        Map<String, String> credentials = credentials(provider);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("provider", provider);
        payload.put("apiKey", credentials == null ? "" : credentials.get("apiKey"));
        payload.put("baseUrl", credentials == null ? "" : credentials.get("baseUrl"));
        return aiClient.postJson("/v1/providers/models", payload).path("data");
    }

    /** 单个服务商的已保存凭据，未配置时返回 null。 */
    public Map<String, String> credentials(String provider) {
        LlmProviderConfig config = findEntity(provider);
        if (config == null || !hasText(config.getApiKey())) {
            return null;
        }
        Map<String, String> entry = new LinkedHashMap<>();
        entry.put("apiKey", cryptoService.decrypt(config.getApiKey()));
        entry.put("baseUrl", hasText(config.getBaseUrl()) ? config.getBaseUrl() : "");
        return entry;
    }

    /** 执行工作流时下发给 ai-service 的凭据，仅包含已保存 Key 的服务商。 */
    public Map<String, Map<String, String>> credentialsForRun() {
        Map<String, Map<String, String>> result = new LinkedHashMap<>();
        List<LlmProviderConfig> configs = configMapper.selectList(
                new LambdaQueryWrapper<LlmProviderConfig>().eq(LlmProviderConfig::getEnabled, 1));
        for (LlmProviderConfig config : configs) {
            if (!hasText(config.getApiKey())) {
                continue;
            }
            Map<String, String> entry = new LinkedHashMap<>();
            entry.put("apiKey", cryptoService.decrypt(config.getApiKey()));
            if (hasText(config.getBaseUrl())) {
                entry.put("baseUrl", config.getBaseUrl());
            }
            result.put(config.getProvider(), entry);
        }
        return result;
    }

    private Map<String, LlmProviderConfig> storedMap() {
        Map<String, LlmProviderConfig> result = new LinkedHashMap<>();
        for (LlmProviderConfig config : configMapper.selectList(null)) {
            result.put(config.getProvider(), config);
        }
        return result;
    }

    private LlmProviderConfig findEntity(String provider) {
        return configMapper.selectOne(new LambdaQueryWrapper<LlmProviderConfig>()
                .eq(LlmProviderConfig::getProvider, provider));
    }

    private void requireProvider(String provider) {
        if (provider == null || !PROVIDER_PATTERN.matcher(provider).matches()) {
            throw new BizException("非法服务商标识: " + provider);
        }
    }

    private List<String> textList(JsonNode node) {
        List<String> items = new ArrayList<>();
        node.forEach(item -> items.add(item.asText()));
        return items;
    }

    private String mask(String apiKey) {
        if (apiKey.length() <= 4) {
            return "****";
        }
        return "****" + apiKey.substring(apiKey.length() - 4);
    }

    private boolean hasText(String value) {
        return value != null && !value.trim().isEmpty();
    }

    private String trim(String value) {
        return value == null ? "" : value.trim();
    }
}
