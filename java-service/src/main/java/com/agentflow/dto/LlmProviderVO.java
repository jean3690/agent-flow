package com.agentflow.dto;

import lombok.Builder;
import lombok.Data;

import java.util.List;

@Data
@Builder
public class LlmProviderVO {

    private String provider;
    private String label;
    private String defaultModel;
    private List<String> models;
    private boolean supportsTts;
    private boolean configured;
    /** DB: 前端保存；ENV: 环境变量；NONE: 未配置 */
    private String source;
    private String baseUrl;
    private String apiKeyMasked;
}
