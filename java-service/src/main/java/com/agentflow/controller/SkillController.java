package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.service.SkillService;
import com.agentflow.dto.SkillSaveRequest;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.RequestBody;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/skills")
@RequiredArgsConstructor
public class SkillController {

    private final SkillService skillService;

    @GetMapping
    public ApiResponse<List<JsonNode>> list() {
        return ApiResponse.ok(skillService.list());
    }

    @GetMapping("/{name}")
    public ApiResponse<JsonNode> detail(@PathVariable String name) {
        return ApiResponse.ok(skillService.detail(name));
    }

    @PostMapping("/reload")
    public ApiResponse<JsonNode> reload() {
        return ApiResponse.ok(skillService.reload());
    }

    @PutMapping("/{name}")
    public ApiResponse<JsonNode> save(@PathVariable String name, @Valid @RequestBody SkillSaveRequest request) {
        return ApiResponse.ok(skillService.save(name, request.getContent()));
    }

    @DeleteMapping("/{name}")
    public ApiResponse<Void> delete(@PathVariable String name) {
        skillService.delete(name); return ApiResponse.ok();
    }

    @GetMapping("/{name}/references/{file}")
    public ApiResponse<JsonNode> reference(@PathVariable String name, @PathVariable String file) {
        return ApiResponse.ok(skillService.reference(name, file));
    }
}
