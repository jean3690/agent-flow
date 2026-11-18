package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.common.PageResult;
import com.agentflow.dto.ExecuteRequest;
import com.agentflow.dto.ExecutionSummaryVO;
import com.agentflow.dto.RunResultVO;
import com.agentflow.dto.WorkflowDetailVO;
import com.agentflow.dto.WorkflowSaveRequest;
import com.agentflow.dto.WorkflowSummaryVO;
import com.agentflow.dto.WorkflowVersionVO;
import com.agentflow.security.UserContext;
import com.agentflow.service.ExecutionService;
import com.agentflow.service.WorkflowService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;

@RestController
@RequestMapping("/api/workflows")
@RequiredArgsConstructor
public class WorkflowController {

    private final WorkflowService workflowService;
    private final ExecutionService executionService;

    @GetMapping
    public ApiResponse<PageResult<WorkflowSummaryVO>> page(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String keyword) {
        return ApiResponse.ok(workflowService.page(page, size, keyword, UserContext.require()));
    }

    @PostMapping
    public ApiResponse<WorkflowDetailVO> create(@Valid @RequestBody WorkflowSaveRequest request) {
        return ApiResponse.ok(workflowService.create(request, UserContext.require()));
    }

    @GetMapping("/{id}")
    public ApiResponse<WorkflowDetailVO> detail(@PathVariable Long id) {
        return ApiResponse.ok(workflowService.detail(id, UserContext.require()));
    }

    @PutMapping("/{id}")
    public ApiResponse<WorkflowDetailVO> update(@PathVariable Long id, @Valid @RequestBody WorkflowSaveRequest request) {
        return ApiResponse.ok(workflowService.update(id, request, UserContext.require()));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable Long id) {
        workflowService.delete(id, UserContext.require());
        return ApiResponse.ok();
    }

    @PostMapping("/{id}/duplicate")
    public ApiResponse<WorkflowDetailVO> duplicate(@PathVariable Long id) {
        return ApiResponse.ok(workflowService.duplicate(id, UserContext.require()));
    }

    @PostMapping(value = "/{id}/execute", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter execute(@PathVariable Long id, @RequestBody(required = false) ExecuteRequest request) {
        return executionService.execute(id, request == null ? new ExecuteRequest() : request, UserContext.require());
    }

    @PostMapping("/{id}/run")
    public ApiResponse<RunResultVO> run(@PathVariable Long id, @RequestBody(required = false) ExecuteRequest request) {
        return ApiResponse.ok(executionService.runSync(id, request == null ? new ExecuteRequest() : request, UserContext.require()));
    }

    @GetMapping("/{id}/versions")
    public ApiResponse<List<WorkflowVersionVO>> versions(@PathVariable Long id) {
        return ApiResponse.ok(workflowService.listVersions(id, UserContext.require()));
    }

    @GetMapping("/{id}/versions/{version}")
    public ApiResponse<WorkflowVersionVO> versionDetail(@PathVariable Long id,
                                                        @PathVariable Integer version) {
        return ApiResponse.ok(workflowService.versionDetail(id, version, UserContext.require()));
    }

    @PostMapping("/{id}/versions/{version}/rollback")
    public ApiResponse<WorkflowDetailVO> rollback(@PathVariable Long id, @PathVariable Integer version) {
        return ApiResponse.ok(workflowService.rollback(id, version, UserContext.require()));
    }

    @PostMapping("/{id}/publish")
    public ApiResponse<WorkflowDetailVO> publish(@PathVariable Long id) {
        return ApiResponse.ok(workflowService.publish(id, UserContext.require()));
    }

    @PostMapping("/{id}/unpublish")
    public ApiResponse<WorkflowDetailVO> unpublish(@PathVariable Long id) {
        return ApiResponse.ok(workflowService.unpublish(id, UserContext.require()));
    }

    @GetMapping("/{id}/executions")
    public ApiResponse<PageResult<ExecutionSummaryVO>> executions(
            @PathVariable Long id,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size) {
        return ApiResponse.ok(executionService.page(page, size, id, null, UserContext.require()));
    }
}
