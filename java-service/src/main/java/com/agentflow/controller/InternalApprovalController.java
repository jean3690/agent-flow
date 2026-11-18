package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.common.BizException;
import com.agentflow.config.AgentFlowProperties;
import com.agentflow.dto.ApprovalCreateRequest;
import com.agentflow.dto.ApprovalVO;
import com.agentflow.service.ApprovalService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 仅供 ai-service 的 human_approval 节点创建与轮询审批任务。 */
@RestController
@RequestMapping("/internal/approvals")
@RequiredArgsConstructor
public class InternalApprovalController {

    private final ApprovalService approvalService;
    private final AgentFlowProperties properties;

    @PostMapping
    public ApiResponse<ApprovalVO> create(@RequestHeader(value = "X-Internal-Token", required = false) String token,
                                          @Valid @RequestBody ApprovalCreateRequest request) {
        requireToken(token);
        return ApiResponse.ok(approvalService.create(request));
    }

    @GetMapping("/{id}")
    public ApiResponse<ApprovalVO> get(@RequestHeader(value = "X-Internal-Token", required = false) String token,
                                       @PathVariable Long id) {
        requireToken(token);
        return ApiResponse.ok(approvalService.get(id));
    }

    private void requireToken(String token) {
        if (token == null || !token.equals(properties.getInternal().getToken())) {
            throw BizException.unauthorized("内部调用令牌无效");
        }
    }
}
