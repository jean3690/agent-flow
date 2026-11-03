package com.agentflow.service;

import com.agentflow.dto.NodeDefinitionVO;
import com.agentflow.entity.NodeDefinition;
import com.agentflow.mapper.NodeDefinitionMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class NodeDefinitionService {

    private final NodeDefinitionMapper nodeDefinitionMapper;
    private final ObjectMapper objectMapper;

    public List<NodeDefinitionVO> list() {
        List<NodeDefinition> definitions = nodeDefinitionMapper.selectList(
                new LambdaQueryWrapper<NodeDefinition>()
                        .eq(NodeDefinition::getEnabled, 1)
                        .orderByAsc(NodeDefinition::getSort));
        return definitions.stream().map(item -> NodeDefinitionVO.of(item, parse(item.getConfigSchema()))).toList();
    }

    private JsonNode parse(String schema) {
        try {
            return schema == null ? objectMapper.createArrayNode() : objectMapper.readTree(schema);
        } catch (Exception ex) {
            return objectMapper.createArrayNode();
        }
    }
}
