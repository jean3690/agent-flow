package com.agentflow.service;

import com.agentflow.config.AgentFlowProperties;
import com.agentflow.entity.NodeDefinition;
import com.agentflow.entity.User;
import com.agentflow.mapper.NodeDefinitionMapper;
import com.agentflow.mapper.UserMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.io.ClassPathResource;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

import java.io.InputStream;

@Slf4j
@Component
@RequiredArgsConstructor
public class DataInitializer implements ApplicationRunner {

    private final UserMapper userMapper;
    private final NodeDefinitionMapper nodeDefinitionMapper;
    private final PasswordEncoder passwordEncoder;
    private final AgentFlowProperties properties;
    private final ObjectMapper objectMapper;

    @Override
    public void run(ApplicationArguments args) throws Exception {
        seedAdmin();
        seedNodes();
    }

    private void seedAdmin() {
        if (userMapper.selectCount(null) > 0) {
            return;
        }
        User admin = new User();
        admin.setUsername(properties.getAuth().getDefaultUsername());
        admin.setPassword(passwordEncoder.encode(properties.getAuth().getDefaultPassword()));
        admin.setNickname("管理员");
        admin.setRole("ADMIN");
        admin.setDeleted(0);
        userMapper.insert(admin);
        log.info("default admin created: {} / {}",
                properties.getAuth().getDefaultUsername(), properties.getAuth().getDefaultPassword());
    }

    private void seedNodes() throws Exception {
        try (InputStream input = new ClassPathResource("node-definitions.json").getInputStream()) {
            JsonNode nodes = objectMapper.readTree(input);
            int created = 0;
            int updated = 0;
            for (JsonNode item : nodes) {
                String type = item.path("type").asText();
                NodeDefinition definition = nodeDefinitionMapper.selectOne(
                        new LambdaQueryWrapper<NodeDefinition>().eq(NodeDefinition::getType, type));
                boolean isNew = definition == null;
                if (isNew) {
                    definition = new NodeDefinition();
                    definition.setType(type);
                }
                definition.setName(item.path("name").asText());
                definition.setCategory(item.path("category").asText());
                definition.setIcon(item.path("icon").asText());
                definition.setColor(item.path("color").asText());
                definition.setDescription(item.path("description").asText());
                definition.setConfigSchema(item.path("configSchema").toString());
                definition.setSort(item.path("sort").asInt());
                definition.setEnabled(1);
                if (isNew) {
                    nodeDefinitionMapper.insert(definition);
                    created++;
                } else {
                    nodeDefinitionMapper.updateById(definition);
                    updated++;
                }
            }
            log.info("node definitions synced: {} total, {} new, {} updated", nodes.size(), created, updated);
        }
    }
}
