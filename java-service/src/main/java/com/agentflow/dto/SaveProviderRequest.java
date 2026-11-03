package com.agentflow.dto;

import lombok.Data;

@Data
public class SaveProviderRequest {

    /** 留空表示不修改已保存的 Key */
    private String apiKey;
    /** 留空表示清空自定义地址，回退到服务商默认地址 */
    private String baseUrl;
}
