package com.agentflow.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
@Schema(description = "Webhook 触发受理结果")
public class WebhookResultVO {

    private Long triggerId;
    private String runId;
    private String status;
}
