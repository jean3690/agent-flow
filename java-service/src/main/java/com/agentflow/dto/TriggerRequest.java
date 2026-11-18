package com.agentflow.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.util.LinkedHashMap;
import java.util.Map;

@Data
@Schema(description = "创建/更新触发器请求")
public class TriggerRequest {

    @NotBlank
    @Schema(description = "触发器名称", example = "每天 9 点生成日报")
    private String name;

    @NotBlank
    @Schema(description = "触发类型：CRON 或 WEBHOOK", example = "CRON")
    private String type;

    @Schema(description = "CRON 表达式，支持 5 段（分 时 日 月 周）或 6 段（秒 分 时 日 月 周）", example = "0 9 * * *")
    private String cronExpression;

    @Schema(description = "时区，默认 Asia/Shanghai", example = "Asia/Shanghai")
    private String timezone;

    @Schema(description = "每次触发时注入到工作流 input 的静态参数")
    private Map<String, Object> input = new LinkedHashMap<>();

    @Schema(description = "是否启用，默认 true")
    private Boolean enabled;
}
