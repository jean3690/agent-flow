import asyncio
import math

import pytest

from app.api import embeddings as embeddings_api
from app.config import Settings
from app.core.errors import NodeExecutionError
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.nodes.knowledge_node import KnowledgeNodeExecutor
from app.schemas.flow import Flow, FlowNode


def test_embedding_endpoint_is_deterministic_in_mock_mode():
    request = embeddings_api.EmbeddingRequest(provider="mock", input=["你好世界", "第二个文本"])
    first = asyncio.run(embeddings_api.embeddings(request))["data"]
    second = asyncio.run(embeddings_api.embeddings(request))["data"]

    assert first["mock"] is True
    assert len(first["vectors"]) == 2
    assert first["vectors"] == second["vectors"]
    assert all(abs(math.sqrt(sum(value * value for value in vector)) - 1) < 0.01 for vector in first["vectors"])


def test_knowledge_node_requires_knowledge_base():
    ctx = NodeContext(
        run_id="run-knowledge",
        settings=Settings(mock_mode="auto"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
    )
    node = FlowNode(id="kb1", type="knowledge", config={})
    with pytest.raises(NodeExecutionError) as error:
        asyncio.run(KnowledgeNodeExecutor().execute(node, {}, ctx))
    assert "知识库" in error.value.message
