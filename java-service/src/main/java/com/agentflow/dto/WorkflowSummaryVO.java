package com.agentflow.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
@Schema(description = "工作流概要（列表项）")
public class WorkflowSummaryVO {

    private Long id;
    private String name;
    private String description;
    private String engineType;
    private Integer status;
    private Integer version;
    private Integer publishedVersion;
    private Integer nodeCount;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
