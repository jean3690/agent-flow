package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.dto.NodeDefinitionVO;
import com.agentflow.service.NodeDefinitionService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/node-definitions")
@RequiredArgsConstructor
public class NodeDefinitionController {

    private final NodeDefinitionService nodeDefinitionService;

    @GetMapping
    public ApiResponse<List<NodeDefinitionVO>> list() {
        return ApiResponse.ok(nodeDefinitionService.list());
    }
}
