"""The editor reads node-definitions.json; ai-service serves node_catalog().

Both must stay in sync, otherwise the config drawer shows options that the
runtime does not know about (or vice versa). This test is the only automated
guard against changing one catalog and forgetting the other.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.catalog import node_catalog

_JSON_PATH = (
    Path(__file__).resolve().parents[2]
    / "platform-service/app/resources/node-definitions.json"
)


def _projection(node: dict) -> list[tuple]:
    """Stable shape: ignore legitimately different option labels / help text."""
    return [
        (
            field.get("key"),
            field.get("type"),
            field.get("dynamic"),
            field.get("providerField"),
            tuple((item.get("key"), item.get("type")) for item in field.get("fields", [])),
            field.get("hasValueKey"),
        )
        for field in node["configSchema"]
    ]


def _by_type() -> tuple[dict, dict]:
    python = {node["type"]: node for node in node_catalog()}
    with _JSON_PATH.open(encoding="utf-8") as handle:
        java = {node["type"]: node for node in json.load(handle)}
    return python, java


def test_catalogs_have_same_node_types():
    python, java = _by_type()
    assert set(python) == set(java)


def test_catalog_config_schema_shapes_match():
    python, java = _by_type()
    assert {t: _projection(node) for t, node in python.items()} == {
        t: _projection(node) for t, node in java.items()
    }


def test_every_node_declares_output_schema():
    for name, nodes in (("python", _by_type()[0]), ("json", _by_type()[1])):
        for node_type, node in nodes.items():
            meta = node["configSchema"][-1]
            assert meta["type"] == "outputSchema", f"{name}/{node_type} missing outputSchema"
            assert meta["fields"], f"{name}/{node_type} has empty output fields"


def test_llm_model_field_is_dynamic_with_identical_fallback():
    python, java = _by_type()

    def model_field(nodes: dict) -> dict:
        return next(f for f in nodes["llm"]["configSchema"] if f["key"] == "model")

    py_field, js_field = model_field(python), model_field(java)
    assert py_field["dynamic"] == js_field["dynamic"] == "providerModels"
    assert py_field["providerField"] == js_field["providerField"] == "provider"
    # Static options are the frontend's last-resort fallback: they must match exactly.
    assert py_field["options"] == js_field["options"]
    assert js_field["options"], "static fallback must not be empty"
