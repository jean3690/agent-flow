package com.agentflow.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("execution_node_log")
public class ExecutionNodeLog {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String runId;
    private Long workflowId;
    private String nodeId;
    private String nodeType;
    private String nodeName;
    private Integer seq;
    private String status;
    private String inputData;
    private String outputData;
    private String errorMessage;
    private Long elapsedMs;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
}
