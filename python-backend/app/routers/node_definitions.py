from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import NodeDefinition
from ..result import success
from ..serializers import node_definition_to_dict

router = APIRouter(prefix="/api/node-types", tags=["节点定义接口"])

HIDDEN_STANDALONE_AGENT_NODE_TYPES = {
    "react_agent",
    "web_search",
    "web_fetch",
    "vision_analyze",
    "memory_write",
    "memory_retrieve",
    "knowledge_upsert",
    "knowledge_retrieve",
}


def _definition(
    node_type: str,
    display_name: str,
    category: str,
    icon: str,
    input_schema: str,
    output_schema: str,
    config_schema: str,
) -> NodeDefinition:
    node = NodeDefinition()
    node.node_type = node_type
    node.display_name = display_name
    node.category = category
    node.icon = icon
    node.input_schema = input_schema
    node.output_schema = output_schema
    node.config_schema = config_schema
    return node


def _generic_llm_definition() -> NodeDefinition:
    return _definition(
        "llm",
        "大模型",
        "LLM",
        "🤖",
        '{"type": "object", "properties": {"input": {"type": "string"}}}',
        '{"type": "object", "properties": {"output": {"type": "string"}, "tokens": {"type": "number"}}}',
        '{"type": "object", "properties": {"provider": {"type": "string"}, "configId": {"type": "number"}, "apiKey": {"type": "string"}, "model": {"type": "string"}, "prompt": {"type": "string"}, "temperature": {"type": "number", "default": 0.7}, "maxTokens": {"type": "number", "default": 1000}, "agentStrategy": {"type": "string", "default": "none"}, "maxSteps": {"type": "number", "default": 5}, "tools": {"type": "array"}, "memoryEnabled": {"type": "boolean", "default": false}, "memoryTopK": {"type": "number", "default": 5}, "knowledgeBaseId": {"type": "string"}, "knowledgeTopK": {"type": "number", "default": 5}, "knowledgeScoreThreshold": {"type": "number", "default": 0.2}}}',
    )


@router.get("")
def list_node_types(db: Session = Depends(get_db)):
    definitions: dict[str, NodeDefinition] = {}
    rows = db.execute(
        select(NodeDefinition)
        .where(NodeDefinition.deleted == 0)
        .order_by(NodeDefinition.id.asc())
    ).scalars()
    for row in rows:
        definitions[row.node_type] = row

    defaults = [
        _generic_llm_definition(),
        _definition(
            "memory_write",
            "写入记忆",
            "MEMORY",
            "MW",
            '{"type":"object","properties":{"content":{"type":"string"}}}',
            '{"type":"object","properties":{"memoryId":{"type":"string"},"scope":{"type":"string"},"stored":{"type":"boolean"}}}',
            '{"type":"object","properties":{"configId":{"type":"number"},"content":{"type":"string"},"memoryType":{"type":"string","default":"fact"},"tags":{"type":"string"},"scope":{"type":"string","default":"workflow"}}}',
        ),
        _definition(
            "memory_retrieve",
            "召回记忆",
            "MEMORY",
            "MR",
            '{"type":"object","properties":{"query":{"type":"string"}}}',
            '{"type":"object","properties":{"memories":{"type":"array"},"context":{"type":"string"},"citations":{"type":"array"}}}',
            '{"type":"object","properties":{"configId":{"type":"number"},"query":{"type":"string"},"scope":{"type":"string","default":"workflow"},"topK":{"type":"number","default":5},"tags":{"type":"string"}}}',
        ),
        _definition(
            "knowledge_upsert",
            "写入知识库",
            "KNOWLEDGE",
            "KU",
            '{"type":"object","properties":{"content":{"type":"string"}}}',
            '{"type":"object","properties":{"knowledgeBaseId":{"type":"string"},"contentId":{"type":"string"},"chunkCount":{"type":"number"},"indexed":{"type":"boolean"}}}',
            '{"type":"object","properties":{"configId":{"type":"number"},"knowledgeBaseId":{"type":"string"},"content":{"type":"string"},"sourceUrl":{"type":"string"},"title":{"type":"string"},"tags":{"type":"string"}}}',
        ),
        _definition(
            "knowledge_retrieve",
            "检索知识库",
            "KNOWLEDGE",
            "KR",
            '{"type":"object","properties":{"query":{"type":"string"}}}',
            '{"type":"object","properties":{"chunks":{"type":"array"},"citations":{"type":"array"},"context":{"type":"string"}}}',
            '{"type":"object","properties":{"configId":{"type":"number"},"knowledgeBaseId":{"type":"string"},"query":{"type":"string"},"topK":{"type":"number","default":5},"scoreThreshold":{"type":"number","default":0.2}}}',
        ),
        _definition(
            "image_generate",
            "图片生成",
            "TOOL",
            "IMG",
            '{"type":"object","properties":{"prompt":{"type":"string"}}}',
            '{"type":"object","properties":{"imageUrl":{"type":"string"},"imageUrls":{"type":"array"},"prompt":{"type":"string"},"model":{"type":"string"},"metadata":{"type":"object"}}}',
            '{"type":"object","properties":{"configId":{"type":"number"},"prompt":{"type":"string"},"model":{"type":"string"},"referenceImageUrl":{"type":"string"},"size":{"type":"string","default":"1024x1024"},"style":{"type":"string"},"count":{"type":"number","default":1},"negativePrompt":{"type":"string"},"steps":{"type":"number"},"cfgScale":{"type":"number"},"seed":{"type":"number"},"textMode":{"type":"boolean","default":true}}}',
        ),
        _definition(
            "video_generate",
            "视频生成",
            "TOOL",
            "VID",
            '{"type":"object","properties":{"prompt":{"type":"string"}}}',
            '{"type":"object","properties":{"taskId":{"type":"string"},"status":{"type":"string"},"videoUrl":{"type":"string"},"coverUrl":{"type":"string"},"model":{"type":"string"},"metadata":{"type":"object"}}}',
            '{"type":"object","properties":{"configId":{"type":"number"},"prompt":{"type":"string"},"model":{"type":"string"},"referenceImageUrl":{"type":"string"},"duration":{"type":"number","default":5},"resolution":{"type":"string"},"ratio":{"type":"string","default":"adaptive"},"cameraMotion":{"type":"string"}}}',
        ),
    ]
    for definition in defaults:
        definitions.setdefault(definition.node_type, definition)

    output = [
        node_definition_to_dict(definition)
        for definition in definitions.values()
        if definition.node_type not in HIDDEN_STANDALONE_AGENT_NODE_TYPES
        and (definition.category != "LLM" or definition.node_type == "llm")
    ]
    return success(output)
