import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.core.errors import NodeExecutionError
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.nodes import approval_node
from app.nodes.approval_node import HumanApprovalNodeExecutor
from app.schemas.flow import Flow, FlowNode


def _context(mock_mode: str = "never") -> NodeContext:
    return NodeContext(
        run_id="run-approval",
        settings=Settings(mock_mode=mock_mode, platform_service_base_url="http://java.test",
                          internal_token="token"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
        workflow_id="42",
        user_id=7,
    )


def _mock_client(monkeypatch, handler):
    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(approval_node.httpx, "AsyncClient", _Client)


async def _no_sleep(*args, **kwargs):
    return None


def test_auto_approve_in_mock_mode_skips_http(monkeypatch):
    ctx = _context("always")
    node = FlowNode(id="approval", type="human_approval", config={"title": "发布审批"})
    result = asyncio.run(HumanApprovalNodeExecutor().execute(node, {"input": {"text": "内容"}}, ctx))

    assert result["approved"] is True
    assert result["auto"] is True
    assert result["status"] == "APPROVED"


def test_auto_approve_switch_works_without_mock(monkeypatch):
    ctx = _context("never")
    node = FlowNode(id="approval", type="human_approval", config={"autoApprove": True})
    result = asyncio.run(HumanApprovalNodeExecutor().execute(node, {"input": {}}, ctx))
    assert result["approved"] is True


def test_approval_polls_until_approved(monkeypatch):
    posts = []
    gets = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(200, json={"code": 0, "data": {"id": 9, "status": "PENDING"}})
        gets.append(request.url.path)
        if len(gets) == 1:
            return httpx.Response(200, json={"code": 0, "data": {"status": "PENDING"}})
        return httpx.Response(200, json={"code": 0, "data": {
            "status": "APPROVED", "comment": "同意发布", "decidedBy": 1,
        }})

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr(approval_node.asyncio, "sleep", _no_sleep)
    node = FlowNode(id="approval", type="human_approval", config={
        "title": "发布审批-{{input.env}}", "content": "{{input.text}}",
        "waitSeconds": 60, "rejectBehavior": "fail",
    })
    result = asyncio.run(HumanApprovalNodeExecutor().execute(
        node, {"input": {"env": "prod", "text": "要发布的正文"}}, _context()))

    assert posts[0]["runId"] == "run-approval"
    assert posts[0]["workflowId"] == 42
    assert posts[0]["nodeId"] == "approval"
    assert posts[0]["userId"] == 7
    assert posts[0]["title"] == "发布审批-prod"
    assert posts[0]["content"] == "要发布的正文"
    assert posts[0]["expiresInSeconds"] == 60
    assert len(gets) == 2
    assert result["approved"] is True
    assert result["approvalId"] == 9
    assert result["comment"] == "同意发布"


def test_rejection_can_fail_or_continue(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"id": 9, "status": "PENDING"}})
        return httpx.Response(200, json={"data": {"status": "REJECTED", "comment": "风险太高"}})

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr(approval_node.asyncio, "sleep", _no_sleep)

    continue_node = FlowNode(id="approval", type="human_approval", config={
        "rejectBehavior": "continue", "waitSeconds": 30,
    })
    continued = asyncio.run(HumanApprovalNodeExecutor().execute(continue_node, {}, _context()))
    assert continued["approved"] is False
    assert continued["status"] == "REJECTED"
    assert continued["comment"] == "风险太高"

    fail_node = FlowNode(id="approval", type="human_approval", config={
        "rejectBehavior": "fail", "waitSeconds": 30,
    })
    with pytest.raises(NodeExecutionError) as error:
        asyncio.run(HumanApprovalNodeExecutor().execute(fail_node, {}, _context()))
    assert "风险太高" in error.value.message


def test_wait_timeout_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"id": 9, "status": "PENDING"}})
        return httpx.Response(200, json={"data": {"status": "PENDING"}})

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr(approval_node.asyncio, "sleep", _no_sleep)

    times = iter([0.0, 0.0, 999.0])
    class _FakeTime:
        @staticmethod
        def monotonic():
            return next(times, 999.0)

    monkeypatch.setattr(approval_node, "time", _FakeTime)
    node = FlowNode(id="approval", type="human_approval", config={"waitSeconds": 30})
    with pytest.raises(NodeExecutionError) as error:
        asyncio.run(HumanApprovalNodeExecutor().execute(node, {}, _context()))
    assert "超时" in error.value.message
