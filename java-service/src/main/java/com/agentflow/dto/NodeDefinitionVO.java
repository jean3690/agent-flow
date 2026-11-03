package com.agentflow.dto;

import com.agentflow.entity.NodeDefinition;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class NodeDefinitionVO {

    private String type;
    private String name;
    private String category;
    private String icon;
    private String color;
    private String description;
    private JsonNode configSchema;
    private Integer sort;

    public static NodeDefinitionVO of(NodeDefinition entity, JsonNode schema) {
        return NodeDefinitionVO.builder()
                .type(entity.getType())
                .name(entity.getName())
                .category(entity.getCategory())
                .icon(entity.getIcon())
                .color(entity.getColor())
                .description(entity.getDescription())
                .configSchema(schema)
                .sort(entity.getSort())
                .build();
    }
}
