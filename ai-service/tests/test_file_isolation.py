import base64

import httpx
import pytest

from app.api import executions, files, internal_auth
from app.config import Settings
from app.core.errors import NodeExecutionError
from app.core.events import EventBus
from app.core.storage import (
    FileNotFoundStorageError,
    StorageError,
    delete_file,
    legacy_storage,
    list_files,
    model_image_reference,
    read_text,
    save_text,
    user_storage,
)
from app.graph.context import NodeContext
from app.main import app
from app.nodes.control_nodes import ForeachNodeExecutor, SubflowNodeExecutor
from app.nodes.file_nodes import FileListNodeExecutor, FileReadNodeExecutor, FileWriteNodeExecutor
from app.nodes.image_node import ImageNodeExecutor
from app.nodes.tts_node import TtsNodeExecutor
from app.nodes.video_node import VideoNodeExecutor
from app.schemas.flow import Flow, FlowNode


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, mock_mode="always", file_dir=str(tmp_path / "files"),
                    output_dir=str(tmp_path / "media"), internal_token="unit-internal")


@pytest.fixture
async def client(settings, monkeypatch):
    for module in (files, executions, internal_auth):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def headers(user=1, legacy=False):
    result = {"X-Internal-Token": "unit-internal", "X-Storage-User-Id": str(user)}
    if legacy:
        result["X-Storage-Legacy"] = "true"
    return result


@pytest.mark.parametrize("method,path", [
    ("GET", "/v1/files"), ("GET", "/files/private.txt"), ("GET", "/v1/files/private.txt/meta"),
    ("GET", "/v1/files/private.txt/text"), ("POST", "/v1/files/text"), ("DELETE", "/v1/files/private.txt"),
])
async def test_all_file_routes_reject_missing_internal_token(client, method, path):
    response = await client.request(method, path, json={"name": "private.txt", "content": "forged"},
                                    headers={"X-Storage-User-Id": "1"})
    assert response.status_code == 403


async def test_same_named_files_are_isolated_across_read_list_delete_and_upload(client, settings):
    one = await client.post("/v1/files/text", json={"name": "reports/a.txt", "content": "user-one"}, headers=headers(1))
    two = await client.post("/v1/files/text", json={"name": "reports/a.txt", "content": "user-two"}, headers=headers(2))
    assert one.json()["data"]["path"] == two.json()["data"]["path"] == "reports/a.txt"
    assert one.json()["data"]["url"] == "/files/users/1/reports/a.txt"
    assert two.json()["data"]["url"] == "/files/users/2/reports/a.txt"
    assert (await client.get("/files/users/1/reports/a.txt", headers=headers(2))).status_code == 404
    response = await client.get("/files/reports/a.txt", headers=headers(2))
    assert response.text == "user-two"
    assert response.headers["cache-control"] == "private, no-store"
    items = (await client.get("/v1/files", headers=headers(2))).json()["data"]
    assert [item["url"] for item in items] == ["/files/users/2/reports/a.txt"]
    assert (await client.delete("/v1/files/users/1/reports/a.txt", headers=headers(2))).status_code == 404
    assert read_text(user_storage(settings, 1), "reports/a.txt")["text"] == "user-one"
    upload = await client.post("/v1/files?name=reports/a.txt", content=b"another", headers={**headers(2), "Content-Type": "application/octet-stream"})
    assert upload.status_code == 200 and upload.json()["data"]["path"] != "reports/a.txt"
    assert read_text(user_storage(settings, 1), "reports/a.txt")["text"] == "user-one"


@pytest.mark.parametrize("identity", [{}, {"X-Storage-User-Id": "0"}, {"X-Storage-User-Id": "-1"}])
async def test_missing_or_invalid_storage_identity_never_falls_back_to_shared_root(client, identity):
    assert (await client.get("/v1/files", headers={"X-Internal-Token": "unit-internal", **identity})).status_code == 403


async def test_legacy_files_are_read_only_and_managed_user_directories_are_hidden(client, settings):
    (settings.files_dir / "old.txt").write_text("historical")
    save_text(user_storage(settings, 1), "private", name="secret.txt")
    assert (await client.get("/files/old.txt", headers=headers(1))).status_code == 404
    response = await client.get("/files/legacy/old.txt", headers=headers(1, legacy=True))
    assert response.text == "historical"
    items = (await client.get("/v1/files", headers=headers(1, legacy=True))).json()["data"]
    assert [item["url"] for item in items] == ["/files/legacy/old.txt"]
    assert (await client.get("/files/legacy/.users/1/secret.txt", headers=headers(1, legacy=True))).status_code == 404
    assert (await client.post("/v1/files/text", json={"name": "old.txt", "content": "changed"}, headers=headers(1, legacy=True))).status_code == 400
    assert (await client.delete("/v1/files/legacy/old.txt", headers=headers(1, legacy=True))).status_code == 400
    assert read_text(legacy_storage(settings), "old.txt")["text"] == "historical"


@pytest.mark.parametrize("name", ["../outside.txt", "%2e%2e/outside.txt", "a/../../outside.txt", ".users/2/a.txt", "users/2/a.txt", "legacy/a.txt"])
async def test_unsafe_or_cross_scope_writes_do_not_create_files(client, settings, name):
    response = await client.post("/v1/files/text", json={"name": name, "content": "forged"}, headers=headers(1))
    assert response.status_code in {400, 404}
    assert list_files(user_storage(settings, 1)) == []


async def test_active_content_is_an_attachment_and_not_publicly_cached(client):
    await client.post("/v1/files/text", json={"name": "danger.html", "content": "<script>alert(1)</script>"}, headers=headers())
    response = await client.get("/files/users/1/danger.html", headers=headers())
    assert response.headers["content-type"] == "application/octet-stream"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]


@pytest.mark.parametrize("operation", ["read", "write", "delete", "list"])
def test_symlinks_cannot_escape_or_leak_metadata(settings, tmp_path, operation):
    owner = user_storage(settings, 1)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (owner.files_dir / "link.txt").symlink_to(outside)
    if operation == "list":
        assert list_files(owner) == []
    else:
        with pytest.raises(StorageError):
            if operation == "read": read_text(owner, "link.txt")
            elif operation == "write": save_text(owner, "overwrite", name="link.txt")
            else: delete_file(owner, "link.txt")
    assert outside.read_text() == "secret"


def test_scope_root_itself_cannot_be_replaced_by_another_users_symlink(settings):
    one, two = user_storage(settings, 1), user_storage(settings, 2)
    save_text(two, "private", name="a.txt")
    path = one.files_dir
    path.rmdir()
    path.symlink_to(two.files_dir, target_is_directory=True)
    with pytest.raises(StorageError):
        read_text(one, "a.txt")


@pytest.mark.parametrize("executor,type", [
    (FileReadNodeExecutor(), "file_read"), (FileWriteNodeExecutor(), "file_write"),
    (FileListNodeExecutor(), "file_list"), (ImageNodeExecutor(), "image_generate"),
    (TtsNodeExecutor(), "tts"), (VideoNodeExecutor(), "video_generate"),
])
async def test_file_and_media_nodes_require_explicit_user_context(settings, executor, type):
    (settings.files_dir / "a.txt").write_text("legacy-secret")
    ctx = NodeContext(run_id="r", settings=settings, flow=Flow(), bus=EventBus())
    with pytest.raises((StorageError, NodeExecutionError)):
        await executor.execute(FlowNode(id="n", type=type, config={"path": "a.txt", "provider": "mock"}), {"input": {}}, ctx)
    assert read_text(legacy_storage(settings), "a.txt")["text"] == "legacy-secret"


@pytest.mark.parametrize("operation", ["read", "write", "list", "delete"])
def test_storage_helpers_themselves_reject_unbound_global_settings(settings, operation):
    (settings.files_dir / "old.txt").write_text("historical")
    with pytest.raises(StorageError):
        if operation == "read": read_text(settings, "old.txt")
        elif operation == "write": save_text(settings, "overwrite", name="old.txt")
        elif operation == "list": list_files(settings)
        else: delete_file(settings, "old.txt")
    assert (settings.files_dir / "old.txt").read_text() == "historical"


async def test_media_generation_and_model_image_conversion_use_only_the_owner(settings):
    ctx = NodeContext(run_id="r", settings=settings, flow=Flow(), bus=EventBus(), user_id=1)
    image = await ImageNodeExecutor().execute(FlowNode(id="img", type="image_generate", config={"provider": "mock"}), {"input": {}}, ctx)
    assert image["imageUrl"].startswith("/files/users/1/")
    encoded = model_image_reference(ctx.storage, image["imageUrl"])
    assert base64.b64decode(encoded.split(",", 1)[1]).startswith(b"\x89PNG")
    with pytest.raises(FileNotFoundStorageError):
        model_image_reference(user_storage(settings, 2), image["imageUrl"])


@pytest.mark.parametrize("kind", ["subflow", "foreach"])
async def test_embedded_flows_inherit_file_owner(settings, kind):
    child = Flow(nodes=[FlowNode(id="write", type="file_write", config={"path": "reports/{{input.item}}.txt", "content": "{{input.item}}"})])
    ctx = NodeContext(run_id="r", settings=settings, flow=Flow(), bus=EventBus(), user_id=7, subflows={"9": child})
    if kind == "subflow":
        await SubflowNodeExecutor().execute(FlowNode(id="s", type=kind, config={"workflowId": 9, "input": {"item": "one"}}), {"input": {}}, ctx)
    else:
        await ForeachNodeExecutor().execute(FlowNode(id="s", type=kind, config={"bodyWorkflowId": 9, "items": ["one"]}), {"input": {}}, ctx)
    assert read_text(user_storage(settings, 7), "reports/one.txt")["text"] == "one"
    assert list_files(user_storage(settings, 8)) == []


async def test_forged_execution_identity_and_cancel_require_internal_token(client):
    payload = {"runId": "forged", "userId": 1, "flow": {"nodes": [{"id": "read", "type": "file_read", "config": {"path": "private.txt"}}], "edges": []}}
    assert (await client.post("/v1/executions", json=payload)).status_code == 403
    assert (await client.post("/v1/executions/forged/cancel")).status_code == 403
    response = await client.post("/v1/executions", json=payload, headers={"X-Internal-Token": "unit-internal"})
    assert response.status_code == 200 and "run_failed" in response.text
