package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.common.BizException;
import com.agentflow.config.AgentFlowProperties;
import com.agentflow.dto.MemorySearchRequest;
import com.agentflow.dto.MemoryWriteRequest;
import com.agentflow.service.AgentMemoryService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** 仅供 ai-service 的记忆节点调用，使用共享令牌而不是用户 JWT。 */
@RestController
@RequestMapping("/internal/memory")
@RequiredArgsConstructor
public class InternalMemoryController {

    private final AgentMemoryService memoryService;
    private final AgentFlowProperties properties;

    @PostMapping("/write")
    public ApiResponse<Map<String, Object>> write(@RequestHeader(value = "X-Internal-Token", required = false) String token,
                                                  @Valid @RequestBody MemoryWriteRequest request) {
        requireToken(token);
        return ApiResponse.ok(memoryService.write(request));
    }

    @PostMapping("/search")
    public ApiResponse<Map<String, Object>> search(@RequestHeader(value = "X-Internal-Token", required = false) String token,
                                                   @Valid @RequestBody MemorySearchRequest request) {
        requireToken(token);
        return ApiResponse.ok(memoryService.search(request));
    }

    private void requireToken(String token) {
        if (token == null || !token.equals(properties.getInternal().getToken())) {
            throw BizException.unauthorized("内部调用令牌无效");
        }
    }
}
