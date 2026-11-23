from __future__ import annotations

import pytest

from app.errors import BizError
from app.flow import count_nodes, fingerprint, validate, validate_structure
from app.scoring import cosine, gram_counts, hybrid, lexical_ceiling, lexical_score


def flow(nodes, edges=None):
    return {"nodes": nodes, "edges": edges or []}


def test_validate_accepts_simple_chain():
    data = flow(
        [{"id": "a", "type": "input"}, {"id": "b", "type": "output"}],
        [{"source": "a", "target": "b"}],
    )
    validate(data)
    assert count_nodes(data) == 2


def test_validate_rejects_empty_cycle_and_multiple_entries():
    with pytest.raises(BizError):
        validate(flow([]))
    with pytest.raises(BizError):
        validate(flow([{"id": "a", "type": "x"}, {"id": "b", "type": "x"}],
                      [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]))
    with pytest.raises(BizError):
        validate(flow([{"id": "a", "type": "x"}, {"id": "b", "type": "x"}], []))


def test_validate_structure_allows_blank_canvas_and_rejects_bad_edge():
    validate_structure(flow([]))
    with pytest.raises(BizError):
        validate_structure(flow([{"id": "a", "type": "x"}], [{"source": "a", "target": "missing"}]))


def test_condition_branch_targets_are_edges():
    data = flow(
        [
            {"id": "c", "type": "condition", "config": {"trueBranch": "t", "falseBranch": "f"}},
            {"id": "t", "type": "output"},
            {"id": "f", "type": "output"},
        ]
    )
    validate(data)


def test_router_targets_and_missing_branch():
    data = flow([{"id": "r", "type": "llm_router", "config": {"routes": '[{"target":"a"}]', "fallbackTarget": "b"}},
                 {"id": "a", "type": "output"}, {"id": "b", "type": "output"}])
    validate(data)
    with pytest.raises(BizError):
        validate(flow([{"id": "r", "type": "llm_router", "config": {}}]))


def test_fingerprint_is_order_insensitive_but_content_sensitive():
    payload = {
        "workflowId": "1",
        "userId": 1,
        "input": {"b": 2, "a": 1},
        "providers": {},
        "mcpServers": {},
        "flow": {"nodes": [{"id": "a", "type": "input", "config": {}}], "edges": []},
        "options": {"mock": True},
    }
    first = fingerprint(payload)
    reordered = {**payload, "input": {"a": 1, "b": 2}}
    assert first == fingerprint(reordered)
    changed = {**payload, "input": {"a": 2, "b": 2}}
    assert first != fingerprint(changed)
    assert first.startswith("v2:")
    assert len(first) == 67


def test_scoring_prefers_self_match():
    query = "退款多久到账"
    target = "退款会在审核通过后到账"
    other = "今天天气很好"
    query_grams = gram_counts(query)
    grams = [gram_counts(target), gram_counts(other)]
    frequency = {gram: sum(1 for item in grams if gram in item) for gram in query_grams}
    ceiling = lexical_ceiling(query_grams, 2, frequency)
    assert lexical_score(query_grams, grams[0], 2, frequency, ceiling) > lexical_score(
        query_grams, grams[1], 2, frequency, ceiling
    )
    assert cosine([1, 0], [1, 0]) == 1
    assert cosine([1, 0], [0, 1]) == 0
    assert hybrid(0.8, 0.2) == pytest.approx(0.62)
