package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.dto.ApprovalCreateRequest;
import com.agentflow.dto.ApprovalDecisionRequest;
import com.agentflow.dto.ApprovalVO;
import com.agentflow.entity.ApprovalTask;
import com.agentflow.mapper.ApprovalTaskMapper;
import com.agentflow.security.CurrentUser;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ApprovalServiceTest {

    @Mock private ApprovalTaskMapper taskMapper;

    private ApprovalService service;

    @BeforeEach
    void setUp() {
        service = new ApprovalService(taskMapper);
    }

    @Test
    void createStoresPendingTask() {
        doAnswer(invocation -> {
            ApprovalTask task = invocation.getArgument(0);
            task.setId(11L);
            return 1;
        }).when(taskMapper).insert(any(ApprovalTask.class));

        ApprovalVO result = service.create(request());

        ArgumentCaptor<ApprovalTask> captor = ArgumentCaptor.forClass(ApprovalTask.class);
        verify(taskMapper).insert(captor.capture());
        ApprovalTask saved = captor.getValue();
        assertThat(saved.getStatus()).isEqualTo("PENDING");
        assertThat(saved.getTitle()).isEqualTo("发布审批");
        assertThat(saved.getExpiresAt()).isAfter(LocalDateTime.now());
        assertThat(result.getId()).isEqualTo(11L);
        assertThat(result.getStatus()).isEqualTo("PENDING");
    }

    @Test
    void ownerCanApproveTask() {
        ApprovalTask task = pending(5L, 7L, LocalDateTime.now().plusMinutes(5));
        when(taskMapper.selectById(5L)).thenReturn(task);

        ApprovalVO result = service.decide(5L, decision(true, "同意发布"), new CurrentUser(7L, "owner", "USER"));

        assertThat(result.getStatus()).isEqualTo("APPROVED");
        assertThat(result.getComment()).isEqualTo("同意发布");
        assertThat(result.getDecidedBy()).isEqualTo(7L);
        verify(taskMapper).updateById(task);
    }

    @Test
    void otherUserCannotDecide() {
        when(taskMapper.selectById(5L)).thenReturn(pending(5L, 7L, LocalDateTime.now().plusMinutes(5)));

        assertThatThrownBy(() -> service.decide(5L, decision(false, "no"), new CurrentUser(9L, "other", "USER")))
                .isInstanceOf(BizException.class);
    }

    @Test
    void adminCanDecideOthersTask() {
        when(taskMapper.selectById(5L)).thenReturn(pending(5L, 7L, LocalDateTime.now().plusMinutes(5)));

        ApprovalVO result = service.decide(5L, decision(false, "风险太高"), new CurrentUser(1L, "admin", "ADMIN"));

        assertThat(result.getStatus()).isEqualTo("REJECTED");
        assertThat(result.getComment()).isEqualTo("风险太高");
    }

    @Test
    void expiredTaskCannotBeApproved() {
        when(taskMapper.selectById(5L)).thenReturn(pending(5L, 7L, LocalDateTime.now().minusMinutes(1)));

        assertThatThrownBy(() -> service.decide(5L, decision(true, ""), new CurrentUser(7L, "owner", "USER")))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("已过期");
        verify(taskMapper).updateById(any(ApprovalTask.class));
    }

    private ApprovalCreateRequest request() {
        ApprovalCreateRequest request = new ApprovalCreateRequest();
        request.setRunId("run-1");
        request.setWorkflowId(2L);
        request.setNodeId("approval");
        request.setUserId(7L);
        request.setTitle("发布审批");
        request.setContent("准备发布 v1");
        request.setExpiresInSeconds(120);
        return request;
    }

    private ApprovalDecisionRequest decision(boolean approved, String comment) {
        ApprovalDecisionRequest request = new ApprovalDecisionRequest();
        request.setApproved(approved);
        request.setComment(comment);
        return request;
    }

    private ApprovalTask pending(Long id, Long userId, LocalDateTime expiresAt) {
        ApprovalTask task = new ApprovalTask();
        task.setId(id);
        task.setUserId(userId);
        task.setRunId("run-1");
        task.setNodeId("approval");
        task.setTitle("发布审批");
        task.setStatus("PENDING");
        task.setExpiresAt(expiresAt);
        return task;
    }
}
