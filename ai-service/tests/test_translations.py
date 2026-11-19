import asyncio
import base64
import io
import json
import time
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, UnidentifiedImageError
from starlette.websockets import WebSocketDisconnect

from app.api import translations as live
from app.config import Settings
from app.core.bailian import api_origin, download_image
from app.core.errors import NodeExecutionError
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.main import app
from app.nodes.image_translate_node import ImageTranslateNodeExecutor
from app.schemas.execution import ProviderConfig
from app.schemas.flow import Flow, FlowNode


def context(tmp_path, **settings):
    return NodeContext(run_id="translation-test", settings=Settings(_env_file=None, output_dir=str(tmp_path),
        mock_mode="never", **settings), flow=Flow(nodes=[], edges=[]), bus=EventBus(),
        providers={"qwen": ProviderConfig(api_key="sk-test-secret", base_url="https://demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")})


def jpeg():
    file = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(file, format="JPEG")
    return file.getvalue()


@pytest.mark.parametrize("host", ["localhost", "example.com", "demo.cn-beijing.maas.aliyuncs.com.evil.com",
    "https://user:pass@dashscope.aliyuncs.com", "https://dashscope.aliyuncs.com:443", "http://dashscope.aliyuncs.com"])
def test_api_host_rejects_untrusted_targets(host):
    with pytest.raises(ValueError):
        api_origin(host)


def test_native_origin_and_realtime_workspace():
    assert api_origin("", "https://demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1") == "https://demo.cn-beijing.maas.aliyuncs.com"
    assert api_origin("demo.ap-southeast-1.maas.aliyuncs.com", realtime=True).startswith("https://demo.")
    with pytest.raises(ValueError, match="业务空间"):
        api_origin("", realtime=True)


@pytest.mark.asyncio
async def test_image_translation_uploads_local_file_and_persists_result(tmp_path, monkeypatch):
    path = tmp_path / "原图.png"
    Image.new("RGB", (32, 32), "white").save(path)
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == "/api/v1/uploads":
            assert request.url.params["model"] == "qwen-mt-image-2.0"
            return httpx.Response(200, json={"data": {"upload_dir": "temp", "upload_host": "https://bucket.oss-cn-beijing.aliyuncs.com",
                "oss_access_key_id": "upload-id", "signature": "sig", "policy": "policy", "x_oss_object_acl": "private",
                "x_oss_forbid_overwrite": "true"}})
        if request.url.host.startswith("bucket."):
            assert "authorization" not in request.headers
            assert b"sk-test-secret" not in request.content
            return httpx.Response(200)
        if request.url.path.endswith("image-synthesis"):
            body = json.loads(request.content)
            assert body["input"]["image_url"].startswith("oss://temp/")
            assert request.headers["X-DashScope-OssResourceResolve"] == "enable"
            assert body["input"]["ext"]["terminologies"] == [{"src": "你好", "tgt": "hello"}]
            return httpx.Response(200, json={"output": {"image_url": "https://result.oss-cn-beijing.aliyuncs.com/result.jpg"},
                "usage": {"image_count": 1}, "request_id": "request-1"})
        return httpx.Response(200, content=jpeg())
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr("app.core.bailian._check_url", lambda url: url)
    result = await ImageTranslateNodeExecutor().execute(FlowNode(id="translate", type="image_translate", config={
        "imageUrl": "原图.png", "sourceLang": "zh", "targetLang": "en",
        "terminologies": '[{"src":"你好","tgt":"hello"}]'}), {"input": {}}, context(tmp_path))
    assert result["mock"] is False and result["requestId"] == "request-1"
    assert (tmp_path / result["imageUrl"].removeprefix("/files/")).read_bytes() == jpeg()
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_image_async_polling_does_not_resubmit(tmp_path, monkeypatch):
    counts = {"post": 0, "get": 0}
    def respond(request):
        if request.method == "POST":
            counts["post"] += 1
            assert request.headers["X-DashScope-Async"] == "enable"
            return httpx.Response(200, json={"output": {"task_id": "task-1"}})
        if "/tasks/" in request.url.path:
            counts["get"] += 1
            if counts["get"] == 1:
                return httpx.Response(200, json={"output": {"task_status": "RUNNING"}})
            return httpx.Response(200, json={"output": {"task_status": "SUCCEEDED", "image_url": "https://result.example/img.jpg",
                "message": "No text detected for translation"}, "usage": {"image_count": 1}})
        return httpx.Response(200, content=jpeg())
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr("app.core.bailian._check_url", lambda url: url)
    result = await ImageTranslateNodeExecutor().execute(FlowNode(id="translate", type="image_translate",
        config={"imageUrl": "oss://temp/img.png", "asyncMode": True}), {"input": {}}, context(tmp_path))
    assert counts == {"post": 1, "get": 2}
    assert result["usage"]["image_count"] == 1
    assert "No text" in result["message"]


@pytest.mark.asyncio
async def test_bad_download_does_not_leave_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.bailian._check_url", lambda url: url)
    target = tmp_path / "out.jpg"
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"not an image"))) as client:
        with pytest.raises(UnidentifiedImageError):
            await download_image(client, "https://example.com/out.jpg", target)
    assert not target.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"imageUrl": "x.png", "sourceLang": "en", "targetLang": "en"},
    {"imageUrl": "x.png", "targetLang": "auto"}, {"imageUrl": "x.png", "provider": "openai"},
    {"imageUrl": "x.png", "model": "gpt-image-1"}, {"imageUrl": "../outside.png"}])
async def test_image_validation_fails_before_network(tmp_path, config):
    with pytest.raises(NodeExecutionError):
        await ImageTranslateNodeExecutor().execute(FlowNode(id="translate", type="image_translate", config=config),
            {"input": {}}, context(tmp_path))


@pytest.mark.asyncio
async def test_image_mock_upstream_is_explicit(tmp_path):
    result = await ImageTranslateNodeExecutor().execute(FlowNode(id="translate", type="image_translate",
        config={"provider": "mock"}), {"outputs": {"img": {"imageUrl": "/files/old.png"}}}, context(tmp_path))
    assert result["mock"] is True and "未翻译原图" in result["message"]


@pytest.fixture
def client(monkeypatch):
    live._TICKETS.clear()
    live._ACTIVE.clear()
    monkeypatch.setattr(live, "get_settings", lambda: Settings(_env_file=None, mock_mode="never", dashscope_api_key=""))
    with TestClient(app) as client:
        yield client
    assert not live._ACTIVE
    live._TICKETS.clear()


HEADERS = {"X-Internal-Token": "agent-flow-internal"}


def new_ticket(client, **config):
    response = client.post("/v1/translations/realtime/sessions", headers=HEADERS,
        json={"userId": 1, "provider": "mock", **config})
    assert response.status_code == 200, response.text
    return response.json()["data"]["ticket"]


def test_live_create_requires_internal_auth_and_real_credentials(client):
    assert client.post("/v1/translations/realtime/sessions", json={"userId": 1}).status_code == 403
    assert client.post("/v1/translations/realtime/sessions", headers=HEADERS, json={"userId": 1}).status_code == 400
    response = client.post("/v1/translations/realtime/sessions", headers=HEADERS, json={"userId": 1,
        "apiKey": "sk-fake", "apiHost": "attacker.example"})
    assert response.status_code == 400 and "sk-fake" not in response.text


def test_mock_ticket_is_one_use_and_never_in_url(client):
    ticket = new_ticket(client)
    with client.websocket_connect("/v1/translations/realtime/ws", headers=HEADERS) as ws:
        ws.send_json({"type": "connect", "ticket": ticket})
        assert ws.receive_json()["type"] == "session.ready"
        ws.send_json({"type": "audio", "audio": base64.b64encode(b"\0\0" * 1600).decode()})
        ws.send_json({"type": "finish"})
        assert "[mock]" in ws.receive_json()["text"]
        assert ws.receive_json()["type"] == "session.finished"
    with client.websocket_connect("/v1/translations/realtime/ws", headers=HEADERS) as ws:
        ws.send_json({"type": "connect", "ticket": ticket})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_expired_ticket_rejected(client):
    ticket = new_ticket(client)
    live._TICKETS[ticket].expires = time.monotonic() - 1
    assert live.consume_ticket(ticket) is None


@pytest.mark.parametrize("payload", [{"type": "audio", "audio": "!"}, {"type": "audio", "audio": "AQ=="},
    {"type": "audio", "audio": ""}, {"type": "response.create"}, [], {"type": "audio", "audio": "A" * 70000}])
def test_audio_validation(payload):
    with pytest.raises((ValueError, TypeError)):
        live.audio_message(json.dumps(payload))


def test_live_protocol_is_38_not_omni_or_35():
    request = live.RealtimeRequest(userId=1, targetLang="ja", outputAudio=False)
    session = live.session_update(request)["session"]
    assert session["translation"]["language"] == "ja" and session["output_modalities"] == ["text"]
    assert "modalities" not in session and "input_audio_transcription" not in session
    assert live.normalize_event({"type": "response.audio_transcript.delta", "delta": "Hello"})["delta"] == "Hello"
    assert live.normalize_event({"type": "response.audio_transcript.done", "transcript": "Hello"})["text"] == "Hello"
    assert live.normalize_event({"type": "response.done", "response": {"usage": {"total_tokens": 50}}})["usage"]["total_tokens"] == 50


def test_upstream_waits_for_ready_and_drains_after_finish(client, monkeypatch):
    class Upstream:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.queue.put_nowait({"type": "session.created"})
            self.sent = []
            self.closed = False
        async def recv(self):
            return json.dumps(await self.queue.get())
        async def send(self, raw):
            data = json.loads(raw)
            self.sent.append(data)
            if data["type"] == "session.update":
                self.queue.put_nowait({"type": "session.updated"})
            if data["type"] == "session.finish":
                self.queue.put_nowait({"type": "response.text.delta", "item_id": "1", "delta": "Hello"})
                self.queue.put_nowait({"type": "response.text.done", "item_id": "1", "text": "Hello"})
                self.queue.put_nowait({"type": "session.finished"})
    upstream = Upstream()
    @asynccontextmanager
    async def fake_connect(url, **kwargs):
        assert url.startswith("wss://demo.cn-beijing.maas.aliyuncs.com/")
        assert kwargs["additional_headers"]["Authorization"] == "Bearer sk-test-secret"
        try:
            yield upstream
        finally:
            upstream.closed = True
    monkeypatch.setattr(live, "connect", fake_connect)
    ticket = new_ticket(client, provider="qwen", apiKey="sk-test-secret", apiHost="demo.cn-beijing.maas.aliyuncs.com")
    with client.websocket_connect("/v1/translations/realtime/ws", headers=HEADERS) as ws:
        ws.send_json({"type": "connect", "ticket": ticket})
        assert ws.receive_json()["type"] == "session.ready"
        ws.send_json({"type": "audio", "audio": base64.b64encode(b"\0\0" * 1600).decode()})
        ws.send_json({"type": "finish"})
        assert ws.receive_json()["type"] == "translation.delta"
        assert ws.receive_json()["text"] == "Hello"
        assert ws.receive_json()["type"] == "session.finished"
    assert [event["type"] for event in upstream.sent] == ["session.update", "input_audio_buffer.append", "session.finish"]
    assert upstream.closed
