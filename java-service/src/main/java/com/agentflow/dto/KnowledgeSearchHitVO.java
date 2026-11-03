package com.agentflow.dto;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class KnowledgeSearchHitVO {

    private Long chunkId;
    private Long documentId;
    private String title;
    private String content;
    private double score;
}
