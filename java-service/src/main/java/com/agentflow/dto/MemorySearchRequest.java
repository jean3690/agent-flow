package com.agentflow.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.util.List;

@Data
public class MemorySearchRequest {

    private Long workflowId;
    private Long userId;
    private String scope = "workflow";
    @NotBlank(message = "召回语句不能为空")
    private String query;
    private List<String> tags;
    @Min(1)
    @Max(20)
    private Integer topK = 5;
    private String provider;
    private String model;
}
