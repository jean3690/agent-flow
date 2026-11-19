package com.agentflow.controller;

import com.agentflow.common.ApiResponse;
import com.agentflow.dto.RealtimeTranslationRequest;
import com.agentflow.security.UserContext;
import com.agentflow.service.AiClient;
import com.agentflow.service.LlmProviderService;
import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/translations")
@RequiredArgsConstructor
public class TranslationController {
    private final AiClient aiClient;
    private final LlmProviderService providers;

    @PostMapping("/realtime/sessions")
    public ApiResponse<JsonNode> create(@Valid @RequestBody RealtimeTranslationRequest request) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("provider", request.getProvider());
        body.put("model", "qwen3.8-livetranslate-flash-realtime");
        body.put("userId", UserContext.require().id());
        body.put("targetLang", request.getTargetLang());
        body.put("apiHost", request.getApiHost());
        body.put("voice", request.getVoice());
        body.put("outputAudio", request.isOutputAudio());
        if ("qwen".equals(request.getProvider())) {
            Map<String, String> credentials = providers.credentials("qwen");
            if (credentials != null) body.putAll(credentials);
        }
        return ApiResponse.ok(aiClient.postJson("/v1/translations/realtime/sessions", body).path("data"));
    }
}
