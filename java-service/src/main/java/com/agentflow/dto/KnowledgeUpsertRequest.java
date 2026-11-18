package com.agentflow.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class KnowledgeUpsertRequest {

    @NotNull(message = "缺少知识库 ID")
    private Long knowledgeBaseId;
    /** 留空时生成 runtime-<时间戳> 标题；相同标题再次写入会覆盖 */
    @Size(max = 255)
    private String title;
    @NotBlank(message = "文档内容不能为空")
    @Size(max = 200_000, message = "文档内容不能超过 200000 字")
    private String content;
}
