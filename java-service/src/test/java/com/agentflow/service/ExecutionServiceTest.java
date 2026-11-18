package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.ExecuteRequest;
import com.agentflow.dto.RunResultVO;
import com.agentflow.entity.ExecutionNodeLog;
import com.agentflow.entity.ExecutionRecord;
import com.agentflow.entity.Workflow;
import com.agentflow.mapper.ExecutionNodeLogMapper;
import com.agentflow.mapper.ExecutionRecordMapper;
import com.agentflow.security.CurrentUser;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.task.TaskRejectedException;
import org.springframework.http.HttpStatus;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class ExecutionServiceTest {
    private static final CurrentUser OWNER = new CurrentUser(1L, "owner", "USER");
    private static final CurrentUser OTHER = new CurrentUser(2L, "other", "USER");
    private static final CurrentUser ADMIN = new CurrentUser(3L, "admin", "ADMIN");

    // All mocks use the subclass maker configured in
    // src/test/resources/mockito-extensions/org.mockito.plugins.MockMaker.
    // Mixing makers in one JVM breaks MockUtil.getMockHandler() on JDK 23+.
    @Mock private AiClient aiClient;
    @Mock private WorkflowService workflowService;
    @Mock private LlmProviderService providers;
    @Mock private McpServerService mcpServers;
    @Mock private ExecutionRecordMapper records;
    @Mock private ExecutionNodeLogMapper nodeLogs;
    @Mock private ThreadPoolTaskExecutor executor;
    @Mock private ModelPricingService pricing;

    private final ObjectMapper json = new ObjectMapper();
    private SimpleMeterRegistry metrics;
    private ExecutionService service;
    private Workflow workflow;
    private JsonNode flow;

    @BeforeEach
    void setUp() throws Exception {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), "test"), ExecutionRecord.class);
        metrics = new SimpleMeterRegistry();
        service = new ExecutionService(aiClient, workflowService, providers, mcpServers, records, nodeLogs, json, executor, pricing, metrics);
        workflow = new Workflow();
        workflow.setId(5L);
        workflow.setUserId(OWNER.id());
        workflow.setName("test flow");
        flow = json.readTree("""
                {"nodes":[{"id":"in","type":"input"},{"id":"out","type":"output"}],
                 "edges":[{"source":"in","target":"out"}]}
                """);
    }

    @ParameterizedTest
    @ValueSource(strings = {"detail", "cancel", "delete"})
    void hidesOtherUsersRecords(String operation) {
        when(records.selectOne(any())).thenReturn(record("SUCCESS"));
        assertThatThrownBy(() -> {
            switch (operation) {
                case "detail" -> service.detail("r1", OTHER);
                case "cancel" -> service.cancel("r1", OTHER);
                default -> service.delete("r1", OTHER);
            }
        }).isInstanceOfSatisfying(BizException.class, ex -> assertThat(ex.getStatus()).isEqualTo(HttpStatus.NOT_FOUND));
        verifyNoInteractions(aiClient, nodeLogs);
        verify(records, never()).deleteById(any(Long.class));
    }

    @Test
    void ownerAndAdminCanReadRecordEvenAfterWorkflowDeletion() {
        when(records.selectOne(any())).thenReturn(record("SUCCESS"));
        when(nodeLogs.selectList(any())).thenReturn(List.of());
        assertThat(service.detail("r1", OWNER).getStatus()).isEqualTo("SUCCESS");
        assertThat(service.detail("r1", ADMIN).getStatus()).isEqualTo("SUCCESS");
        verifyNoInteractions(workflowService);
    }

    @Test
    void preventsDeletingRunningExecution() {
        when(records.selectOne(any())).thenReturn(record("RUNNING"));
        assertThatThrownBy(() -> service.delete("r1", OWNER))
                .isInstanceOfSatisfying(BizException.class, ex -> assertThat(ex.getStatus()).isEqualTo(HttpStatus.CONFLICT));
        verifyNoInteractions(nodeLogs);
    }

    @Test
    void filtersExecutionListByOwnerInDatabase() {
        when(records.selectPage(any(), any())).thenAnswer(call -> {
            LambdaQueryWrapper<ExecutionRecord> query = call.getArgument(1);
            assertThat(query.getSqlSegment()).contains("user_id");
            assertThat(query.getParamNameValuePairs()).containsValue(OWNER.id());
            return new Page<ExecutionRecord>(1, 10);
        });
        assertThat(service.page(1, 10, null, null, OWNER).getTotal()).isZero();
    }

    @Test
    void workflowExecutionListChecksWorkflowOwnershipBeforeQuerying() {
        when(workflowService.getEntity(5L, OTHER)).thenThrow(BizException.notFound("工作流不存在"));
        assertThatThrownBy(() -> service.page(1, 10, 5L, null, OTHER)).isInstanceOf(BizException.class);
        verifyNoInteractions(records);
    }

    @ParameterizedTest
    @ValueSource(strings = {"stream", "sync", "submit"})
    void payloadFailureDoesNotLeaveRunningRecord(String entry) {
        stubFlow(entry);
        when(providers.credentialsForRun()).thenThrow(new BizException("凭据解密失败"));
        assertThatThrownBy(() -> start(entry, new ExecuteRequest())).hasMessageContaining("凭据解密失败");
        verify(records, never()).insert(any(ExecutionRecord.class));
        verifyNoInteractions(executor, aiClient);
    }

    @ParameterizedTest
    @ValueSource(strings = {"stream", "submit"})
    void rejectedTaskIsFailedAndRemovedFromRunningRegistry(String entry) {
        stubFlow(entry);
        doThrow(new TaskRejectedException("full")).when(executor).execute(any(Runnable.class));
        assertThatThrownBy(() -> start(entry, new ExecuteRequest()))
                .isInstanceOfSatisfying(BizException.class, ex -> assertThat(ex.getStatus()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE));
        ArgumentCaptor<ExecutionRecord> saved = ArgumentCaptor.forClass(ExecutionRecord.class);
        verify(records).updateById(saved.capture());
        assertThat(saved.getValue().getStatus()).isEqualTo("FAILED");
        assertThat(saved.getValue().getFinishedAt()).isNotNull();
        assertThat(metrics.get("agentflow.executions.running").gauge().value()).isZero();
        verifyNoInteractions(aiClient);
    }

    @ParameterizedTest
    @ValueSource(strings = {"stream", "submit"})
    void canceledQueuedTaskNeverStartsUpstream(String entry) {
        stubFlow(entry);
        AtomicReference<ExecutionRecord> record = new AtomicReference<>();
        doAnswer(call -> { record.set(call.getArgument(0)); return 1; }).when(records).insert(any(ExecutionRecord.class));
        start(entry, new ExecuteRequest());
        when(records.selectOne(any())).thenAnswer(call -> record.get());
        service.cancel(record.get().getRunId(), OWNER);
        ArgumentCaptor<Runnable> task = ArgumentCaptor.forClass(Runnable.class);
        verify(executor).execute(task.capture());
        task.getValue().run();
        assertThat(record.get().getStatus()).isEqualTo("CANCELED");
        assertThat(metrics.get("agentflow.executions.running").gauge().value()).isZero();
        verify(aiClient, never()).openExecution(anyString());
    }

    @Test
    void refusesCrossOwnerSubflowBeforeCreatingRecord() throws Exception {
        flow = json.readTree("""
                {"nodes":[{"id":"sub","type":"subflow","config":{"workflowId":9}}],"edges":[]}
                """);
        stubFlow("sync");
        when(workflowService.getEntity(9L, OWNER)).thenThrow(BizException.notFound("工作流不存在: 9"));
        assertThatThrownBy(() -> service.runSync(5L, new ExecuteRequest(), OWNER)).hasMessageContaining("工作流不存在");
        verify(records, never()).insert(any(ExecutionRecord.class));
        verifyNoInteractions(aiClient);
    }

    @Test
    void brokenUpstreamFinalizesBothRunAndStartedNodes() {
        stubFlow("sync");
        when(aiClient.openExecution(anyString())).thenReturn(stream("event: node_started\ndata: {\"nodeId\":\"in\",\"nodeType\":\"input\"}\n\n"));
        RunResultVO result = service.runSync(5L, new ExecuteRequest(), OWNER);
        assertThat(result.getStatus()).isEqualTo("FAILED");
        assertThat(result.getErrorMessage()).isEqualTo("执行中断");
        assertThat(result.getNodeStatus()).singleElement().satisfies(node -> assertThat(node.getStatus()).isEqualTo("FAILED"));
        ArgumentCaptor<ExecutionNodeLog> node = ArgumentCaptor.forClass(ExecutionNodeLog.class);
        verify(nodeLogs).insert(node.capture());
        assertThat(node.getValue().getFinishedAt()).isNotNull();
        assertThat(metrics.get("agentflow.executions.running").gauge().value()).isZero();
    }

    @Test
    void syncRunConsumesFinalEventAndClosesUpstream() {
        stubFlow("sync");
        AtomicReference<Boolean> closed = new AtomicReference<>(false);
        ByteArrayInputStream input = new ByteArrayInputStream("event: run_finished\r\ndata: {\"output\":\"你好\",\"elapsedMs\":12}".getBytes(StandardCharsets.UTF_8)) {
            @Override public void close() throws IOException { closed.set(true); super.close(); }
        };
        when(aiClient.openExecution(anyString())).thenReturn(input);
        RunResultVO result = service.runSync(5L, new ExecuteRequest(), OWNER);
        assertThat(result.getStatus()).isEqualTo("SUCCESS");
        assertThat(result.getOutputs()).isEqualTo("你好");
        assertThat(result.getElapsedMs()).isEqualTo(12L);
        assertThat(closed.get()).isTrue();
    }

    private void stubFlow(String entry) {
        if ("submit".equals(entry)) when(workflowService.getEntity(5L)).thenReturn(workflow);
        else when(workflowService.getEntity(5L, OWNER)).thenReturn(workflow);
        when(workflowService.flowForRun(workflow, false)).thenReturn(new WorkflowService.FlowSelection(flow, 1, false));
    }

    private void start(String entry, ExecuteRequest request) {
        switch (entry) {
            case "stream" -> service.execute(5L, request, OWNER);
            case "sync" -> service.runSync(5L, request, OWNER);
            default -> service.submit(5L, request, OWNER.id(), (Consumer<RunResultVO>) null);
        }
    }

    private ExecutionRecord record(String status) {
        ExecutionRecord record = new ExecutionRecord();
        record.setId(1L);
        record.setRunId("r1");
        record.setWorkflowId(5L);
        record.setUserId(OWNER.id());
        record.setStatus(status);
        record.setStartedAt(LocalDateTime.now().minusSeconds(1));
        return record;
    }

    private ByteArrayInputStream stream(String text) {
        return new ByteArrayInputStream(text.getBytes(StandardCharsets.UTF_8));
    }
}
