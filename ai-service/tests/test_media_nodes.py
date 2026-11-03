import asyncio

from app.config import Settings
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.nodes.image_node import ImageNodeExecutor, _placeholder_png
from app.nodes.video_node import VideoNodeExecutor
from app.nodes.vision_node import VisionNodeExecutor
from app.schemas.flow import Flow, FlowNode


def _context(tmp_path):
    return NodeContext(
        run_id="run-media",
        settings=Settings(mock_mode="always", output_dir=str(tmp_path)),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
    )


def test_placeholder_png_is_valid():
    data = _placeholder_png("一只猫")
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in data and b"IEND" in data


def test_image_node_mock_writes_file(tmp_path):
    ctx = _context(tmp_path)
    node = FlowNode(id="img", type="image_generate", config={"provider": "mock", "prompt": "一只猫"})
    result = asyncio.run(ImageNodeExecutor().execute(node, {"input": {}}, ctx))

    assert result["mock"] is True
    assert result["imageUrl"].startswith("/files/")
    file = tmp_path / result["imageUrl"].removeprefix("/files/")
    assert file.exists() and file.read_bytes()[:4] == b"\x89PNG"


def test_vision_node_mock_reads_upstream_image(tmp_path):
    ctx = _context(tmp_path)
    image = asyncio.run(ImageNodeExecutor().execute(
        FlowNode(id="img", type="image_generate", config={"provider": "mock", "prompt": "一只猫"}),
        {"input": {}}, ctx))
    state = {"input": {}, "outputs": {"image": image}}

    node = FlowNode(id="vision", type="vision_analyze", config={
        "provider": "mock", "model": "gpt-4o-mini",
        "imageUrl": "{{image.imageUrl}}", "prompt": "描述这张图片",
    })
    result = asyncio.run(VisionNodeExecutor().execute(node, state, ctx))

    assert result["mock"] is True
    assert result["imageUrl"] == image["imageUrl"]
    assert "视觉理解模拟输出" in result["text"]


def test_video_node_mock_creates_poster(tmp_path):
    ctx = _context(tmp_path)
    node = FlowNode(id="vid", type="video_generate", config={"provider": "mock", "prompt": "奔跑的猫"})
    result = asyncio.run(VideoNodeExecutor().execute(node, {"input": {}}, ctx))

    assert result["mock"] is True
    assert result["videoUrl"] == ""
    assert result["posterUrl"].startswith("/files/")
    file = tmp_path / result["posterUrl"].removeprefix("/files/")
    assert file.read_bytes()[:4] == b"\x89PNG"
