"""Against a running stack: image workflow + authenticated ticket + Java/Python WS.

Explicit mock only. No vendor credentials or microphone recordings are needed.
Run with ai-service/.venv/bin/python e2e/verify_translations.py.
"""
import asyncio
import base64
import json

import httpx
from websockets.asyncio.client import connect

from smoke import BASE, ADMIN, PASSWORD, api, create_workflow, run_sse, run_status, node_output


async def main():
    _, body = api("POST", "/api/auth/login", payload={"username": ADMIN, "password": PASSWORD})
    token = body["data"]["token"]
    flow = {"nodes": [
        {"id": "in", "type": "input", "config": {}},
        {"id": "translate", "type": "image_translate", "config": {"provider": "mock", "imageUrl": "https://example.com/image.png"}},
        {"id": "out", "type": "output", "config": {}}
    ], "edges": [{"id": "1", "source": "in", "target": "translate"}, {"id": "2", "source": "translate", "target": "out"}]}
    wid = create_workflow(token, flow, "图片翻译回归")
    assert wid
    try:
        events = run_sse(token, wid, {"input": {}})
        output = node_output(events, "translate")
        assert run_status(events) == "success" and output["mock"]
        async with httpx.AsyncClient() as client:
            image = await client.get(BASE + "/api" + output["imageUrl"])
            assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
        print("PASS image translation workflow and persisted media")
    finally:
        api("DELETE", f"/api/workflows/{wid}", token)
    status, _ = api("POST", "/api/translations/realtime/sessions", payload={"provider": "mock"})
    assert status == 401
    print("PASS live session rejects unauthenticated requests")
    status, body = api("POST", "/api/translations/realtime/sessions", token, {"provider": "mock", "targetLang": "en"})
    assert status == 200 and "apiKey" not in json.dumps(body)
    ticket = body["data"]["ticket"]
    uri = BASE.replace("http", "ws", 1) + "/api/translations/realtime/ws"
    async with connect(uri, proxy=None) as ws:
        await ws.send(json.dumps({"type": "connect", "ticket": ticket}))
        ready = json.loads(await asyncio.wait_for(ws.recv(), 15))
        assert ready["type"] == "session.ready" and ready["mock"]
        await ws.send(json.dumps({"type": "audio", "audio": base64.b64encode(b"\0\0" * 1600).decode()}))
        await ws.send(json.dumps({"type": "finish"}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "translation.done"
        assert json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "session.finished"
    print("PASS Java -> Python live audio relay, finish and terminal event")
    async with connect(uri, proxy=None) as ws:
        await ws.send(json.dumps({"type": "connect", "ticket": ticket}))
        event = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert event["type"] == "error"
    print("PASS consumed ticket cannot be reused")


if __name__ == "__main__":
    asyncio.run(main())
