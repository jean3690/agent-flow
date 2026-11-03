package com.agentflow.service;

import com.fasterxml.jackson.databind.JsonNode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class SkillService {

    private final AiClient aiClient;

    public List<JsonNode> list() {
        return aiClient.dataList("/v1/skills");
    }

    public JsonNode detail(String name) {
        return aiClient.data("/v1/skills/" + name);
    }

    public JsonNode reload() {
        return aiClient.postData("/v1/skills/reload").path("data");
    }
}
