package com.agentflow.dto;

import lombok.Data;

import java.util.HashMap;
import java.util.Map;

@Data
public class ExecuteRequest {

    private Map<String, Object> input = new HashMap<>();
    private Integer timeoutMs;
    private Boolean mock;
    /** 断点续跑：传入上次失败的 runId，已成功节点的输出会被复用 */
    private String resumeRunId;
}
