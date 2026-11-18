import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest

from agentflow import AgentFlowClient, ApiError

NL = chr(10)
Q = chr(34)


def make_client(handler):
    transport = httpx.MockTransport(handler)
    return AgentFlowClient("http://test", api_key="af_demo", transport=transport)


def test_auth_header_is_sent():
    captured = {}

    def handler(request):
        captured["key"] = request.headers.get("X-API-Key")
        return httpx.Response(200, json={"code": 0, "message": "ok", "data": {"id": 1}})

    client = make_client(handler)
    data = client.workflows.list()
    assert data == {"id": 1}
    assert captured["key"] == "af_demo"
    client.close()


def test_api_error_raised_on_nonzero_code():
    def handler(request):
        return httpx.Response(200, json={"code": 4010, "message": "bad key", "data": None})

    client = make_client(handler)
    with pytest.raises(ApiError):
        client.workflows.list()
    client.close()


def test_run_returns_aggregated_result():
    run_result = {
        "runId": "abc",
        "status": "SUCCESS",
        "outputs": {"text": "hi"},
        "nodeStatus": [],
        "elapsedMs": 12,
        "errorMessage": None,
    }

    def handler(request):
        assert request.url.path == "/api/workflows/5/run"
        assert request.method == "POST"
        return httpx.Response(200, json={"code": 0, "message": "ok", "data": run_result})

    client = make_client(handler)
    result = client.workflows.run(5, input={"topic": "x"})
    assert result["status"] == "SUCCESS"
    assert result["outputs"] == {"text": "hi"}
    client.close()


def test_execute_stream_parses_sse():
    sse_body = (
        "event: run_started" + NL
        + "data: {" + Q + "runId" + Q + ":" + Q + "r1" + Q + "}" + NL + NL
        + "event: run_finished" + NL
        + "data: {" + Q + "status" + Q + ":" + Q + "SUCCESS" + Q + "}" + NL + NL
    )

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse_body,
        )

    client = make_client(handler)
    events = list(client.workflows.execute_stream(5, input={}))
    assert [e[0] for e in events] == ["run_started", "run_finished"]
    assert events[1][1] == {"status": "SUCCESS"}
    client.close()


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_execute_stream_handles_multiline_json_and_default_event(newline):
    body = newline.join([
        "\ufeff: heartbeat", "", 'data: {"text":', 'data: "你好"}', "", "",
    ])
    with make_client(lambda request: httpx.Response(200, text=body)) as client:
        assert list(client.workflows.execute_stream(5)) == [("message", {"text": "你好"})]


@pytest.mark.parametrize("suffix", ["", "\n", "\r\n"])
def test_execute_stream_keeps_final_event_without_blank_line(suffix):
    body = 'event: run_finished\ndata: {"status":"SUCCESS"}' + suffix
    with make_client(lambda request: httpx.Response(200, text=body)) as client:
        assert list(client.workflows.execute_stream(5)) == [
            ("run_finished", {"status": "SUCCESS"}),
        ]


def test_execute_stream_reads_http_error_body_and_closes_response():
    class ErrorStream(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b'{"message":"bad key"}'

        def close(self):
            self.closed = True

    stream = ErrorStream()
    with make_client(lambda request: httpx.Response(401, stream=stream)) as client:
        with pytest.raises(ApiError, match="bad key") as exc:
            list(client.workflows.execute_stream(5))
        assert exc.value.code == 401
        assert stream.closed


def test_execute_stream_requests_sse_and_closes_on_early_exit():
    class EventStream(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b'event: run_started\ndata: {"runId":"r1"}\n\n'
            raise AssertionError("must not read the rest of the stream")

        def close(self):
            self.closed = True

    stream = EventStream()

    def handler(request):
        assert request.headers["Accept"] == "text/event-stream"
        assert request.headers["X-API-Key"] == "af_demo"
        return httpx.Response(200, stream=stream)

    with make_client(handler) as client:
        events = client.workflows.execute_stream(5)
        assert next(events) == ("run_started", {"runId": "r1"})
        events.close()
        assert stream.closed
