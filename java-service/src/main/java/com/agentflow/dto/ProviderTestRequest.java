package com.agentflow.dto;

import lombok.Data;

@Data
public class ProviderTestRequest {

    /** 不传则使用已保存/环境变量中的 Key */
    private String apiKey;
    private String baseUrl;
    private String model;
}
