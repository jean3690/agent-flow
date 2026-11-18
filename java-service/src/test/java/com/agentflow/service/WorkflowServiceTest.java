package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.WorkflowDetailVO;
import com.agentflow.dto.WorkflowSaveRequest;
import com.agentflow.entity.Workflow;
import com.agentflow.entity.WorkflowTrigger;
import com.agentflow.entity.WorkflowVersion;
import com.agentflow.event.TriggerChangedEvent;
import com.agentflow.mapper.WorkflowMapper;
import com.agentflow.mapper.WorkflowTriggerMapper;
import com.agentflow.mapper.WorkflowVersionMapper;
import com.agentflow.security.CurrentUser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.context.ApplicationEventPublisher;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class WorkflowServiceTest {

    private static final CurrentUser OWNER = new CurrentUser(1L, "owner", "USER");
    private static final CurrentUser OTHER = new CurrentUser(2L, "other", "USER");
    private static final CurrentUser ADMIN = new CurrentUser(9L, "admin", "ADMIN");

    @Mock private WorkflowMapper workflowMapper;
    @Mock private WorkflowTriggerMapper triggerMapper;
    @Mock private WorkflowVersionMapper versionMapper;
    @Mock private ApplicationEventPublisher events;

    private final ObjectMapper objectMapper = new ObjectMapper();
    private WorkflowService service;

    @BeforeEach
    void setUp() {
        service = new WorkflowService(workflowMapper, triggerMapper, versionMapper, events, objectMapper);
    }

    private JsonNode flow(String marker) {
        ObjectNode root = objectMapper.createObjectNode();
        root.set("nodes", objectMapper.createArrayNode()
                .add(objectMapper.createObjectNode().put("id", "n1").put("type", "input").put("label", marker)));
        root.set("edges", objectMapper.createArrayNode());
        return root;
    }

    private Workflow published(Integer version, Integer publishedVersion, String flowData) {
        Workflow workflow = new Workflow();
        workflow.setId(5L);
        workflow.setName("demo");
        workflow.setUserId(1L);
        workflow.setVersion(version);
        workflow.setPublishedVersion(publishedVersion);
        workflow.setStatus(2);
        workflow.setFlowData(flowData);
        workflow.setEngineType("langgraph");
        return workflow;
    }

    @Test
    void createStoresOwnerAndInitialSnapshot() {
        WorkflowSaveRequest request = new WorkflowSaveRequest();
        request.setName("demo");
        request.setFlow(flow("v1"));
        when(workflowMapper.insert(any(Workflow.class))).thenAnswer(invocation -> {
            Workflow saved = invocation.getArgument(0);
            saved.setId(5L);
            return 1;
        });

        WorkflowDetailVO detail = service.create(request, OWNER);

        assertThat(detail.getVersion()).isEqualTo(1);
        ArgumentCaptor<Workflow> workflowCaptor = ArgumentCaptor.forClass(Workflow.class);
        verify(workflowMapper).insert(workflowCaptor.capture());
        assertThat(workflowCaptor.getValue().getUserId()).isEqualTo(1L);

        ArgumentCaptor<WorkflowVersion> versionCaptor = ArgumentCaptor.forClass(WorkflowVersion.class);
        verify(versionMapper).insert(versionCaptor.capture());
        assertThat(versionCaptor.getValue().getVersion()).isEqualTo(1);
        assertThat(versionCaptor.getValue().getNote()).isEqualTo("初始版本");
    }

    @Test
    void savingDraftOfPublishedWorkflowKeepsPublishedPointer() {
        Workflow workflow = published(3, 2, flow("old").toString());
        when(workflowMapper.selectById(5L)).thenReturn(workflow);

        WorkflowSaveRequest request = new WorkflowSaveRequest();
        request.setName("demo");
        request.setStatus(1);
        request.setFlow(flow("new"));

        service.update(5L, request, OWNER);

        assertThat(workflow.getVersion()).isEqualTo(4);
        assertThat(workflow.getPublishedVersion()).isEqualTo(2);
        assertThat(workflow.getStatus()).isEqualTo(2);
        verify(workflowMapper).updateById(workflow);
        verify(versionMapper).insert(any(WorkflowVersion.class));
    }

    @Test
    void publishMovesPublishedPointerToCurrentVersion() {
        Workflow workflow = published(3, null, flow("current").toString());
        when(workflowMapper.selectById(5L)).thenReturn(workflow);
        when(versionMapper.selectOne(any())).thenReturn(null);

        WorkflowDetailVO detail = service.publish(5L, OWNER);

        assertThat(detail.getPublishedVersion()).isEqualTo(3);
        assertThat(workflow.getPublishedAt()).isNotNull();
        verify(versionMapper).insert(any(WorkflowVersion.class));
    }

    @Test
    void rollbackCopiesTargetVersionAndKeepsHistory() {
        Workflow workflow = published(4, 2, flow("draft").toString());
        WorkflowVersion target = new WorkflowVersion();
        target.setId(30L);
        target.setWorkflowId(5L);
        target.setVersion(2);
        target.setEngineType("langgraph");
        target.setFlowData(objectMapper.valueToTree(flow("v2")).toString());
        when(workflowMapper.selectById(5L)).thenReturn(workflow);
        when(versionMapper.selectOne(any())).thenReturn(target);

        WorkflowDetailVO detail = service.rollback(5L, 2, OWNER);

        assertThat(detail.getVersion()).isEqualTo(5);
        assertThat(workflow.getFlowData()).contains("v2");
        ArgumentCaptor<WorkflowVersion> captor = ArgumentCaptor.forClass(WorkflowVersion.class);
        verify(versionMapper).insert(captor.capture());
        assertThat(captor.getValue().getVersion()).isEqualTo(5);
        assertThat(captor.getValue().getNote()).isEqualTo("回滚自 v2");
        verify(versionMapper, never()).deleteById(any(Long.class));
    }

    @Test
    void flowForRunPrefersPublishedSnapshot() {
        Workflow workflow = published(4, 2, flow("draft").toString());
        WorkflowVersion snapshot = new WorkflowVersion();
        snapshot.setWorkflowId(5L);
        snapshot.setVersion(2);
        snapshot.setFlowData(objectMapper.valueToTree(flow("published")).toString());
        when(versionMapper.selectOne(any())).thenReturn(snapshot);

        WorkflowService.FlowSelection selection = service.flowForRun(workflow, true);

        assertThat(selection.published()).isTrue();
        assertThat(selection.version()).isEqualTo(2);
        assertThat(selection.flow().toString()).contains("published");
    }

    @Test
    void flowForRunFallsBackToDraftWhenSnapshotMissing() {
        Workflow workflow = published(4, 2, objectMapper.valueToTree(flow("draft")).toString());
        when(versionMapper.selectOne(any())).thenReturn(null);

        WorkflowService.FlowSelection selection = service.flowForRun(workflow, true);

        assertThat(selection.published()).isFalse();
        assertThat(selection.version()).isEqualTo(4);
        assertThat(selection.flow().toString()).contains("draft");
    }

    @Test
    void otherUserCannotReadOrPublish() {
        when(workflowMapper.selectById(5L)).thenReturn(published(1, null, "{}"));

        assertThatThrownBy(() -> service.detail(5L, OTHER))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("工作流不存在");
        assertThatThrownBy(() -> service.publish(5L, OTHER))
                .isInstanceOf(BizException.class);
        assertThat(service.detail(5L, ADMIN).getId()).isEqualTo(5L);
    }

    @Test
    void deleteRemovesTriggersAndVersionHistory() {
        Workflow workflow = published(1, null, "{}");
        when(workflowMapper.selectById(5L)).thenReturn(workflow);
        WorkflowTrigger trigger = new WorkflowTrigger();
        trigger.setId(70L);
        trigger.setWorkflowId(5L);
        when(triggerMapper.selectList(any())).thenReturn(List.of(trigger));

        service.delete(5L, OWNER);

        verify(triggerMapper).deleteById(70L);
        verify(events).publishEvent(any(TriggerChangedEvent.class));
        verify(versionMapper).delete(any());
        verify(workflowMapper).deleteById(5L);
    }
}