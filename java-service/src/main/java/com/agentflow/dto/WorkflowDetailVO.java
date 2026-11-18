package com.agentflow.dto;

import com.fasterxml.jackson.databind.JsonNode;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
@Schema(description = "工作流详情")
public class WorkflowDetailVO {

    private Long id;
    private String name;
    private String description;
    private String engineType;
    private Integer status;
    private Integer version;
    private Integer publishedVersion;
    private LocalDateTime publishedAt;
    private JsonNode flow;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
