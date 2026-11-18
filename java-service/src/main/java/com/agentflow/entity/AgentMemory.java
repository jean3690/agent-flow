package com.agentflow.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/** Agent 长期记忆：scope 决定召回边界（workflow / user / global）。 */
@Data
@TableName("agent_memory")
public class AgentMemory {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long workflowId;
    private Long userId;
    private String scope;
    private String memoryType;
    private String content;
    /** 逗号分隔的标签，写入时去重并限制数量 */
    private String tags;
    private String sourceNodeId;
    /** 向量 JSON 数组；未配置 embedding 时为空 */
    private String embedding;
    private String embeddingModel;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
