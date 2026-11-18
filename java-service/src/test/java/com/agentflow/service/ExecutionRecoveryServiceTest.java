package com.agentflow.service;

import com.agentflow.entity.ExecutionNodeLog;
import com.agentflow.entity.ExecutionRecord;
import com.agentflow.mapper.ExecutionNodeLogMapper;
import com.agentflow.mapper.ExecutionRecordMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ExecutionRecoveryServiceTest {

    @Mock private ExecutionRecordMapper records;
    @Mock private ExecutionNodeLogMapper nodeLogs;

    @Test
    void staleRunningRecordIsClosedAsFailed() {
        ExecutionRecord stale = new ExecutionRecord();
        stale.setId(11L);
        stale.setRunId("run-stale");
        stale.setWorkflowId(3L);
        stale.setStatus("RUNNING");
        stale.setStartedAt(LocalDateTime.now().minusMinutes(5));
        when(records.selectList(any())).thenReturn(List.of(stale));

        ExecutionNodeLog runningNode = new ExecutionNodeLog();
        runningNode.setId(21L);
        runningNode.setRunId("run-stale");
        runningNode.setStatus("RUNNING");
        runningNode.setStartedAt(LocalDateTime.now().minusMinutes(4));
        when(nodeLogs.selectList(any())).thenReturn(List.of(runningNode));

        ExecutionRecoveryService service = new ExecutionRecoveryService(records, nodeLogs);
        int recovered = service.recoverStaleExecutions();

        assertThat(recovered).isEqualTo(1);
        ArgumentCaptor<ExecutionRecord> recordCaptor = ArgumentCaptor.forClass(ExecutionRecord.class);
        verify(records).updateById(recordCaptor.capture());
        ExecutionRecord saved = recordCaptor.getValue();
        assertThat(saved.getStatus()).isEqualTo("FAILED");
        assertThat(saved.getErrorMessage()).isEqualTo(ExecutionRecoveryService.INTERRUPTED_MESSAGE);
        assertThat(saved.getFinishedAt()).isNotNull();
        assertThat(saved.getElapsedMs()).isGreaterThan(0L);

        ArgumentCaptor<ExecutionNodeLog> nodeCaptor = ArgumentCaptor.forClass(ExecutionNodeLog.class);
        verify(nodeLogs).updateById(nodeCaptor.capture());
        assertThat(nodeCaptor.getValue().getStatus()).isEqualTo("FAILED");
        assertThat(nodeCaptor.getValue().getFinishedAt()).isNotNull();
    }

    @Test
    void noStaleRecordSkipsWrites() {
        when(records.selectList(any())).thenReturn(List.of());

        ExecutionRecoveryService service = new ExecutionRecoveryService(records, nodeLogs);
        assertThat(service.recoverStaleExecutions()).isZero();
        verify(records, never()).updateById(any(ExecutionRecord.class));
        verify(nodeLogs, never()).updateById(any(ExecutionNodeLog.class));
    }
}