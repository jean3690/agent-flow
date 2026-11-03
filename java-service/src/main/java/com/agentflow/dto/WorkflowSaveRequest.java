package com.agentflow.dto;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
public class WorkflowSaveRequest {

    @NotBlank(message = "不能为空")
    private String name;

    private String description;
    private String engineType = "langgraph";
    private Integer status = 1;

    @NotNull(message = "不能为空")
    private JsonNode flow;
}
