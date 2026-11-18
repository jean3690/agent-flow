package com.agentflow.service;

import com.agentflow.entity.Workflow;
import com.agentflow.entity.WorkflowTrigger;
import com.agentflow.mapper.WorkflowMapper;
import com.agentflow.mapper.WorkflowTriggerMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.context.ApplicationEventPublisher;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/** 多实例部署时同一个 CRON 触发点只允许一个实例派发。 */
@ExtendWith(MockitoExtension.class)
class TriggerCronDispatchTest {

    @Mock private WorkflowTriggerMapper triggerMapper;
    @Mock private WorkflowMapper workflowMapper;
    @Mock private ExecutionService executionService;
    @Mock private SchedulerLockService schedulerLock;
    @Mock private ApplicationEventPublisher events;

    private TriggerService service() {
        return new TriggerService(triggerMapper, workflowMapper, executionService,
                schedulerLock, new ObjectMapper(), events);
    }

    private WorkflowTrigger cronTrigger() {
        WorkflowTrigger trigger = new WorkflowTrigger();
        trigger.setId(7L);
        trigger.setWorkflowId(3L);
        trigger.setUserId(1L);
        trigger.setType("CRON");
        trigger.setEnabled(1);
        return trigger;
    }

    @Test
    void dispatchIsSkippedWhenAnotherInstanceHoldsTheLease() {
        when(triggerMapper.selectById(7L)).thenReturn(cronTrigger());
        when(schedulerLock.tryAcquire(eq("cron:7"), any())).thenReturn(false);

        service().fireCron(7L);

        verify(schedulerLock).tryAcquire(eq("cron:7"), any());
        verifyNoInteractions(executionService);
    }

    @Test
    void dispatchRunsWhenLeaseIsAcquired() {
        when(triggerMapper.selectById(7L)).thenReturn(cronTrigger());
        when(schedulerLock.tryAcquire(eq("cron:7"), any())).thenReturn(true);
        when(workflowMapper.selectById(3L)).thenReturn(new Workflow());
        when(executionService.submit(eq(3L), any(), eq(1L), eq(true), any())).thenReturn("run-1");

        service().fireCron(7L);

        verify(executionService).submit(eq(3L), any(), eq(1L), eq(true), any());
    }
}
