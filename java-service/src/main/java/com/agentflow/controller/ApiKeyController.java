package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.common.BizException;
import com.agentflow.security.UserContext;
import com.agentflow.service.ApiKeyService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

@RestController
@RequestMapping("/api/api-keys")
@RequiredArgsConstructor
public class ApiKeyController {

    private final ApiKeyService apiKeyService;

    private void requireAdmin() {
        if (!"ADMIN".equals(UserContext.require().role())) {
            throw BizException.unauthorized("仅管理员可管理 API Key");
        }
    }

    @PostMapping
    public ApiResponse<ApiKeyService.ApiKeyIssue> create(@Valid @RequestBody CreateRequest request) {
        requireAdmin();
        Long owner = request.ownerUserId != null ? request.ownerUserId : UserContext.require().id();
        return ApiResponse.ok(apiKeyService.issue(request.name, owner, request.expiresAt));
    }

    @GetMapping
    public ApiResponse<List<ApiKeyService.ApiKeyInfo>> list() {
        requireAdmin();
        return ApiResponse.ok(apiKeyService.list());
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> revoke(@PathVariable Long id) {
        requireAdmin();
        apiKeyService.revoke(id);
        return ApiResponse.ok();
    }

    @Data
    public static class CreateRequest {
        @NotBlank(message = "名称不能为空")
        private String name;
        private Long ownerUserId;
        /** 可选过期时间（ISO-8601），为空表示长期有效。 */
        private LocalDateTime expiresAt;
    }
}
