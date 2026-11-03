package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.service.AiClient;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/system")
@RequiredArgsConstructor
public class SystemController {

    private final AiClient aiClient;

    @GetMapping("/health")
    public ApiResponse<Map<String, Object>> health() {
        return ApiResponse.ok(Map.of("status", "UP", "service", "agent-flow-java"));
    }

    @GetMapping("/ai-health")
    public ApiResponse<Object> aiHealth() {
        boolean up = aiClient.healthy();
        return ApiResponse.ok(Map.of("up", up));
    }
}
