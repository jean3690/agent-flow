package com.agentflow.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

@Data
@Builder
@Schema(description = "同步执行的汇总结果（POST /api/workflows/{id}/run 返回）")
public class RunResultVO {

    @Schema(description = "本次执行的 runId")
    private String runId;

    @Schema(description = "最终状态：SUCCESS / FAILED / CANCELED")
    private String status;

    @Schema(description = "工作流最终输出（各 output 节点的聚合结果）")
    private Object outputs;

    @Schema(description = "每个节点的执行状态明细")
    private List<NodeStatusVO> nodeStatus;

    @Schema(description = "提示词 token 数")
    private Integer promptTokens;

    @Schema(description = "补全 token 数")
    private Integer completionTokens;

    @Schema(description = "总 token 数")
    private Integer totalTokens;

    @Schema(description = "估算成本（美元）")
    private BigDecimal costUsd;

    @Schema(description = "总耗时（毫秒）")
    private Long elapsedMs;

    @Schema(description = "失败时的错误信息")
    private String errorMessage;
}
