package com.agentflow.dto;

import com.fasterxml.jackson.databind.JsonNode;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
public class WorkflowDetailVO {

    private Long id;
    private String name;
    private String description;
    private String engineType;
    private Integer status;
    private Integer version;
    private JsonNode flow;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
