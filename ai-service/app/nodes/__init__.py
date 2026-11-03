"""Importing this package registers every built-in node executor."""

from app.nodes import (  # noqa: F401
    condition_node,
    http_node,
    image_node,
    input_node,
    knowledge_node,
    llm_node,
    output_node,
    react_agent_node,
    template_node,
    tts_node,
    video_node,
    vision_node,
)
from app.nodes.registry import get_executor, registered_types

__all__ = ["get_executor", "registered_types"]
