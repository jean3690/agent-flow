package com.agentflow.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.List;

@Data
public class MemoryWriteRequest {

    private Long workflowId;
    private Long userId;
    private String scope = "workflow";
    @Size(max = 32)
    private String memoryType = "fact";
    @NotBlank(message = "记忆内容不能为空")
    @Size(max = 8000, message = "记忆内容不能超过 8000 字")
    private String content;
    /** 逗号分隔或数组均可，服务端统一去重 */
    private List<String> tags;
    @Size(max = 64)
    private String sourceNodeId;
    /** 生成向量用的服务商；mock 或留空时退化为词法匹配 */
    private String provider;
    private String model;
}
