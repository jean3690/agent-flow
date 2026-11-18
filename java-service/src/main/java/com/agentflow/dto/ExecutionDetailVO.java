package com.agentflow.dto;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

@Data
@Builder
public class ExecutionDetailVO {

    private String runId;
    private Long workflowId;
    private String workflowName;
    private String status;
    private Integer flowVersion;
    private Integer promptTokens;
    private Integer completionTokens;
    private Integer totalTokens;
    private BigDecimal costUsd;
    private String input;
    private String output;
    private String errorMessage;
    private Long elapsedMs;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
    private List<NodeLogVO> nodes;
}
