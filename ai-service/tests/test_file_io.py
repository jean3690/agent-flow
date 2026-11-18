import asyncio

import pytest

from app.config import Settings
from app.core.events import EventBus
from app.core.errors import NodeExecutionError
from app.core.storage import (
    FileNotFoundStorageError,
    StorageError,
    delete_file,
    list_files,
    normalize_relative_path,
    read_text,
    resolve_existing,
    resolve_for_write,
    safe_upload_name,
    save_text,
    save_upload,
)
from app.graph.context import NodeContext
from app.nodes.file_nodes import (
    FileListNodeExecutor,
    FileNodeExecutor,
    FileReadNodeExecutor,
    FileWriteNodeExecutor,
)
from app.schemas.flow import Flow, FlowNode


def _settings(tmp_path) -> Settings:
    return Settings(file_dir=str(tmp_path / "files"), output_dir=str(tmp_path / "audio"))


def _context(tmp_path) -> NodeContext:
    return NodeContext(
        run_id="run-file",
        settings=_settings(tmp_path),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
    )


def _run(executor, node, state, ctx):
    return asyncio.run(executor.execute(node, state, ctx))


def test_normalize_relative_path_accepts_storage_and_url_refs():
    assert normalize_relative_path("reports/today.md") == "reports/today.md"
    assert normalize_relative_path("./reports//today.md") == "reports/today.md"
    assert normalize_relative_path("/files/reports/today.md") == "reports/today.md"
    assert normalize_relative_path("/api/files/reports/a%20b.txt") == "reports/a b.txt"
    assert normalize_relative_path("https://host/files/x/y.md") == "x/y.md"
    assert normalize_relative_path("a\\b\\c.txt") == "a/b/c.txt"


@pytest.mark.parametrize("ref", ["", "   ", "/etc/passwd", "../secret.txt", "a/../../b.txt", "a/./../b.txt"])
def test_normalize_relative_path_rejects_unsafe_refs(ref):
    with pytest.raises(StorageError):
        normalize_relative_path(ref)


def test_save_and_read_text_roundtrip(tmp_path):
    settings = _settings(tmp_path)
    metadata = save_text(settings, "你好 AgentFlow", name="notes/hello.md")

    assert metadata["path"] == "notes/hello.md"
    assert metadata["size"] == len("你好 AgentFlow".encode())
    assert metadata["url"] == "/files/notes/hello.md"

    result = read_text(settings, "/api/files/notes/hello.md")
    assert result["text"] == "你好 AgentFlow"
    assert result["charCount"] == len("你好 AgentFlow")
    assert result["truncated"] is False


def test_read_text_truncates_and_uses_encoding(tmp_path):
    settings = _settings(tmp_path)
    save_text(settings, "abcdef", name="a.txt", encoding="utf-8")

    truncated = read_text(settings, "a.txt", max_chars=3)
    assert truncated["text"] == "abc"
    assert truncated["truncated"] is True

    save_text(settings, "中文", name="gbk.txt", encoding="gbk")
    assert read_text(settings, "gbk.txt", encoding="gbk")["text"] == "中文"


def test_save_text_append_and_overwrite_guard(tmp_path):
    settings = _settings(tmp_path)
    save_text(settings, "第一行\n", name="log.txt")
    save_text(settings, "第二行\n", name="log.txt", append=True)
    assert read_text(settings, "log.txt")["text"] == "第一行\n第二行\n"

    with pytest.raises(StorageError):
        save_text(settings, "x", name="log.txt", overwrite=False, append=False)


def test_save_upload_keeps_name_and_deduplicates(tmp_path):
    settings = _settings(tmp_path)
    first = save_upload(settings, b"one", original_name="../../报告 2026.txt")
    second = save_upload(settings, b"two", original_name="报告 2026.txt")

    assert first["path"] == "报告 2026.txt"
    assert first["originalName"] == "报告 2026.txt"
    assert second["path"] != first["path"]
    assert second["path"].startswith("报告 2026-")
    assert (settings.files_dir / second["path"]).read_bytes() == b"two"


def test_safe_upload_name_handles_empty_and_long_names():
    assert safe_upload_name(None) == "upload.bin"
    assert safe_upload_name("C:\\temp\\a.txt") == "a.txt"
    long_name = safe_upload_name("x" * 200 + ".md")
    assert len(long_name) <= 120
    assert long_name.endswith(".md")


def test_list_files_filters_prefix_newest_first(tmp_path):
    settings = _settings(tmp_path)
    save_text(settings, "a", name="reports/a.md")
    save_text(settings, "b", name="reports/sub/b.md")
    save_text(settings, "c", name="other.md")

    all_items = list_files(settings)
    assert {item["path"] for item in all_items} == {"reports/a.md", "reports/sub/b.md", "other.md"}

    reports = list_files(settings, prefix="reports/")
    assert {item["path"] for item in reports} == {"reports/a.md", "reports/sub/b.md"}

    limited = list_files(settings, prefix="reports/", limit=1)
    assert len(limited) == 1 and limited[0]["path"] in {"reports/a.md", "reports/sub/b.md"}


def test_delete_file_prunes_empty_directory(tmp_path):
    settings = _settings(tmp_path)
    save_text(settings, "x", name="tmp/deep/file.txt")

    delete_file(settings, "tmp/deep/file.txt")
    assert not (settings.files_dir / "tmp").exists()
    with pytest.raises(FileNotFoundStorageError):
        resolve_existing(settings, "tmp/deep/file.txt")


def test_resolve_for_write_rejects_escape(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(StorageError):
        resolve_for_write(settings, "../outside.txt")
    with pytest.raises(StorageError):
        resolve_for_write(settings, "/absolute.txt")


def test_file_write_node_renders_path_and_content(tmp_path):
    ctx = _context(tmp_path)
    node = FlowNode(
        id="write",
        type="file_write",
        config={
            "path": "reports/{{input.date}}.md",
            "content": "# {{input.title}}\n\n{{input.body}}",
        },
    )
    state = {"input": {"date": "2026-11-04", "title": "周报", "body": "完成文件 IO"}}

    result = _run(FileWriteNodeExecutor(), node, state, ctx)

    assert result["path"] == "reports/2026-11-04.md"
    assert result["charCount"] == len(result["text"])
    saved = (ctx.settings.files_dir / result["path"]).read_text(encoding="utf-8")
    assert saved.startswith("# 周报")
    assert "完成文件 IO" in saved


def test_file_write_node_returns_upstream_content_when_content_empty(tmp_path):
    ctx = _context(tmp_path)
    node = FlowNode(id="write2", type="file_write", config={"path": "out.txt"})
    state = {
        "input": {},
        "executed": ["llm"],
        "outputs": {"llm": {"text": "上游结果"}},
    }

    result = _run(FileWriteNodeExecutor(), node, state, ctx)
    assert result["text"] == "上游结果"
    assert (ctx.settings.files_dir / "out.txt").read_text(encoding="utf-8") == "上游结果"


def test_file_read_node_reads_template_path_and_truncates(tmp_path):
    ctx = _context(tmp_path)
    save_text(ctx.settings, "0123456789", name="docs/a.txt")
    state = {"input": {"name": "a.txt"}}
    node = FlowNode(id="read", type="file_read", config={"path": "docs/{{input.name}}", "maxChars": 4})

    result = _run(FileReadNodeExecutor(), node, state, ctx)
    assert result["text"] == "0123"
    assert result["truncated"] is True
    assert result["path"] == "docs/a.txt"


def test_file_read_node_falls_back_to_upstream_file_ref(tmp_path):
    ctx = _context(tmp_path)
    save_text(ctx.settings, "来自上游", name="media/out.txt")
    state = {
        "input": {},
        "executed": ["img"],
        "outputs": {"img": {"url": "/files/media/out.txt"}},
    }

    result = _run(FileReadNodeExecutor(), FlowNode(id="read", type="file_read", config={}), state, ctx)
    assert result["text"] == "来自上游"


def test_file_read_node_rejects_traversal(tmp_path):
    ctx = _context(tmp_path)
    node = FlowNode(id="read", type="file_read", config={"path": "../secret.txt"})
    with pytest.raises(NodeExecutionError):
        _run(FileReadNodeExecutor(), node, {"input": {}}, ctx)


def test_file_list_node_returns_json_payload(tmp_path):
    ctx = _context(tmp_path)
    save_text(ctx.settings, "a", name="reports/a.md")
    save_text(ctx.settings, "b", name="reports/b.md")

    node = FlowNode(id="list", type="file_list", config={"prefix": "reports/", "limit": 10})
    result = _run(FileListNodeExecutor(), node, {"input": {}}, ctx)

    assert result["count"] == 2
    assert {item["path"] for item in result["files"]} == {"reports/a.md", "reports/b.md"}
    assert result["value"] == result["text"]


@pytest.mark.parametrize(
    "action,expected_text",
    [("write", "内容"), ("append", "内容"), ("read", "内容"), ("list", "")],
)
def test_generic_file_node_dispatches_actions(tmp_path, action, expected_text):
    ctx = _context(tmp_path)
    save_text(ctx.settings, "内容", name="generic.txt")
    node = FlowNode(id="file", type="file", config={"action": action, "path": "generic.txt", "content": "内容"})

    result = _run(FileNodeExecutor(), node, {"input": {}}, ctx)

    if action == "list":
        assert result["count"] == 1
    else:
        assert result["text"] == expected_text
