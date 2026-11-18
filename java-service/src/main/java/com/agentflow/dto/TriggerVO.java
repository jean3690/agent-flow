package com.agentflow.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;

@Data
@Builder
@Schema(description = "触发器信息")
public class TriggerVO {

    private Long id;
    private Long workflowId;
    private String name;
    private String type;
    private Boolean enabled;
    private String cronExpression;
    private String timezone;
    @Schema(description = "Webhook 相对路径，拼接站点地址即可调用")
    private String webhookPath;
    private Map<String, Object> input;
    private String lastRunId;
    private String lastStatus;
    private LocalDateTime lastRunAt;
    private LocalDateTime nextRunAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
