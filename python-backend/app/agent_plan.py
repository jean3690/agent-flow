from __future__ import annotations

import json
import logging
import math
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from . import llm_config_service
from .db import first_text, jdump, text_or_none, to_float, to_int
from .llm import normalize_provider
from .models import LLMGlobalConfig

logger = logging.getLogger("agentflow.agent_plan")

DEFAULT_EMBEDDING_MODEL = "doubao-embedding-vision"


@dataclass
class ResolvedAgentPlanConfig:
    config_id: Optional[int]
    provider: str
    api_url: Optional[str]
    api_key: Optional[str]
    model: Optional[str]
    embedding_model: Optional[str]
    image_model: Optional[str]
    video_model: Optional[str]
    memory_enabled: bool


def _node_config(db: Session, node_data: dict) -> Optional[LLMGlobalConfig]:
    return llm_config_service.get_by_id(db, node_data.get("configId"))


def resolve(db: Session, node_data: dict, capability: str) -> ResolvedAgentPlanConfig:
    node_global_config = _node_config(db, node_data)

    explicit_id = to_int(node_data.get("agentPlanConfigId"))
    explicit = llm_config_service.get_by_id(db, explicit_id) if explicit_id is not None else None

    if explicit is not None:
        global_config = explicit
    elif node_global_config is not None:
        global_config = node_global_config
    else:
        global_config = llm_config_service.get_default_config(db, "volcengine_agent_plan")

    node_model = text_or_none(node_data.get("model"))
    api_url = first_text(global_config.api_url if global_config else None, text_or_none(node_data.get("apiUrl")))
    api_key = first_text(global_config.api_key if global_config else None, text_or_none(node_data.get("apiKey")))
    provider = normalize_provider(
        first_text(
            global_config.provider if global_config else None,
            text_or_none(node_data.get("provider")),
            "volcengine_agent_plan",
        )
    )

    language_model = first_text(node_model, global_config.model if global_config else None)
    embedding_model = first_text(
        node_model if capability == "embedding" else None,
        global_config.embedding_model if global_config else None,
        DEFAULT_EMBEDDING_MODEL,
    )
    image_model = first_text(
        node_model if capability == "image" else None,
        global_config.image_model if global_config else None,
        language_model,
    )
    video_model = first_text(
        node_model if capability == "video" else None,
        global_config.video_model if global_config else None,
        language_model,
    )

    if capability in ("embedding", "memory", "knowledge"):
        effective_model = embedding_model
    elif capability == "image":
        effective_model = image_model
    elif capability == "video":
        effective_model = video_model
    else:
        effective_model = language_model

    return ResolvedAgentPlanConfig(
        config_id=global_config.id if global_config else None,
        provider=provider,
        api_url=api_url,
        api_key=api_key,
        model=effective_model,
        embedding_model=embedding_model,
        image_model=image_model,
        video_model=video_model,
        memory_enabled=bool(global_config and (global_config.memory_enabled or 0) == 1),
    )


def _resolve_default_image_config(db: Session, configured_provider: Optional[str]) -> Optional[LLMGlobalConfig]:
    if configured_provider:
        provider_default = llm_config_service.get_default_config(db, configured_provider)
        if provider_default is not None:
            return provider_default
    default_agent_plan = llm_config_service.get_default_config(db, "volcengine_agent_plan")
    if default_agent_plan is not None:
        return default_agent_plan
    return llm_config_service.get_default_config(db, "step")


def resolve_image_config(db: Session, node_data: dict) -> ResolvedAgentPlanConfig:
    global_config = _node_config(db, node_data)
    configured_provider = normalize_provider(text_or_none(node_data.get("provider")))
    if global_config is None:
        global_config = _resolve_default_image_config(db, configured_provider)

    node_model = text_or_none(node_data.get("model"))
    api_url = first_text(global_config.api_url if global_config else None, text_or_none(node_data.get("apiUrl")))
    api_key = first_text(global_config.api_key if global_config else None, text_or_none(node_data.get("apiKey")))
    provider = normalize_provider(
        first_text(
            global_config.provider if global_config else None,
            configured_provider,
            "volcengine_agent_plan",
        )
    )
    language_model = first_text(node_model, global_config.model if global_config else None)
    image_model = first_text(
        node_model,
        global_config.image_model if global_config else None,
        language_model,
    )
    return ResolvedAgentPlanConfig(
        config_id=global_config.id if global_config else None,
        provider=provider,
        api_url=api_url,
        api_key=api_key,
        model=image_model,
        embedding_model=global_config.embedding_model if global_config else None,
        image_model=image_model,
        video_model=global_config.video_model if global_config else None,
        memory_enabled=bool(global_config and (global_config.memory_enabled or 0) == 1),
    )


def resolve_knowledge_config(db: Session, config_id: Any, model_override: Optional[str]) -> ResolvedAgentPlanConfig:
    global_config = llm_config_service.get_by_id(db, config_id)
    embedding_model = first_text(
        model_override,
        global_config.embedding_model if global_config else None,
        DEFAULT_EMBEDDING_MODEL,
    )
    return ResolvedAgentPlanConfig(
        config_id=to_int(config_id),
        provider=normalize_provider(
            first_text(global_config.provider if global_config else None, "volcengine_agent_plan")
        ),
        api_url=global_config.api_url if global_config else None,
        api_key=global_config.api_key if global_config else None,
        model=embedding_model,
        embedding_model=embedding_model,
        image_model=global_config.image_model if global_config else None,
        video_model=global_config.video_model if global_config else None,
        memory_enabled=bool(global_config and (global_config.memory_enabled or 0) == 1),
    )


def validate_api_config(config: ResolvedAgentPlanConfig, node_name: str) -> None:
    if not (config.api_url and config.api_key and config.model):
        raise ValueError(f"{node_name} 节点缺少有效的 Agent Plan 配置，请选择全局配置或填写 API 信息")


def _normalize_base_url(api_url: Optional[str]) -> str:
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


def _first_text(*values: Any) -> Optional[str]:
    return first_text(*values)


def _find_string(payload: Any, keys: tuple[str, ...]) -> Optional[str]:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        for value in payload.values():
            found = _find_string(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_string(item, keys)
            if found:
                return found
    return None


class VolcengineAgentPlanClient:
    def _post(self, config: ResolvedAgentPlanConfig, path: str, body: dict) -> dict:
        url = _normalize_base_url(config.api_url) + path
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {config.api_key}"}
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            response = client.post(url, json=body, headers=headers)
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"Agent Plan 调用失败, HTTP {response.status_code}: {response.text[:800]}")
        return response.json()

    def _get(self, config: ResolvedAgentPlanConfig, path: str) -> dict:
        url = _normalize_base_url(config.api_url) + path
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {config.api_key}"}
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            response = client.get(url, headers=headers)
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"Agent Plan 调用失败, HTTP {response.status_code}: {response.text[:800]}")
        return response.json()

    def create_embedding(self, config: ResolvedAgentPlanConfig, text: str) -> list[float]:
        payload = self._post(config, "/embeddings", {"model": config.model, "input": text})
        data = payload.get("data") or []
        if not data:
            return []
        embedding = (data[0] or {}).get("embedding")
        if not isinstance(embedding, list):
            return []
        return [float(value) for value in embedding if isinstance(value, (int, float))]

    def generate_image(
        self,
        config: ResolvedAgentPlanConfig,
        prompt: str,
        reference_image_url: Optional[str],
        size: Optional[str],
        count: int,
        negative_prompt: Optional[str],
        style: Optional[str],
    ) -> dict:
        body: dict[str, Any] = {
            "model": config.model,
            "prompt": prompt,
            "response_format": "url",
            "output_format": "png",
            "watermark": False,
            "stream": False,
        }
        if size:
            body["size"] = size
        if reference_image_url:
            body["image"] = reference_image_url
        payload = self._post(config, "/images/generations", body)
        urls: list[str] = []
        for item in payload.get("data") or []:
            if isinstance(item, dict):
                url = item.get("url")
                if url:
                    urls.append(url)
        return {"imageUrls": urls, "metadata": payload}

    def create_video_task(
        self,
        config: ResolvedAgentPlanConfig,
        prompt: str,
        reference_image_url: Optional[str],
        duration: int,
        resolution: Optional[str],
        ratio: Optional[str],
        camera_motion: Optional[str],
    ) -> Optional[str]:
        content: list[dict] = [{"type": "text", "text": prompt}]
        if reference_image_url:
            content.append({"type": "image_url", "image_url": {"url": reference_image_url}})
        body: dict[str, Any] = {
            "model": config.model,
            "content": content,
            "generate_audio": True,
            "duration": duration,
            "watermark": False,
        }
        if resolution:
            body["resolution"] = resolution
        if ratio:
            body["ratio"] = ratio
        payload = self._post(config, "/contents/generations/tasks", body)
        return _first_text(payload.get("id"), payload.get("task_id"), payload.get("taskId"))

    def get_video_task(self, config: ResolvedAgentPlanConfig, task_id: str) -> dict:
        payload = self._get(config, f"/contents/generations/tasks/{task_id}")
        return {
            "status": _first_text(payload.get("status"), payload.get("task_status"), "running"),
            "videoUrl": _find_string(payload, ("video_url", "videoUrl", "url")),
            "coverUrl": _find_string(payload, ("last_frame_url", "cover_url", "coverUrl", "poster_url")),
            "raw": payload,
        }


agent_plan_client = VolcengineAgentPlanClient()


def cosine(left: Optional[list[float]], right: Optional[list[float]]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for index in range(size):
        l_value = float(left[index])
        r_value = float(right[index])
        dot += l_value * r_value
        left_norm += l_value * l_value
        right_norm += r_value * r_value
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def split_tags(tag_text: Optional[str]) -> list[str]:
    if not tag_text:
        return []
    return [part for part in re.split(r"[,，\s]+", tag_text.strip()) if part]


class AgentMemoryService:
    def __init__(self) -> None:
        self._records: list[dict] = []
        self._lock = threading.Lock()

    def write(
        self,
        content: str,
        memory_type: str,
        scope: str,
        tags: Optional[list[str]],
        source: Optional[str],
        embedding: Optional[list[float]],
        embedding_model: Optional[str],
    ) -> dict:
        record = {
            "id": uuid.uuid4().hex,
            "scope": scope or "workflow",
            "memoryType": memory_type or "fact",
            "content": content,
            "tags": list(tags or []),
            "source": source,
            "embedding": list(embedding or []),
            "embeddingModel": embedding_model,
        }
        with self._lock:
            self._records.append(record)
        return {"memoryId": record["id"], "scope": record["scope"], "stored": True}

    def retrieve(
        self,
        query: str,
        scope: str,
        tags: Optional[list[str]],
        query_embedding: Optional[list[float]],
        top_k: int,
    ) -> dict:
        with self._lock:
            records = list(self._records)
        matches: list[dict] = []
        for record in records:
            if scope and record["scope"] != scope:
                continue
            if tags and not set(tags).issubset(set(record["tags"])):
                continue
            score = cosine(query_embedding, record["embedding"])
            if score == 0 and query and query in record["content"]:
                score = 0.5
            if score <= 0:
                continue
            matches.append(
                {
                    "memoryId": record["id"],
                    "scope": record["scope"],
                    "memoryType": record["memoryType"],
                    "content": record["content"],
                    "tags": record["tags"],
                    "source": record["source"],
                    "score": score,
                }
            )
        matches.sort(key=lambda item: item["score"], reverse=True)
        matches = matches[: max(1, top_k)]
        context = "\n".join(f"- {item['content']}" for item in matches)
        return {
            "memories": matches,
            "context": context,
            "citations": [item["memoryId"] for item in matches],
        }

    def split_tags(self, tag_text: Optional[str]) -> list[str]:
        return split_tags(tag_text)


memory_service = AgentMemoryService()
