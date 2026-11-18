package com.agentflow.dto;

import com.agentflow.entity.ApprovalTask;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
public class ApprovalVO {

    private Long id;
    private String runId;
    private Long workflowId;
    private String nodeId;
    private Long userId;
    private String title;
    private String content;
    private String status;
    private String comment;
    private Long decidedBy;
    private LocalDateTime expiresAt;
    private LocalDateTime decidedAt;
    private LocalDateTime createdAt;

    public static ApprovalVO of(ApprovalTask task) {
        return ApprovalVO.builder()
                .id(task.getId())
                .runId(task.getRunId())
                .workflowId(task.getWorkflowId())
                .nodeId(task.getNodeId())
                .userId(task.getUserId())
                .title(task.getTitle())
                .content(task.getContent())
                .status(task.getStatus())
                .comment(task.getComment())
                .decidedBy(task.getDecidedBy())
                .expiresAt(task.getExpiresAt())
                .decidedAt(task.getDecidedAt())
                .createdAt(task.getCreatedAt())
                .build();
    }
}
