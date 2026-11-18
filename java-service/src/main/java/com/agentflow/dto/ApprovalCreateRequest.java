package com.agentflow.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class ApprovalCreateRequest {

    @NotBlank
    @Size(max = 64)
    private String runId;
    private Long workflowId;
    @NotBlank
    @Size(max = 64)
    private String nodeId;
    private Long userId;
    @NotBlank
    @Size(max = 255)
    private String title;
    @Size(max = 20_000)
    private String content;
    @Min(30)
    @Max(1800)
    private Integer expiresInSeconds = 300;
}
