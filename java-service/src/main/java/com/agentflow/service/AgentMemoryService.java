package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.MemorySearchRequest;
import com.agentflow.dto.MemoryVO;
import com.agentflow.dto.MemoryWriteRequest;
import com.agentflow.entity.AgentMemory;
import com.agentflow.mapper.AgentMemoryMapper;
import com.agentflow.security.CurrentUser;
import com.agentflow.util.KnowledgeScorer;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Agent 长期记忆：写入、召回与按归属管理。
 *
 * <p>记忆表由 Java 独占，ai-service 只通过 /internal/memory/* 读写；
 * 召回打分与知识库一致：有向量时向量 + 词法混合，无向量时退化为词法匹配。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AgentMemoryService {

    private static final int MAX_CONTENT = 8000;
    private static final int MAX_CANDIDATES = 1000;
    private static final int MAX_TOP_K = 20;
    private static final int MAX_TAGS = 10;
    private static final int MAX_TAG_LENGTH = 32;
    private static final Set<String> SCOPES = Set.of("workflow", "user", "global");

    private final AgentMemoryMapper memoryMapper;
    private final LlmProviderService llmProviderService;
    private final AiClient aiClient;
    private final ObjectMapper objectMapper;

    @Transactional
    public Map<String, Object> write(MemoryWriteRequest request) {
        String content = request.getContent() == null ? "" : request.getContent().trim();
        if (content.isEmpty()) {
            throw new BizException("记忆内容不能为空");
        }
        if (content.length() > MAX_CONTENT) {
            throw new BizException("记忆内容不能超过 " + MAX_CONTENT + " 字");
        }
        String scope = normalizeScope(request.getScope());
        requireScopeContext(scope, request.getWorkflowId(), request.getUserId());

        double[] vector = tryEmbed(request.getProvider(), request.getModel(), content);
        AgentMemory memory = new AgentMemory();
        memory.setWorkflowId(request.getWorkflowId());
        memory.setUserId(request.getUserId());
        memory.setScope(scope);
        memory.setMemoryType(normalizeType(request.getMemoryType()));
        memory.setContent(content);
        memory.setTags(String.join(",", normalizeTags(request.getTags())));
        memory.setSourceNodeId(trimTo(request.getSourceNodeId(), 64));
        memory.setEmbedding(vector == null ? null : writeVector(vector));
        memory.setEmbeddingModel(vector == null ? null : trimTo(request.getModel(), 64));
        memoryMapper.insert(memory);

        Map<String, Object> output = new LinkedHashMap<>();
        output.put("memoryId", String.valueOf(memory.getId()));
        output.put("scope", scope);
        output.put("stored", true);
        return output;
    }

    public Map<String, Object> search(MemorySearchRequest request) {
        String query = request.getQuery() == null ? "" : request.getQuery().trim();
        if (query.isEmpty()) {
            throw new BizException("召回记忆的语句不能为空");
        }
        String scope = normalizeScope(request.getScope());
        requireScopeContext(scope, request.getWorkflowId(), request.getUserId());
        int topK = clamp(request.getTopK(), 1, MAX_TOP_K, 5);
        List<String> requiredTags = normalizeTags(request.getTags());

        LambdaQueryWrapper<AgentMemory> wrapper = scopeWrapper(scope, request.getWorkflowId(), request.getUserId())
                .orderByDesc(AgentMemory::getId)
                .last("LIMIT " + MAX_CANDIDATES);
        List<AgentMemory> candidates = memoryMapper.selectList(wrapper).stream()
                .filter(memory -> parsedTags(memory.getTags()).containsAll(requiredTags))
                .toList();
        if (candidates.isEmpty()) {
            return emptyResult();
        }

        double[] queryVector = tryEmbed(request.getProvider(), request.getModel(), query);
        Map<String, Integer> queryGrams = KnowledgeScorer.gramCounts(query);
        List<Map<String, Integer>> memoryGrams = new ArrayList<>();
        for (AgentMemory memory : candidates) {
            memoryGrams.add(KnowledgeScorer.gramCounts(memory.getContent()));
        }
        Map<String, Integer> documentFrequency = new HashMap<>();
        for (String gram : queryGrams.keySet()) {
            int frequency = 0;
            for (Map<String, Integer> grams : memoryGrams) {
                if (grams.containsKey(gram)) {
                    frequency++;
                }
            }
            documentFrequency.put(gram, frequency);
        }
        double ceiling = KnowledgeScorer.lexicalCeiling(queryGrams, candidates.size(), documentFrequency);

        List<MemoryVO> hits = new ArrayList<>();
        for (int index = 0; index < candidates.size(); index++) {
            AgentMemory memory = candidates.get(index);
            double lexical = KnowledgeScorer.lexicalScore(
                    queryGrams, memoryGrams.get(index), candidates.size(), documentFrequency, ceiling);
            double score = lexical;
            if (queryVector != null) {
                double[] stored = readVector(memory.getEmbedding());
                if (stored != null && stored.length == queryVector.length) {
                    score = KnowledgeScorer.hybrid(KnowledgeScorer.cosine(queryVector, stored), lexical);
                }
            }
            if (score <= 0) {
                continue;
            }
            MemoryVO vo = MemoryVO.of(memory, parsedTags(memory.getTags()));
            vo.setScore(Math.round(score * 1000.0) / 1000.0);
            hits.add(vo);
        }
        hits.sort(Comparator.comparingDouble(MemoryVO::getScore).reversed());
        List<MemoryVO> memories = hits.stream().limit(topK).toList();

        StringBuilder context = new StringBuilder();
        for (MemoryVO memory : memories) {
            context.append("- ").append(memory.getContent()).append('\n');
        }
        Map<String, Object> output = new LinkedHashMap<>();
        output.put("memories", memories);
        output.put("context", context.toString().trim());
        output.put("count", memories.size());
        return output;
    }

    public List<MemoryVO> list(CurrentUser user, String scope, Long workflowId) {
        LambdaQueryWrapper<AgentMemory> wrapper = new LambdaQueryWrapper<>();
        if (user != null && !isAdmin(user)) {
            wrapper.and(item -> item.eq(AgentMemory::getUserId, user.id())
                    .or().eq(AgentMemory::getScope, "global"));
        }
        if (scope != null && !scope.isBlank()) {
            wrapper.eq(AgentMemory::getScope, normalizeScope(scope));
        }
        if (workflowId != null) {
            wrapper.eq(AgentMemory::getWorkflowId, workflowId);
        }
        wrapper.orderByDesc(AgentMemory::getId).last("LIMIT 200");
        return memoryMapper.selectList(wrapper).stream()
                .map(memory -> MemoryVO.of(memory, parsedTags(memory.getTags())))
                .toList();
    }

    @Transactional
    public void delete(Long id, CurrentUser user) {
        AgentMemory memory = memoryMapper.selectById(id);
        if (memory == null) {
            throw BizException.notFound("记忆不存在: " + id);
        }
        if (user != null && !isAdmin(user) && !user.id().equals(memory.getUserId())) {
            throw BizException.notFound("记忆不存在: " + id);
        }
        memoryMapper.deleteById(id);
    }

    private LambdaQueryWrapper<AgentMemory> scopeWrapper(String scope, Long workflowId, Long userId) {
        LambdaQueryWrapper<AgentMemory> wrapper = new LambdaQueryWrapper<>();
        switch (scope) {
            case "workflow" -> wrapper.eq(AgentMemory::getWorkflowId, workflowId);
            case "user" -> wrapper.eq(AgentMemory::getUserId, userId);
            default -> { }
        }
        return wrapper;
    }

    private void requireScopeContext(String scope, Long workflowId, Long userId) {
        if ("workflow".equals(scope) && workflowId == null) {
            throw new BizException("工作流范围的记忆缺少 workflowId");
        }
        if ("user".equals(scope) && userId == null) {
            throw new BizException("用户范围的记忆缺少 userId");
        }
    }

    private String normalizeScope(String scope) {
        String value = scope == null ? "workflow" : scope.trim().toLowerCase();
        return SCOPES.contains(value) ? value : "workflow";
    }

    private String normalizeType(String type) {
        String value = type == null ? "fact" : type.trim().toLowerCase();
        return value.isEmpty() ? "fact" : trimTo(value, 32);
    }

    private List<String> normalizeTags(List<String> tags) {
        if (tags == null || tags.isEmpty()) {
            return List.of();
        }
        LinkedHashSet<String> unique = new LinkedHashSet<>();
        for (String item : tags) {
            if (item == null) {
                continue;
            }
            for (String part : item.split("[,，]")) {
                String value = part.trim();
                if (!value.isEmpty()) {
                    unique.add(trimTo(value, MAX_TAG_LENGTH));
                }
                if (unique.size() >= MAX_TAGS) {
                    return new ArrayList<>(unique);
                }
            }
        }
        return new ArrayList<>(unique);
    }

    private List<String> parsedTags(String tags) {
        if (tags == null || tags.isBlank()) {
            return List.of();
        }
        List<String> result = new ArrayList<>();
        for (String item : tags.split(",")) {
            if (!item.isBlank()) {
                result.add(item.trim());
            }
        }
        return result;
    }

    private double[] tryEmbed(String provider, String model, String text) {
        if (provider == null || provider.isBlank() || "mock".equalsIgnoreCase(provider)) {
            return null;
        }
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("provider", provider.trim());
            payload.put("model", model == null || model.isBlank() ? "text-embedding-3-small" : model.trim());
            payload.put("input", List.of(text));
            Map<String, String> credentials = llmProviderService.credentials(provider);
            if (credentials != null) {
                payload.put("apiKey", credentials.get("apiKey"));
                payload.put("baseUrl", credentials.getOrDefault("baseUrl", ""));
            }
            JsonNode data = aiClient.postJson("/v1/embeddings", payload).path("data");
            if (data.path("mock").asBoolean(false)) {
                return null;
            }
            JsonNode vector = data.path("vectors").path(0);
            if (!vector.isArray() || vector.isEmpty()) {
                return null;
            }
            double[] values = new double[vector.size()];
            for (int index = 0; index < vector.size(); index++) {
                values[index] = vector.get(index).asDouble();
            }
            return values;
        } catch (Exception ex) {
            log.warn("memory embedding failed, fallback to lexical: {}", ex.getMessage());
            return null;
        }
    }

    private String writeVector(double[] vector) {
        try {
            return objectMapper.writeValueAsString(vector);
        } catch (Exception ex) {
            return null;
        }
    }

    private double[] readVector(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(json, double[].class);
        } catch (Exception ex) {
            return null;
        }
    }

    private Map<String, Object> emptyResult() {
        Map<String, Object> output = new LinkedHashMap<>();
        output.put("memories", List.of());
        output.put("context", "");
        output.put("count", 0);
        return output;
    }

    private boolean isAdmin(CurrentUser user) {
        return user.role() != null && "ADMIN".equalsIgnoreCase(user.role());
    }

    private String trimTo(String value, int max) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.length() <= max ? trimmed : trimmed.substring(0, max);
    }

    private int clamp(Integer value, int min, int max, int fallback) {
        if (value == null) {
            return fallback;
        }
        return Math.max(min, Math.min(max, value));
    }
}
