package com.agentflow.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/** 工作流不可变版本快照。 */
@Data
@TableName("workflow_version")
public class WorkflowVersion {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long workflowId;
    private Integer version;
    private String name;
    private String description;
    private String engineType;
    private String flowData;
    private String note;
    private Long createdBy;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
