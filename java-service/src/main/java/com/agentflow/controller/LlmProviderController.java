package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.dto.LlmProviderVO;
import com.agentflow.dto.ProviderTestRequest;
import com.agentflow.dto.SaveProviderRequest;
import com.agentflow.service.LlmProviderService;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/llm-providers")
@RequiredArgsConstructor
public class LlmProviderController {

    private final LlmProviderService llmProviderService;

    @GetMapping
    public ApiResponse<List<LlmProviderVO>> list() {
        return ApiResponse.ok(llmProviderService.list());
    }

    @PutMapping("/{provider}")
    public ApiResponse<Void> save(@PathVariable String provider, @RequestBody SaveProviderRequest request) {
        llmProviderService.save(provider, request);
        return ApiResponse.ok();
    }

    @DeleteMapping("/{provider}")
    public ApiResponse<Void> clear(@PathVariable String provider) {
        llmProviderService.clear(provider);
        return ApiResponse.ok();
    }

    @PostMapping("/{provider}/test")
    public ApiResponse<JsonNode> test(@PathVariable String provider, @RequestBody(required = false) ProviderTestRequest request) {
        return ApiResponse.ok(llmProviderService.test(provider,
                request == null ? new ProviderTestRequest() : request));
    }
}
