package com.agentflow.dto;

import com.fasterxml.jackson.databind.JsonNode;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
@Schema(description = "工作流版本快照")
public class WorkflowVersionVO {

    private Long id;
    private Long workflowId;
    private Integer version;
    private String name;
    private String description;
    private String engineType;
    private String note;
    private Long createdBy;
    private LocalDateTime createdAt;
    @Schema(description = "是否为当前发布版本")
    private Boolean published;
    @Schema(description = "是否为当前最新版本")
    private Boolean current;
    @Schema(description = "版本详情接口才返回完整 flow")
    private JsonNode flow;
}
