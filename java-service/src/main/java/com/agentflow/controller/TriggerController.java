package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.dto.TriggerRequest;
import com.agentflow.dto.TriggerVO;
import com.agentflow.dto.WebhookResultVO;
import com.agentflow.security.UserContext;
import com.agentflow.service.TriggerService;
import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 触发器管理（需登录或 API Key）+ Webhook 入口（公开，凭 URL 令牌鉴权）。
 */
@RestController
@RequiredArgsConstructor
public class TriggerController {

    private final TriggerService triggerService;

    @GetMapping("/api/workflows/{workflowId}/triggers")
    public ApiResponse<List<TriggerVO>> list(@PathVariable Long workflowId) {
        return ApiResponse.ok(triggerService.list(workflowId, UserContext.require()));
    }

    @PostMapping("/api/workflows/{workflowId}/triggers")
    public ApiResponse<TriggerVO> create(@PathVariable Long workflowId,
                                         @Valid @RequestBody TriggerRequest request) {
        return ApiResponse.ok(triggerService.create(workflowId, request, UserContext.require()));
    }

    @PutMapping("/api/triggers/{id}")
    public ApiResponse<TriggerVO> update(@PathVariable Long id,
                                         @Valid @RequestBody TriggerRequest request) {
        return ApiResponse.ok(triggerService.update(id, request, UserContext.require()));
    }

    @DeleteMapping("/api/triggers/{id}")
    public ApiResponse<Void> delete(@PathVariable Long id) {
        triggerService.delete(id, UserContext.require());
        return ApiResponse.ok();
    }

    @PostMapping("/api/triggers/{id}/run")
    public ApiResponse<TriggerVO> run(@PathVariable Long id) {
        return ApiResponse.ok(triggerService.runNow(id, UserContext.require()));
    }

    @PostMapping("/api/triggers/{id}/rotate-token")
    public ApiResponse<TriggerVO> rotateToken(@PathVariable Long id) {
        return ApiResponse.ok(triggerService.rotateToken(id, UserContext.require()));
    }

    /** Webhook 入口：请求体（JSON 对象）会合并进触发器的静态 input。 */
    @PostMapping("/api/triggers/webhook/{token}")
    public ApiResponse<WebhookResultVO> webhook(@PathVariable String token,
                                                @RequestBody(required = false) JsonNode body) {
        return ApiResponse.ok(triggerService.webhook(token, body));
    }
}
