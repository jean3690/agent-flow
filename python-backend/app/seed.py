from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import NodeDefinition

logger = logging.getLogger("paiagent.seed")

_NODE_DEFINITIONS = [
    (
        "input", "输入", "IO", "📥",
        '{"type": "object", "properties": {}}',
        '{"type": "object", "properties": {"input": {"type": "string"}}}',
        '{"type": "object", "properties": {"defaultValue": {"type": "string"}}}',
    ),
    (
        "output", "输出", "IO", "📤",
        '{"type": "object", "properties": {"input": {"type": "string"}}}',
        '{"type": "object", "properties": {"output": {"type": "string"}}}',
        '{"type": "object", "properties": {}}',
    ),
    (
        "openai", "OpenAI", "LLM", "🤖",
        '{"type": "object", "properties": {"input": {"type": "string"}}}',
        '{"type": "object", "properties": {"output": {"type": "string"}, "tokens": {"type": "number"}}}',
        '{"type": "object", "properties": {"apiKey": {"type": "string"}, "model": {"type": "string", "default": "gpt-3.5-turbo"}, "prompt": {"type": "string"}, "temperature": {"type": "number", "default": 0.7}, "maxTokens": {"type": "number", "default": 1000}}}',
    ),
    (
        "deepseek", "DeepSeek", "LLM", "🧠",
        '{"type": "object", "properties": {"input": {"type": "string"}}}',
        '{"type": "object", "properties": {"output": {"type": "string"}, "tokens": {"type": "number"}}}',
        '{"type": "object", "properties": {"apiKey": {"type": "string"}, "model": {"type": "string", "default": "deepseek-chat"}, "prompt": {"type": "string"}, "temperature": {"type": "number", "default": 0.7}, "maxTokens": {"type": "number", "default": 1000}}}',
    ),
    (
        "qwen", "通义千问", "LLM", "🌟",
        '{"type": "object", "properties": {"input": {"type": "string"}}}',
        '{"type": "object", "properties": {"output": {"type": "string"}, "tokens": {"type": "number"}}}',
        '{"type": "object", "properties": {"apiKey": {"type": "string"}, "model": {"type": "string", "default": "qwen-turbo"}, "prompt": {"type": "string"}, "temperature": {"type": "number", "default": 0.7}, "maxTokens": {"type": "number", "default": 1000}}}',
    ),
    (
        "step", "Step", "LLM", "🟆",
        '{"type": "object", "properties": {"input": {"type": "string"}}}',
        '{"type": "object", "properties": {"output": {"type": "string"}, "tokens": {"type": "number"}}}',
        '{"type": "object", "properties": {"apiKey": {"type": "string"}, "model": {"type": "string", "default": "claude-3-5-sonnet-20241022"}, "prompt": {"type": "string"}, "temperature": {"type": "number", "default": 0.7}, "maxTokens": {"type": "number", "default": 1000}}}',
    ),
    (
        "react_agent", "ReAct Agent", "LLM", "RA",
        '{"type": "object", "properties": {"input": {"type": "string"}}}',
        '{"type": "object", "properties": {"output": {"type": "string"}, "finalAnswer": {"type": "string"}, "toolTrace": {"type": "array"}, "steps": {"type": "number"}, "tokens": {"type": "number"}}}',
        '{"type": "object", "properties": {"provider": {"type": "string"}, "configId": {"type": "number"}, "apiKey": {"type": "string"}, "model": {"type": "string"}, "prompt": {"type": "string"}, "temperature": {"type": "number", "default": 0.7}, "maxSteps": {"type": "number", "default": 5}, "tools": {"type": "array"}}}',
    ),
    (
        "tts", "超拟人音频合成", "TOOL", "🔊",
        '{"type": "object", "properties": {"text": {"type": "string"}}}',
        '{"type": "object", "properties": {"audioUrl": {"type": "string"}, "duration": {"type": "number"}, "fileSize": {"type": "number"}}}',
        '{"type": "object", "properties": {"provider": {"type": "string"}, "configId": {"type": "number"}, "apiUrl": {"type": "string"}, "apiKey": {"type": "string"}, "model": {"type": "string", "default": "qwen3-tts-flash"}, "voice": {"type": "string", "default": "Cherry"}, "languageType": {"type": "string", "default": "Auto"}, "instruction": {"type": "string"}, "speed": {"type": "number", "default": 1.0}, "volume": {"type": "number", "default": 1.0}, "sampleRate": {"type": "number", "default": 24000}}}',
    ),
    (
        "condition", "条件分支", "CONTROL", "🔀",
        '{"type": "object", "properties": {"input": {"type": "object"}}}',
        '{"type": "object", "properties": {"__selectedBranch__": {"type": "string"}, "__conditionNodeId__": {"type": "string"}}}',
        '{"type": "object", "properties": {"conditions": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "field": {"type": "string"}, "operator": {"type": "string", "enum": ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "notContains", "startsWith", "endsWith", "isEmpty", "isNotEmpty"]}, "value": {"type": "string"}}}}}}',
    ),
]


def seed_node_definitions(db: Session) -> None:
    count = db.execute(select(func.count()).select_from(NodeDefinition)).scalar_one()
    if count:
        return
    for node_type, display_name, category, icon, input_schema, output_schema, config_schema in _NODE_DEFINITIONS:
        db.add(
            NodeDefinition(
                node_type=node_type,
                display_name=display_name,
                category=category,
                icon=icon,
                input_schema=input_schema,
                output_schema=output_schema,
                config_schema=config_schema,
                deleted=0,
            )
        )
    db.commit()
    logger.info("Seeded %d node definitions", len(_NODE_DEFINITIONS))
