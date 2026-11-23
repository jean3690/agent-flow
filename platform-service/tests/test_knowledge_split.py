from __future__ import annotations

from app.services.knowledge import split


def test_split_respects_size_and_overlap():
    text = "第一句。第二句！第三句？" * 20
    chunks = split(text, 40, 10)
    assert chunks
    assert all(len(chunk) <= 40 for chunk in chunks)
    assert "".join(chunks).startswith("第一句")


def test_split_handles_empty_and_newlines():
    assert split("", 100, 10) == []
    assert split(None, 100, 10) == []
    chunks = split("a\r\nbbbb\nccccc", 6, 0)
    assert all(chunk.strip() for chunk in chunks)


def test_split_starts_at_sentence_boundary_after_overlap():
    text = "一二三四五。六七八九十。" * 5
    chunks = split(text, 12, 4)
    assert all(not chunk.startswith("。") for chunk in chunks)
