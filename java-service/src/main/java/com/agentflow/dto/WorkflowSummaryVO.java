package com.agentflow.dto;

import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
public class WorkflowSummaryVO {

    private Long id;
    private String name;
    private String description;
    private String engineType;
    private Integer status;
    private Integer version;
    private Integer nodeCount;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
