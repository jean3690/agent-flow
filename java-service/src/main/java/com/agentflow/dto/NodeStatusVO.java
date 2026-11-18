package com.agentflow.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
@Schema(description = "单个节点的执行状态")
public class NodeStatusVO {

    @Schema(description = "节点 id")
    private String nodeId;

    @Schema(description = "节点类型")
    private String nodeType;

    @Schema(description = "节点名称")
    private String nodeName;

    @Schema(description = "状态：RUNNING / SUCCESS / FAILED")
    private String status;

    @Schema(description = "节点输出")
    private Object output;

    @Schema(description = "节点耗时（毫秒）")
    private Long elapsedMs;

    @Schema(description = "失败时的错误信息")
    private String errorMessage;
}
