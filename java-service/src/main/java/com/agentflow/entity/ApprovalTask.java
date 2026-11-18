package com.agentflow.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/** 人工审批任务：由 human_approval 节点创建，等待用户或管理员处理。 */
@Data
@TableName("approval_task")
public class ApprovalTask {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String runId;
    private Long workflowId;
    private String nodeId;
    private Long userId;
    private String title;
    private String content;
    /** PENDING | APPROVED | REJECTED | EXPIRED */
    private String status;
    @TableField("decision_comment")
    private String comment;
    private Long decidedBy;
    private LocalDateTime expiresAt;
    private LocalDateTime decidedAt;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
