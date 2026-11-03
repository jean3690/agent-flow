package com.agentflow.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("knowledge_chunk")
public class KnowledgeChunk {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long knowledgeBaseId;
    private Long documentId;
    private Integer chunkIndex;
    private String content;
    private Integer charCount;
    /** JSON 数组；mock 模式下为空 */
    private String embedding;
    private String embeddingModel;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
