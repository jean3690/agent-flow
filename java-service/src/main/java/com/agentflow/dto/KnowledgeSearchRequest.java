package com.agentflow.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class KnowledgeSearchRequest {

    /** 内部检索接口使用；公开接口从路径取知识库 id。 */
    private Long knowledgeBaseId;

    @NotBlank(message = "检索内容不能为空")
    private String query;
    private Integer topK = 4;
}
