package com.agentflow.dto;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class KnowledgeChunkVO {

    private Long id;
    private Integer chunkIndex;
    private String content;
    private Integer charCount;
}
