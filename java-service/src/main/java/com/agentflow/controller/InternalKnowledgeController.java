package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.common.BizException;
import com.agentflow.config.AgentFlowProperties;
import com.agentflow.dto.KnowledgeDocumentVO;
import com.agentflow.dto.KnowledgeSearchHitVO;
import com.agentflow.dto.KnowledgeSearchRequest;
import com.agentflow.dto.KnowledgeUpsertRequest;
import com.agentflow.service.KnowledgeBaseService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/** 仅供 ai-service 在节点执行期调用，使用共享令牌而不是用户 JWT。 */
@RestController
@RequestMapping("/internal/knowledge")
@RequiredArgsConstructor
public class InternalKnowledgeController {

    private final KnowledgeBaseService knowledgeBaseService;
    private final AgentFlowProperties properties;

    @PostMapping("/search")
    public ApiResponse<Map<String, Object>> search(@RequestHeader(value = "X-Internal-Token", required = false) String token,
                                                   @Valid @RequestBody KnowledgeSearchRequest request) {
        if (token == null || !token.equals(properties.getInternal().getToken())) {
            throw BizException.unauthorized("内部调用令牌无效");
        }
        List<KnowledgeSearchHitVO> hits = knowledgeBaseService.searchForRuntime(
                request.getKnowledgeBaseId(), request.getQuery(), request.getTopK());
        return ApiResponse.ok(Map.of("chunks", hits, "count", hits.size()));
    }

    @PostMapping("/upsert")
    public ApiResponse<KnowledgeDocumentVO> upsert(@RequestHeader(value = "X-Internal-Token", required = false) String token,
                                                   @Valid @RequestBody KnowledgeUpsertRequest request) {
        if (token == null || !token.equals(properties.getInternal().getToken())) {
            throw BizException.unauthorized("内部调用令牌无效");
        }
        return ApiResponse.ok(knowledgeBaseService.upsertForRuntime(
                request.getKnowledgeBaseId(), request.getTitle(), request.getContent()));
    }
}
