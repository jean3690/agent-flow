package com.agentflow.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
@Schema(description = "执行记录概要（列表项）")
public class ExecutionSummaryVO {

    private Long id;
    private String runId;
    private Long workflowId;
    private String workflowName;
    private String status;
    private Integer nodeCount;
    private Integer flowVersion;
    private Integer promptTokens;
    private Integer completionTokens;
    private Integer totalTokens;
    private java.math.BigDecimal costUsd;
    private Long elapsedMs;
    private String errorMessage;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
}
