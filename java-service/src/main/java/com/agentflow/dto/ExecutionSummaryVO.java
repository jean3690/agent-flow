package com.agentflow.dto;

import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
public class ExecutionSummaryVO {

    private Long id;
    private String runId;
    private Long workflowId;
    private String workflowName;
    private String status;
    private Integer nodeCount;
    private Long elapsedMs;
    private String errorMessage;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
}
