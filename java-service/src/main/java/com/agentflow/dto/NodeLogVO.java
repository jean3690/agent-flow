package com.agentflow.dto;

import com.agentflow.entity.ExecutionNodeLog;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Builder
public class NodeLogVO {

    private String nodeId;
    private String nodeType;
    private String nodeName;
    private Integer seq;
    private String status;
    private String output;
    private String errorMessage;
    private Long elapsedMs;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;

    public static NodeLogVO from(ExecutionNodeLog log) {
        return NodeLogVO.builder()
                .nodeId(log.getNodeId())
                .nodeType(log.getNodeType())
                .nodeName(log.getNodeName())
                .seq(log.getSeq())
                .status(log.getStatus())
                .output(log.getOutputData())
                .errorMessage(log.getErrorMessage())
                .elapsedMs(log.getElapsedMs())
                .startedAt(log.getStartedAt())
                .finishedAt(log.getFinishedAt())
                .build();
    }
}
