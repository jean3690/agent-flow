package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.dto.ApprovalDecisionRequest;
import com.agentflow.dto.ApprovalVO;
import com.agentflow.security.UserContext;
import com.agentflow.service.ApprovalService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/approvals")
@RequiredArgsConstructor
public class ApprovalController {

    private final ApprovalService approvalService;

    @GetMapping
    public ApiResponse<List<ApprovalVO>> list(@RequestParam(required = false) String status) {
        return ApiResponse.ok(approvalService.list(UserContext.get(), status));
    }

    @PostMapping("/{id}/decide")
    public ApiResponse<ApprovalVO> decide(@PathVariable Long id,
                                          @Valid @RequestBody ApprovalDecisionRequest request) {
        return ApiResponse.ok(approvalService.decide(id, request, UserContext.get()));
    }
}
