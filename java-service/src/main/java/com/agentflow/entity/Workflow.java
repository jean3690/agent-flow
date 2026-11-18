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

@Data
@TableName("workflow")
public class Workflow {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String name;
    private String description;
    private String engineType;
    private String flowData;
    private Integer status;
    private Integer version;
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private Integer publishedVersion;

    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private LocalDateTime publishedAt;
    private Long userId;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
