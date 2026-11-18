package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.KnowledgeBaseRequest;
import com.agentflow.dto.KnowledgeBaseVO;
import com.agentflow.dto.KnowledgeChunkVO;
import com.agentflow.dto.KnowledgeDocumentVO;
import com.agentflow.dto.KnowledgeSearchHitVO;
import com.agentflow.entity.KnowledgeBase;
import com.agentflow.entity.KnowledgeChunk;
import com.agentflow.entity.KnowledgeDocument;
import com.agentflow.mapper.KnowledgeBaseMapper;
import com.agentflow.mapper.KnowledgeChunkMapper;
import com.agentflow.mapper.KnowledgeDocumentMapper;
import com.agentflow.security.CurrentUser;
import com.agentflow.util.KnowledgeScorer;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeBaseService {

    private static final int MAX_TOP_K = 10;
    private static final int EMBED_BATCH = 16;

    private final KnowledgeBaseMapper baseMapper;
    private final KnowledgeDocumentMapper documentMapper;
    private final KnowledgeChunkMapper chunkMapper;
    private final LlmProviderService llmProviderService;
    private final AiClient aiClient;
    private final ObjectMapper objectMapper;

    /** 管理员可见全部知识库，普通用户只能看到自己创建的。 */
    public List<KnowledgeBaseVO> list(CurrentUser user) {
        return baseMapper.selectList(new LambdaQueryWrapper<KnowledgeBase>()
                        .eq(isOwnerFiltered(user), KnowledgeBase::getUserId, userIdOf(user))
                        .orderByDesc(KnowledgeBase::getUpdatedAt))
                .stream().map(this::toVO).toList();
    }

    public KnowledgeBaseVO detail(Long id, CurrentUser user) {
        return toVO(getOwned(id, user));
    }

    @Transactional
    public KnowledgeBaseVO create(KnowledgeBaseRequest request, CurrentUser user) {
        KnowledgeBase base = new KnowledgeBase();
        base.setName(request.getName().trim());
        base.setDescription(request.getDescription() == null ? "" : request.getDescription());
        base.setEmbeddingProvider(request.getEmbeddingProvider() == null ? "mock" : request.getEmbeddingProvider());
        base.setEmbeddingModel(request.getEmbeddingModel() == null ? "text-embedding-3-small" : request.getEmbeddingModel());
        base.setChunkSize(clamp(request.getChunkSize(), 200, 2000, 600));
        base.setChunkOverlap(clamp(request.getChunkOverlap(), 0, base.getChunkSize() / 2, 80));
        base.setUserId(user == null ? null : user.id());
        baseMapper.insert(base);
        return toVO(base);
    }

    @Transactional
    public void delete(Long id, CurrentUser user) {
        KnowledgeBase base = getOwned(id, user);
        chunkMapper.delete(new LambdaQueryWrapper<KnowledgeChunk>()
                .eq(KnowledgeChunk::getKnowledgeBaseId, base.getId()));
        documentMapper.delete(new LambdaQueryWrapper<KnowledgeDocument>()
                .eq(KnowledgeDocument::getKnowledgeBaseId, base.getId()));
        baseMapper.deleteById(base.getId());
    }

    public List<KnowledgeDocumentVO> documents(Long knowledgeBaseId, CurrentUser user) {
        getOwned(knowledgeBaseId, user);
        return documentMapper.selectList(new LambdaQueryWrapper<KnowledgeDocument>()
                        .eq(KnowledgeDocument::getKnowledgeBaseId, knowledgeBaseId)
                        .orderByDesc(KnowledgeDocument::getId))
                .stream().map(KnowledgeDocumentVO::of).toList();
    }

    @Transactional
    public KnowledgeDocumentVO importText(Long knowledgeBaseId, String title, String content,
                                         String sourceType, CurrentUser user) {
        getOwned(knowledgeBaseId, user);
        return importTextInternal(knowledgeBaseId, title, content, sourceType);
    }

    private KnowledgeDocumentVO importTextInternal(Long knowledgeBaseId, String title, String content, String sourceType) {
        if (content == null || content.trim().isEmpty()) {
            throw new BizException("文档内容不能为空");
        }
        KnowledgeDocument document = new KnowledgeDocument();
        document.setKnowledgeBaseId(knowledgeBaseId);
        document.setTitle(title == null || title.isBlank() ? "未命名文档" : title.trim());
        document.setSourceType(sourceType == null ? "TEXT" : sourceType);
        document.setContent(content);
        document.setCharCount(content.length());
        document.setStatus("PENDING");
        document.setChunkCount(0);
        documentMapper.insert(document);
        return KnowledgeDocumentVO.of(document);
    }

    /**
     * 供 ai-service 的 knowledge_upsert 节点调用：同一知识库内按标题覆盖写入并立即建索引。
     */
    @Transactional
    public KnowledgeDocumentVO upsertForRuntime(Long knowledgeBaseId, String title, String content) {
        getEntity(knowledgeBaseId);
        String body = content == null ? "" : content.trim();
        if (body.isEmpty()) {
            throw new BizException("文档内容不能为空");
        }
        if (body.length() > 200_000) {
            throw new BizException("文档内容不能超过 200000 字");
        }
        String docTitle = title == null || title.isBlank()
                ? "runtime-" + System.currentTimeMillis()
                : title.trim();
        if (docTitle.length() > 255) {
            throw new BizException("文档标题不能超过 255 字");
        }

        KnowledgeDocument document = documentMapper.selectOne(new LambdaQueryWrapper<KnowledgeDocument>()
                .eq(KnowledgeDocument::getKnowledgeBaseId, knowledgeBaseId)
                .eq(KnowledgeDocument::getTitle, docTitle)
                .last("LIMIT 1"));
        if (document == null) {
            document = new KnowledgeDocument();
            document.setKnowledgeBaseId(knowledgeBaseId);
            document.setTitle(docTitle);
            document.setSourceType("NODE");
            document.setContent(body);
            document.setCharCount(body.length());
            document.setStatus("PENDING");
            document.setChunkCount(0);
            documentMapper.insert(document);
        } else {
            document.setContent(body);
            document.setCharCount(body.length());
            document.setSourceType("NODE");
            documentMapper.updateById(document);
            chunkMapper.delete(new LambdaQueryWrapper<KnowledgeChunk>()
                    .eq(KnowledgeChunk::getDocumentId, document.getId()));
        }
        return indexDocumentInternal(knowledgeBaseId, document.getId());
    }

    @Transactional
    public KnowledgeDocumentVO uploadTextFile(Long knowledgeBaseId, MultipartFile file, CurrentUser user) {
        getOwned(knowledgeBaseId, user);
        if (file == null || file.isEmpty()) {
            throw new BizException("请选择文件");
        }
        String name = file.getOriginalFilename() == null ? "uploaded.txt" : file.getOriginalFilename();
        String lower = name.toLowerCase();
        if (!lower.endsWith(".txt") && !lower.endsWith(".md") && !lower.endsWith(".markdown")) {
            throw new BizException("目前仅支持 txt / md 文件");
        }
        try {
            String content = new String(file.getBytes(), StandardCharsets.UTF_8);
            return importTextInternal(knowledgeBaseId, name, content, "FILE");
        } catch (Exception ex) {
            throw new BizException("读取文件失败: " + ex.getMessage());
        }
    }

    @Transactional
    public void deleteDocument(Long knowledgeBaseId, Long documentId, CurrentUser user) {
        getOwned(knowledgeBaseId, user);
        KnowledgeDocument document = requireDocument(knowledgeBaseId, documentId);
        chunkMapper.delete(new LambdaQueryWrapper<KnowledgeChunk>()
                .eq(KnowledgeChunk::getDocumentId, document.getId()));
        documentMapper.deleteById(document.getId());
    }

    public List<KnowledgeChunkVO> previewChunks(Long knowledgeBaseId, Long documentId, Integer chunkSize,
                                               Integer chunkOverlap, CurrentUser user) {
        KnowledgeBase base = getOwned(knowledgeBaseId, user);
        KnowledgeDocument document = requireDocument(knowledgeBaseId, documentId);
        int size = clamp(chunkSize, 200, 2000, base.getChunkSize());
        int overlap = clamp(chunkOverlap, 0, size / 2, base.getChunkOverlap());
        List<String> chunks = split(document.getContent(), size, overlap);
        List<KnowledgeChunkVO> result = new ArrayList<>();
        for (int index = 0; index < chunks.size(); index++) {
            result.add(KnowledgeChunkVO.builder()
                    .chunkIndex(index)
                    .content(chunks.get(index))
                    .charCount(chunks.get(index).length())
                    .build());
        }
        return result;
    }

    @Transactional
    public KnowledgeDocumentVO indexDocument(Long knowledgeBaseId, Long documentId, CurrentUser user) {
        getOwned(knowledgeBaseId, user);
        return indexDocumentInternal(knowledgeBaseId, documentId);
    }

    private KnowledgeDocumentVO indexDocumentInternal(Long knowledgeBaseId, Long documentId) {
        KnowledgeBase base = getEntity(knowledgeBaseId);
        KnowledgeDocument document = requireDocument(knowledgeBaseId, documentId);
        List<String> chunks = split(document.getContent(), base.getChunkSize(), base.getChunkOverlap());
        if (chunks.isEmpty()) {
            document.setStatus("FAILED");
            document.setErrorMessage("文档内容为空，无法分片");
            documentMapper.updateById(document);
            return KnowledgeDocumentVO.of(document);
        }

        try {
            List<List<Double>> vectors = new ArrayList<>();
            String model = base.getEmbeddingModel();
            boolean mock = false;
            for (int start = 0; start < chunks.size(); start += EMBED_BATCH) {
                int end = Math.min(start + EMBED_BATCH, chunks.size());
                EmbeddingResult batch = embed(base, chunks.subList(start, end));
                vectors.addAll(batch.vectors());
                model = batch.model();
                mock = batch.mock();
            }
            if (vectors.size() != chunks.size()) {
                throw new IllegalStateException("embedding 返回数量与分片数量不一致");
            }

            chunkMapper.delete(new LambdaQueryWrapper<KnowledgeChunk>()
                    .eq(KnowledgeChunk::getDocumentId, document.getId()));
            for (int index = 0; index < chunks.size(); index++) {
                KnowledgeChunk chunk = new KnowledgeChunk();
                chunk.setKnowledgeBaseId(knowledgeBaseId);
                chunk.setDocumentId(document.getId());
                chunk.setChunkIndex(index);
                chunk.setContent(chunks.get(index));
                chunk.setCharCount(chunks.get(index).length());
                chunk.setEmbeddingModel(mock ? "mock-embedding" : model);
                if (!mock) {
                    chunk.setEmbedding(objectMapper.writeValueAsString(vectors.get(index)));
                }
                chunkMapper.insert(chunk);
            }

            document.setStatus("INDEXED");
            document.setChunkCount(chunks.size());
            document.setErrorMessage(null);
            document.setCharCount(document.getContent().length());
            documentMapper.updateById(document);
        } catch (Exception ex) {
            document.setStatus("FAILED");
            document.setErrorMessage(trimMessage(ex.getMessage()));
            documentMapper.updateById(document);
            log.warn("index document failed, docId={}: {}", documentId, ex.getMessage());
        }
        return KnowledgeDocumentVO.of(document);
    }

    public List<KnowledgeSearchHitVO> search(Long knowledgeBaseId, String query, Integer topK, CurrentUser user) {
        KnowledgeBase base = getOwned(knowledgeBaseId, user);
        return doSearch(base, query, topK);
    }

    /** 供 ai-service 在节点执行期调用。 */
    public List<KnowledgeSearchHitVO> searchForRuntime(Long knowledgeBaseId, String query, Integer topK) {
        return doSearch(getEntity(knowledgeBaseId), query, topK);
    }

    private List<KnowledgeSearchHitVO> doSearch(KnowledgeBase base, String query, Integer topK) {
        if (query == null || query.trim().isEmpty()) {
            throw new BizException("检索内容不能为空");
        }
        int limit = clamp(topK, 1, MAX_TOP_K, 4);
        List<KnowledgeChunk> chunks = chunkMapper.selectList(new LambdaQueryWrapper<KnowledgeChunk>()
                .eq(KnowledgeChunk::getKnowledgeBaseId, base.getId()));
        if (chunks.isEmpty()) {
            return List.of();
        }

        Map<Long, String> titles = new HashMap<>();
        documentMapper.selectList(new LambdaQueryWrapper<KnowledgeDocument>()
                        .eq(KnowledgeDocument::getKnowledgeBaseId, base.getId()))
                .forEach(document -> titles.put(document.getId(), document.getTitle()));

        EmbeddingResult queryEmbedding;
        try {
            queryEmbedding = embed(base, List.of(query.trim()));
        } catch (Exception ex) {
            log.warn("query embedding failed, fallback to lexical: {}", ex.getMessage());
            queryEmbedding = new EmbeddingResult(List.of(), "mock-embedding", true);
        }

        boolean lexical = queryEmbedding.mock() || queryEmbedding.vectors().isEmpty();
        double[] queryVector = lexical ? null : toVector(queryEmbedding.vectors().get(0));

        // 混合重排：向量相似为主、词法覆盖为辅；无向量（mock/缺 embedding）时退化为纯词法
        Map<String, Integer> queryGrams = KnowledgeScorer.gramCounts(query);
        List<Map<String, Integer>> chunkGrams = new ArrayList<>();
        for (KnowledgeChunk chunk : chunks) {
            chunkGrams.add(KnowledgeScorer.gramCounts(chunk.getContent()));
        }
        Map<String, Integer> documentFrequency = new HashMap<>();
        for (String gram : queryGrams.keySet()) {
            int frequency = 0;
            for (Map<String, Integer> grams : chunkGrams) {
                if (grams.containsKey(gram)) {
                    frequency++;
                }
            }
            documentFrequency.put(gram, frequency);
        }
        double lexicalCeiling = KnowledgeScorer.lexicalCeiling(queryGrams, chunks.size(), documentFrequency);

        List<KnowledgeSearchHitVO> hits = new ArrayList<>();
        for (int index = 0; index < chunks.size(); index++) {
            KnowledgeChunk chunk = chunks.get(index);
            double lexicalScore = KnowledgeScorer.lexicalScore(
                    queryGrams, chunkGrams.get(index), chunks.size(), documentFrequency, lexicalCeiling);
            double score = lexicalScore;
            if (!lexical) {
                double[] vector = parseVector(chunk.getEmbedding());
                if (vector != null && vector.length == queryVector.length) {
                    score = KnowledgeScorer.hybrid(KnowledgeScorer.cosine(queryVector, vector), lexicalScore);
                }
            }
            hits.add(KnowledgeSearchHitVO.builder()
                    .chunkId(chunk.getId())
                    .documentId(chunk.getDocumentId())
                    .title(titles.getOrDefault(chunk.getDocumentId(), ""))
                    .content(chunk.getContent())
                    .score(Math.round(score * 1000.0) / 1000.0)
                    .build());
        }
        hits.removeIf(hit -> hit.getScore() <= 0);
        hits.sort(Comparator.comparingDouble(KnowledgeSearchHitVO::getScore).reversed());
        return hits.stream().limit(limit).toList();
    }

    private EmbeddingResult embed(KnowledgeBase base, List<String> texts) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("provider", base.getEmbeddingProvider());
        payload.put("model", base.getEmbeddingModel());
        payload.put("input", texts);
        Map<String, String> credentials = llmProviderService.credentials(base.getEmbeddingProvider());
        if (credentials != null) {
            payload.put("apiKey", credentials.get("apiKey"));
            payload.put("baseUrl", credentials.getOrDefault("baseUrl", ""));
        }

        JsonNode data = aiClient.postJson("/v1/embeddings", payload).path("data");
        List<List<Double>> vectors = new ArrayList<>();
        for (JsonNode vector : data.path("vectors")) {
            List<Double> values = new ArrayList<>();
            vector.forEach(value -> values.add(value.asDouble()));
            vectors.add(values);
        }
        return new EmbeddingResult(vectors, data.path("model").asText(base.getEmbeddingModel()),
                data.path("mock").asBoolean(false));
    }

    /**
     * 资源级归属校验：非管理员访问他人知识库统一返回 404，避免通过 ID 探测资源是否存在。
     */
    private KnowledgeBase getOwned(Long id, CurrentUser user) {
        KnowledgeBase base = getEntity(id);
        if (isOwnerFiltered(user) && !user.id().equals(base.getUserId())) {
            throw BizException.notFound("知识库不存在: " + id);
        }
        return base;
    }

    private boolean isOwnerFiltered(CurrentUser user) {
        return user != null && !"ADMIN".equals(user.role());
    }

    private Long userIdOf(CurrentUser user) {
        return user == null ? -1L : user.id();
    }

    private KnowledgeBase getEntity(Long id) {
        KnowledgeBase base = baseMapper.selectById(id);
        if (base == null) {
            throw BizException.notFound("知识库不存在: " + id);
        }
        return base;
    }

    private KnowledgeDocument requireDocument(Long knowledgeBaseId, Long documentId) {
        KnowledgeDocument document = documentMapper.selectById(documentId);
        if (document == null || !document.getKnowledgeBaseId().equals(knowledgeBaseId)) {
            throw BizException.notFound("文档不存在: " + documentId);
        }
        return document;
    }

    private KnowledgeBaseVO toVO(KnowledgeBase base) {
        long documents = documentMapper.selectCount(new LambdaQueryWrapper<KnowledgeDocument>()
                .eq(KnowledgeDocument::getKnowledgeBaseId, base.getId()));
        long chunks = chunkMapper.selectCount(new LambdaQueryWrapper<KnowledgeChunk>()
                .eq(KnowledgeChunk::getKnowledgeBaseId, base.getId()));
        return KnowledgeBaseVO.builder()
                .id(base.getId())
                .name(base.getName())
                .description(base.getDescription())
                .embeddingProvider(base.getEmbeddingProvider())
                .embeddingModel(base.getEmbeddingModel())
                .chunkSize(base.getChunkSize())
                .chunkOverlap(base.getChunkOverlap())
                .documentCount(documents)
                .chunkCount(chunks)
                .createdAt(base.getCreatedAt())
                .build();
    }

    static List<String> split(String content, int size, int overlap) {
        List<String> chunks = new ArrayList<>();
        if (content == null) {
            return chunks;
        }
        String text = content.replace("\r\n", "\n").trim();
        if (text.isEmpty()) {
            return chunks;
        }
        int length = text.length();
        int start = 0;
        while (start < length) {
            if (start > 0) {
                // 重叠区可能落在句子中间，尽量从下一个句子边界开始，避免分片以半句开头
                int probe = Math.min(length, start + 80);
                for (int index = start + 1; index <= probe; index++) {
                    if (isBoundary(text.charAt(index - 1))) {
                        start = index;
                        break;
                    }
                }
                if (start >= length) {
                    break;
                }
            }
            int end = Math.min(start + size, length);
            if (end < length) {
                int floor = start + Math.max(1, size / 3);
                for (int index = end; index > floor; index--) {
                    if (isBoundary(text.charAt(index - 1))) {
                        end = index;
                        break;
                    }
                }
            }
            String piece = text.substring(start, end).trim();
            if (!piece.isEmpty()) {
                chunks.add(piece);
            }
            if (end >= length) {
                break;
            }
            start = Math.max(end - overlap, start + 1);
        }
        return chunks;
    }

    private static boolean isBoundary(char current) {
        return current == '\n' || current == '。' || current == '！' || current == '？'
                || current == '；' || current == ';';
    }






    private double[] parseVector(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(json, double[].class);
        } catch (Exception ex) {
            return null;
        }
    }

    private double[] toVector(List<Double> values) {
        double[] vector = new double[values.size()];
        for (int index = 0; index < values.size(); index++) {
            vector[index] = values.get(index);
        }
        return vector;
    }

    private int clamp(Integer value, int min, int max, int fallback) {
        if (value == null) {
            return fallback;
        }
        return Math.max(min, Math.min(max, value));
    }

    private String trimMessage(String message) {
        if (message == null) {
            return "索引失败";
        }
        return message.length() > 500 ? message.substring(0, 500) : message;
    }

    private record EmbeddingResult(List<List<Double>> vectors, String model, boolean mock) {
    }
}
