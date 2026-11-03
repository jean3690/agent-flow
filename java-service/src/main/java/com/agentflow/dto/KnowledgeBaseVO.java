package com.agentflow.dto;

import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
public class KnowledgeBaseVO {

    private Long id;
    private String name;
    private String description;
    private String embeddingProvider;
    private String embeddingModel;
    private Integer chunkSize;
    private Integer chunkOverlap;
    private long documentCount;
    private long chunkCount;
    private LocalDateTime createdAt;
}
