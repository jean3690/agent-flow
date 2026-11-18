package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.dto.McpServerRequest;
import com.agentflow.security.UserContext;
import com.agentflow.service.McpServerService;
import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/mcp-servers")
@RequiredArgsConstructor
public class McpServerController {
    private final McpServerService service;
    @GetMapping public ApiResponse<List<Map<String, Object>>> list() { return ApiResponse.ok(service.list(UserContext.require())); }
    @PostMapping public ApiResponse<Map<String, Object>> create(@Valid @RequestBody McpServerRequest request) { return ApiResponse.ok(service.save(null, request, UserContext.require())); }
    @PutMapping("/{id}") public ApiResponse<Map<String, Object>> update(@PathVariable Long id, @Valid @RequestBody McpServerRequest request) { return ApiResponse.ok(service.save(id, request, UserContext.require())); }
    @DeleteMapping("/{id}") public ApiResponse<Void> delete(@PathVariable Long id) { service.delete(id, UserContext.require()); return ApiResponse.ok(); }
    @PostMapping("/{id}/discover") public ApiResponse<JsonNode> discover(@PathVariable Long id) { return ApiResponse.ok(service.discover(id, UserContext.require())); }
    @GetMapping("/{id}/tools") public ApiResponse<List<JsonNode>> tools(@PathVariable Long id) { return ApiResponse.ok(service.tools(id, UserContext.require())); }
}
