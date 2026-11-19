"""Importing this package registers every built-in node executor."""

from app.nodes import (  # noqa: F401
    agent_paradigms,
    approval_node,
    condition_node,
    control_nodes,
    data_nodes,
    file_nodes,
    http_node,
    image_node,
    image_translate_node,
    input_node,
    knowledge_node,
    llm_node,
    mcp_node,
    memory_nodes,
    output_node,
    rag_nodes,
    react_agent_node,
    template_node,
    text_nodes,
    tts_node,
    utility_nodes,
    video_node,
    vision_node,
    web_nodes,
)
from app.nodes.registry import get_executor, registered_types

__all__ = ["get_executor", "registered_types"]
