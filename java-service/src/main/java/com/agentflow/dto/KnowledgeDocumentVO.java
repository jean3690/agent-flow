package com.agentflow.dto;

import com.agentflow.entity.KnowledgeDocument;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
public class KnowledgeDocumentVO {

    private Long id;
    private String title;
    private String sourceType;
    private Integer charCount;
    private String status;
    private Integer chunkCount;
    private String errorMessage;
    private LocalDateTime createdAt;

    public static KnowledgeDocumentVO of(KnowledgeDocument document) {
        return KnowledgeDocumentVO.builder()
                .id(document.getId())
                .title(document.getTitle())
                .sourceType(document.getSourceType())
                .charCount(document.getCharCount())
                .status(document.getStatus())
                .chunkCount(document.getChunkCount())
                .errorMessage(document.getErrorMessage())
                .createdAt(document.getCreatedAt())
                .build();
    }
}
