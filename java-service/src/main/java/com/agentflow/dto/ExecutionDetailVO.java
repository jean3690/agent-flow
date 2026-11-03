package com.agentflow.dto;

import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

@Data
@Builder
public class ExecutionDetailVO {

    private String runId;
    private Long workflowId;
    private String workflowName;
    private String status;
    private String input;
    private String output;
    private String errorMessage;
    private Long elapsedMs;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
    private List<NodeLogVO> nodes;
}
