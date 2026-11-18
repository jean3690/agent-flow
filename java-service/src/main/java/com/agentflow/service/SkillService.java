package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.security.UserContext;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.http.HttpStatus;

import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class SkillService {

    private final AiClient aiClient;

    public List<JsonNode> list() {
        return aiClient.dataList("/v1/skills");
    }

    public JsonNode detail(String name) {
        validateName(name);
        return aiClient.data("/v1/skills/" + name);
    }

    public JsonNode save(String name, String content) {
        requireAdmin(); validateName(name);
        return aiClient.putJson("/v1/skills/" + name, Map.of("content", content));
    }

    public void delete(String name) {
        requireAdmin(); validateName(name);
        aiClient.delete("/v1/skills/" + name);
    }

    public JsonNode reference(String name, String file) {
        validateName(name);
        if (!file.matches("[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}\\.md")) {
            throw new BizException("引用文件名无效");
        }
        return aiClient.data("/v1/skills/" + name + "/references/" + file);
    }

    private void validateName(String name) {
        if (name == null || !name.matches("[a-z][a-z0-9_-]{0,63}")) throw new BizException("技能标识无效");
    }

    private void requireAdmin() {
        if (!"ADMIN".equals(UserContext.require().role())) {
            throw new BizException(4030, "只有管理员可管理平台共享技能", HttpStatus.FORBIDDEN);
        }
    }

    public JsonNode reload() {
        requireAdmin();
        return aiClient.postData("/v1/skills/reload").path("data");
    }
}
