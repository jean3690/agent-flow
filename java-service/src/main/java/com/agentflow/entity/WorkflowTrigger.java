package com.agentflow.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/** 工作流触发器：定时（CRON）或 Webhook。 */
@Data
@TableName("workflow_trigger")
public class WorkflowTrigger {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long workflowId;
    private Long userId;
    private String name;
    /** CRON | WEBHOOK */
    private String type;
    private Integer enabled;
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String cronExpression;
    private String timezone;
    /** Webhook 路径中的一次性随机令牌 */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String webhookToken;
    /** 触发时使用的静态输入（JSON 对象字符串） */
    private String inputData;
    private String lastRunId;
    private String lastStatus;
    private LocalDateTime lastRunAt;
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private LocalDateTime nextRunAt;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
