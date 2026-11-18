package com.agentflow.dto;

import com.agentflow.entity.AgentMemory;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

@Data
@Builder
public class MemoryVO {

    private Long id;
    private Long workflowId;
    private Long userId;
    private String scope;
    private String memoryType;
    private String content;
    private List<String> tags;
    private String sourceNodeId;
    private double score;
    private LocalDateTime createdAt;

    public static MemoryVO of(AgentMemory memory, List<String> tags) {
        return MemoryVO.builder()
                .id(memory.getId())
                .workflowId(memory.getWorkflowId())
                .userId(memory.getUserId())
                .scope(memory.getScope())
                .memoryType(memory.getMemoryType())
                .content(memory.getContent())
                .tags(tags)
                .sourceNodeId(memory.getSourceNodeId())
                .createdAt(memory.getCreatedAt())
                .build();
    }
}
