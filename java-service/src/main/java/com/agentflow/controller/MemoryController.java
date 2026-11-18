package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.dto.MemoryVO;
import com.agentflow.security.UserContext;
import com.agentflow.service.AgentMemoryService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** 记忆管理接口：普通用户只能看到自己的记忆与全局记忆。 */
@RestController
@RequestMapping("/api/memories")
@RequiredArgsConstructor
public class MemoryController {

    private final AgentMemoryService memoryService;

    @GetMapping
    public ApiResponse<List<MemoryVO>> list(@RequestParam(required = false) String scope,
                                            @RequestParam(required = false) Long workflowId) {
        return ApiResponse.ok(memoryService.list(UserContext.get(), scope, workflowId));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable Long id) {
        memoryService.delete(id, UserContext.get());
        return ApiResponse.ok();
    }
}
