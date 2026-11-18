package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.MemorySearchRequest;
import com.agentflow.dto.MemoryVO;
import com.agentflow.dto.MemoryWriteRequest;
import com.agentflow.entity.AgentMemory;
import com.agentflow.mapper.AgentMemoryMapper;
import com.agentflow.security.CurrentUser;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AgentMemoryServiceTest {

    @Mock private AgentMemoryMapper memoryMapper;
    @Mock private LlmProviderService llmProviderService;
    @Mock private AiClient aiClient;

    private AgentMemoryService service;

    @BeforeEach
    void setUp() {
        service = new AgentMemoryService(memoryMapper, llmProviderService, aiClient, new ObjectMapper());
    }

    @Test
    void writeStoresMemoryWithNormalizedFields() {
        doAnswer(invocation -> {
            AgentMemory memory = invocation.getArgument(0);
            memory.setId(99L);
            return 1;
        }).when(memoryMapper).insert(any(AgentMemory.class));

        MemoryWriteRequest request = new MemoryWriteRequest();
        request.setWorkflowId(42L);
        request.setUserId(7L);
        request.setScope("workflow");
        request.setMemoryType("preference");
        request.setContent("  用户偏好表格排版  ");
        request.setTags(List.of("偏好", "排版", "偏好"));
        request.setSourceNodeId("mem-1");
        request.setProvider("mock");

        Map<String, Object> result = service.write(request);

        ArgumentCaptor<AgentMemory> captor = ArgumentCaptor.forClass(AgentMemory.class);
        verify(memoryMapper).insert(captor.capture());
        AgentMemory saved = captor.getValue();
        assertThat(saved.getContent()).isEqualTo("用户偏好表格排版");
        assertThat(saved.getWorkflowId()).isEqualTo(42L);
        assertThat(saved.getUserId()).isEqualTo(7L);
        assertThat(saved.getScope()).isEqualTo("workflow");
        assertThat(saved.getMemoryType()).isEqualTo("preference");
        assertThat(saved.getTags()).isEqualTo("偏好,排版");
        assertThat(saved.getEmbedding()).isNull();
        assertThat(result).containsEntry("memoryId", "99")
                .containsEntry("scope", "workflow")
                .containsEntry("stored", true);
    }

    @Test
    void writeRejectsBlankContent() {
        MemoryWriteRequest request = new MemoryWriteRequest();
        request.setScope("global");
        request.setContent("   ");
        assertThatThrownBy(() -> service.write(request)).isInstanceOf(BizException.class);
    }

    @Test
    void workflowScopeRequiresWorkflowId() {
        MemoryWriteRequest request = new MemoryWriteRequest();
        request.setScope("workflow");
        request.setContent("x");
        assertThatThrownBy(() -> service.write(request))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("workflowId");
    }

    @Test
    void searchRanksLexicallyAndFiltersByTags() {
        AgentMemory hit = memory(1L, "用户喜欢用表格展示周报", "偏好,周报");
        AgentMemory tagMiss = memory(2L, "用户喜欢用表格展示周报", "其他");
        AgentMemory noOverlap = memory(3L, "服务器部署在杭州", "运维");
        when(memoryMapper.selectList(any())).thenReturn(List.of(hit, tagMiss, noOverlap));

        MemorySearchRequest request = new MemorySearchRequest();
        request.setScope("workflow");
        request.setWorkflowId(42L);
        request.setQuery("周报 表格 排版");
        request.setTags(List.of("偏好"));
        request.setTopK(5);
        request.setProvider("mock");

        Map<String, Object> result = service.search(request);

        @SuppressWarnings("unchecked")
        List<MemoryVO> memories = (List<MemoryVO>) result.get("memories");
        assertThat(memories).hasSize(1);
        assertThat(memories.get(0).getContent()).contains("周报");
        assertThat(memories.get(0).getScore()).isGreaterThan(0);
        assertThat(result.get("context").toString()).isEqualTo("- 用户喜欢用表格展示周报");
        assertThat(result).containsEntry("count", 1);
    }

    @Test
    void searchReturnsEmptyWhenNoMemoryMatches() {
        when(memoryMapper.selectList(any())).thenReturn(List.of(memory(1L, "无关内容", "")));

        MemorySearchRequest request = new MemorySearchRequest();
        request.setScope("user");
        request.setUserId(7L);
        request.setQuery("完全不相关的词");
        request.setProvider("mock");

        Map<String, Object> result = service.search(request);

        assertThat(result).containsEntry("count", 0);
        assertThat(result.get("context")).isEqualTo("");
    }

    @Test
    void deleteRejectsOtherUsersMemory() {
        AgentMemory memory = memory(5L, "私有记忆", "");
        memory.setUserId(8L);
        when(memoryMapper.selectById(5L)).thenReturn(memory);

        assertThatThrownBy(() -> service.delete(5L, new CurrentUser(7L, "user", "USER")))
                .isInstanceOf(BizException.class);
    }

    @Test
    void adminCanDeleteAnyMemory() {
        when(memoryMapper.selectById(5L)).thenReturn(memory(5L, "任意记忆", ""));

        service.delete(5L, new CurrentUser(1L, "admin", "ADMIN"));

        verify(memoryMapper).deleteById(5L);
    }

    private AgentMemory memory(Long id, String content, String tags) {
        AgentMemory memory = new AgentMemory();
        memory.setId(id);
        memory.setWorkflowId(42L);
        memory.setUserId(7L);
        memory.setScope("workflow");
        memory.setMemoryType("fact");
        memory.setContent(content);
        memory.setTags(tags);
        return memory;
    }
}
