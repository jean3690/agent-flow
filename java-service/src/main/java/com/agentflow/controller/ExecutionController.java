package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.common.PageResult;
import com.agentflow.dto.ExecutionDetailVO;
import com.agentflow.dto.ExecutionSummaryVO;
import com.agentflow.service.ExecutionService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/executions")
@RequiredArgsConstructor
public class ExecutionController {

    private final ExecutionService executionService;

    @GetMapping
    public ApiResponse<PageResult<ExecutionSummaryVO>> page(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) Long workflowId,
            @RequestParam(required = false) String status) {
        return ApiResponse.ok(executionService.page(page, size, workflowId, status));
    }

    @PostMapping("/{runId}/cancel")
    public ApiResponse<Void> cancel(@PathVariable String runId) {
        executionService.cancel(runId);
        return ApiResponse.ok();
    }

    @DeleteMapping("/{runId}")
    public ApiResponse<Void> delete(@PathVariable String runId) {
        executionService.delete(runId);
        return ApiResponse.ok();
    }

    @GetMapping("/{runId}")
    public ApiResponse<ExecutionDetailVO> detail(@PathVariable String runId) {
        return ApiResponse.ok(executionService.detail(runId));
    }
}
