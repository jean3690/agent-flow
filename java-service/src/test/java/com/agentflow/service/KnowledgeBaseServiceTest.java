package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.KnowledgeDocumentVO;
import com.agentflow.entity.KnowledgeBase;
import com.agentflow.entity.KnowledgeChunk;
import com.agentflow.entity.KnowledgeDocument;
import com.agentflow.mapper.KnowledgeBaseMapper;
import com.agentflow.mapper.KnowledgeChunkMapper;
import com.agentflow.mapper.KnowledgeDocumentMapper;
import com.agentflow.security.CurrentUser;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class KnowledgeBaseServiceTest {

    @Mock private KnowledgeBaseMapper baseMapper;
    @Mock private KnowledgeDocumentMapper documentMapper;
    @Mock private KnowledgeChunkMapper chunkMapper;
    @Mock private LlmProviderService llmProviderService;
    @Mock private AiClient aiClient;

    private KnowledgeBaseService service;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        // LambdaQueryWrapper 需要实体元数据缓存，否则 getSqlSegment() 无法解析列名
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""),
                KnowledgeBase.class);
        service = new KnowledgeBaseService(baseMapper, documentMapper, chunkMapper,
                llmProviderService, aiClient, objectMapper);
    }

    @Test
    void upsertForRuntimeCreatesDocumentAndIndexes() throws Exception {
        KnowledgeBase base = new KnowledgeBase();
        base.setId(5L);
        base.setChunkSize(600);
        base.setChunkOverlap(80);
        base.setEmbeddingProvider("mock");
        base.setEmbeddingModel("text-embedding-3-small");
        when(baseMapper.selectById(5L)).thenReturn(base);
        when(documentMapper.selectOne(any())).thenReturn(null);

        AtomicReference<KnowledgeDocument> saved = new AtomicReference<>();
        doAnswer(invocation -> {
            KnowledgeDocument document = invocation.getArgument(0);
            document.setId(9L);
            saved.set(document);
            return 1;
        }).when(documentMapper).insert(any(KnowledgeDocument.class));
        when(documentMapper.selectById(9L)).thenAnswer(invocation -> saved.get());

        JsonNode embedding = objectMapper.readTree(
                "{\"data\":{\"vectors\":[[0.1,0.2]],\"model\":\"text-embedding-3-small\",\"mock\":false}}");
        when(aiClient.postJson(eq("/v1/embeddings"), any())).thenReturn(embedding);
        when(llmProviderService.credentials("mock")).thenReturn(Map.of("apiKey", "test"));

        KnowledgeDocumentVO result = service.upsertForRuntime(5L, "e2e沉淀", "运行期写入的知识");

        assertThat(result.getStatus()).isEqualTo("INDEXED");
        assertThat(result.getChunkCount()).isEqualTo(1);
        assertThat(saved.get().getSourceType()).isEqualTo("NODE");
        verify(chunkMapper).insert(any(KnowledgeChunk.class));
        verify(documentMapper).updateById(any(KnowledgeDocument.class));
    }

    @Test
    void otherUserCannotReadKnowledgeBase() {
        KnowledgeBase base = new KnowledgeBase();
        base.setId(5L);
        base.setUserId(1L);
        when(baseMapper.selectById(5L)).thenReturn(base);

        assertThatThrownBy(() -> service.detail(5L, new CurrentUser(2L, "other", "USER")))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("知识库不存在");
    }

    @Test
    void otherUserCannotIndexOrDeleteDocuments() {
        KnowledgeBase base = new KnowledgeBase();
        base.setId(5L);
        base.setUserId(1L);
        when(baseMapper.selectById(5L)).thenReturn(base);
        CurrentUser other = new CurrentUser(2L, "other", "USER");

        assertThatThrownBy(() -> service.indexDocument(5L, 9L, other))
                .isInstanceOf(BizException.class);
        assertThatThrownBy(() -> service.deleteDocument(5L, 9L, other))
                .isInstanceOf(BizException.class);
        verify(documentMapper, never()).deleteById(any(Long.class));
    }

    @Test
    void adminCanReadAnyKnowledgeBase() {
        KnowledgeBase base = new KnowledgeBase();
        base.setId(5L);
        base.setUserId(1L);
        when(baseMapper.selectById(5L)).thenReturn(base);
        when(documentMapper.selectCount(any())).thenReturn(0L);
        when(chunkMapper.selectCount(any())).thenReturn(0L);

        assertThat(service.detail(5L, new CurrentUser(9L, "admin", "ADMIN")).getId()).isEqualTo(5L);
    }

    @Test
    void listFiltersByOwnerForNormalUser() {
        when(baseMapper.selectList(any())).thenReturn(List.of());

        service.list(new CurrentUser(2L, "other", "USER"));

        ArgumentCaptor<LambdaQueryWrapper<KnowledgeBase>> captor = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(baseMapper).selectList(captor.capture());
        assertThat(captor.getValue().getSqlSegment()).contains("user_id");
        assertThat(captor.getValue().getParamNameValuePairs()).containsValue(2L);
    }
}