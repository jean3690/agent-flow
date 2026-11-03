package com.agentflow.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("execution_record")
public class ExecutionRecord {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String runId;
    private Long workflowId;
    private String workflowName;
    private Long userId;
    private String status;
    private String inputData;
    private String outputData;
    private String errorMessage;
    private Integer nodeCount;
    private Long elapsedMs;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
