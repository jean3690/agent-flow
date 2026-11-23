from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import httpx

from app.core.bailian import MAX_IMAGE_BYTES, api_origin, download_image, provider_error, upload_image
from app.core.errors import NodeExecutionError
from app.core.storage import media_target, resolve_existing, scoped_relative_path, storage_url
from app.core.template import build_names, render
from app.core.web import _check_url
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.image_node import _placeholder_png
from app.nodes.registry import register
from app.schemas.flow import FlowNode


@register
class ImageTranslateNodeExecutor(NodeExecutor):
    type = "image_translate"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider = config.get("provider") or "qwen"
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        reference = render(str(config.get("imageUrl") or ""), names, strict=True).strip()
        if not reference:
            reference = next((str(out["imageUrl"]) for out in reversed(list((state.get("outputs") or {}).values()))
                              if isinstance(out, dict) and out.get("imageUrl")), "")
        source = str(config.get("sourceLang") or "auto").strip().lower()
        target_lang = str(config.get("targetLang") or "en").strip().lower()
        model = str(config.get("model") or "qwen-mt-image-2.0")
        api_key, base_url = ctx.credentials(provider)
        try:
            if provider not in {"qwen", "mock"}:
                raise ValueError("图片翻译仅支持百炼（qwen）或 mock")
            if not reference:
                raise ValueError("缺少图片地址，请选择文件或连接上游图片节点")
            if not target_lang or target_lang == "auto" or source == target_lang:
                raise ValueError("目标语种不能为空或 auto，且必须与源语种不同")
            if model != "qwen-mt-image-2.0":
                raise ValueError("此节点适配 qwen-mt-image-2.0，请勿填入视觉问答或图片生成模型")
            mock = ctx.mock_for(provider)
            storage = ctx.storage
            if reference.startswith(("/files/", "/api/files/")) or "://" not in reference:
                scoped_relative_path(storage, reference)
            filename = uuid.uuid4().hex + (".png" if mock else ".jpg")
            target = media_target(storage, filename)
            if mock:
                target.write_bytes(_placeholder_png("mock image translation"))
                message, usage, request_id = "模拟图片翻译：占位图片，未翻译原图", {}, ""
            else:
                if not api_key:
                    raise ValueError("百炼未配置 API Key")
                origin = api_origin(str(config.get("apiHost") or ctx.settings.dashscope_api_host), base_url)
                async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
                    image_url = reference
                    if reference.startswith(("/files/", "/api/files/")) or "://" not in reference:
                        path, _ = resolve_existing(storage, reference)
                        _validate_local_image(path)
                        image_url = await upload_image(client, origin, api_key, model, path)
                    elif not reference.startswith("oss://"):
                        await asyncio.to_thread(_check_url, reference)
                        if not reference.isascii():
                            raise ValueError("公网图片 URL 不能包含中文，请使用编码后的地址")
                    ext = {"config": {"imageSegment": bool(config.get("imageSegment", False))}}
                    if config.get("domainHint"):
                        ext["domainHint"] = render(str(config["domainHint"]), names, strict=True)
                    terms = config.get("terminologies") or []
                    if isinstance(terms, str):
                        terms = json.loads(terms)
                    if not isinstance(terms, list) or len(terms) > 50 or any(
                        not isinstance(term, dict) or not isinstance(term.get("src"), str)
                        or not isinstance(term.get("tgt"), str) for term in terms
                    ):
                        raise ValueError('术语须为最多 50 项的 JSON 数组，每项含 src 和 tgt')
                    if terms:
                        ext["terminologies"] = terms
                    body = {"model": model, "input": {"image_url": image_url, "source_lang": source,
                                                      "target_lang": target_lang, "ext": ext}}
                    headers = {"Authorization": f"Bearer {api_key}"}
                    if image_url.startswith("oss://"):
                        headers["X-DashScope-OssResourceResolve"] = "enable"
                    data = await _translate(client, origin, headers, body, bool(config.get("asyncMode", False)), ctx, node)
                    await download_image(client, data["output"]["image_url"], target)
                    message = str(data["output"].get("message") or "")
                    usage, request_id = data.get("usage") or {}, data.get("request_id") or ""
            return {"imageUrl": storage_url(storage, filename), "originalImageUrl": reference, "provider": provider,
                    "model": model, "sourceLang": source, "targetLang": target_lang, "message": message,
                    "usage": usage, "requestId": request_id, "mock": mock, "createdAt": int(time.time() * 1000)}
        except Exception as exc:
            message = str(exc).replace(api_key, "[REDACTED]") if api_key else str(exc)
            raise NodeExecutionError(node.id, f"图片翻译失败: {message[:600]}") from exc


def _validate_local_image(path) -> None:
    from PIL import Image
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("输入图片超过 100 MB 限制")
    with Image.open(path) as image:
        width, height = image.size
        if image.format not in {"JPEG", "PNG", "BMP", "PPM", "TIFF", "WEBP"}:
            raise ValueError("图片格式不受支持，请使用 JPG、PNG、BMP、TIFF 或 WEBP")
        if not (15 <= width <= 8192 and 15 <= height <= 8192 and 0.1 <= width / height <= 10):
            raise ValueError("图片宽高须为 15–8192 像素，宽高比须在 1:10–10:1 内")
        image.verify()


async def _translate(client, origin, headers, body, asynchronous, ctx, node):
    if asynchronous:
        headers = {**headers, "X-DashScope-Async": "enable"}
    response = await client.post(origin + "/api/v1/services/aigc/image2image/image-synthesis", json=body, headers=headers)
    response.raise_for_status()
    data = response.json()
    provider_error(data)
    if not asynchronous:
        return data
    task_id = data["output"]["task_id"]
    if not isinstance(task_id, str) or not all(char.isalnum() or char == "-" for char in task_id):
        raise ValueError("百炼返回非法任务 ID")
    ctx.emit("node_log", nodeId=node.id, level="info", message=f"图片翻译任务已提交: {task_id}")
    async with asyncio.timeout(300):
        while True:
            await asyncio.sleep(1)
            response = await client.get(origin + "/api/v1/tasks/" + task_id, headers=headers)
            response.raise_for_status()
            data = response.json()
            provider_error(data)
            output = data.get("output") or {}
            if output.get("task_status") == "SUCCEEDED":
                return data
            if output.get("task_status") not in {"PENDING", "RUNNING"}:
                raise ValueError(f"图片翻译任务 {output.get('task_status')}: {output.get('message', '')}")
