package com.agentflow.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class KnowledgeBaseRequest {

    @NotBlank(message = "知识库名称不能为空")
    private String name;
    private String description = "";
    private String embeddingProvider = "mock";
    private String embeddingModel = "text-embedding-3-small";
    private Integer chunkSize = 600;
    private Integer chunkOverlap = 80;
}
