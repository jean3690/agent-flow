from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote, urlparse, urlunparse

import httpx

from .agent_plan import ResolvedAgentPlanConfig
from .db import first_text

logger = logging.getLogger("paiagent.media")

STEP_IMAGE_EDIT_2 = "step-image-edit-2"
STEP_2X_LARGE = "step-2x-large"
MAX_PROMPT_LENGTH = 512
MAX_NEGATIVE_PROMPT_LENGTH = 512
DEFAULT_FRAME_RATE = 24
DEFAULT_DURATION_SECONDS = 5
MAX_NUM_FRAMES = 441


def _strip_trailing_slash(value: str) -> str:
    return value.rstrip("/")


def _is_agnes(provider: Optional[str]) -> bool:
    return bool(provider) and provider.strip().lower() == "agnes"


def _rewrite_agnes_host(api_url: str) -> str:
    parsed = urlparse(api_url)
    if parsed.hostname and parsed.hostname.lower() == "api.agnes-ai.com":
        return urlunparse(parsed._replace(netloc=parsed.netloc.replace("api.agnes-ai.com", "apihub.agnes-ai.com")))
    return api_url


def _normalize_from_versioned_path(api_url: str) -> Optional[str]:
    parsed = urlparse(api_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    path = parsed.path or ""
    lower = path.lower()
    index = lower.find("/v1")
    if index < 0:
        return None
    return f"{parsed.scheme}://{parsed.netloc}{path[:index]}"


def _post_json(url: str, api_key: str, body: dict, error_prefix: str) -> dict:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        response = client.post(url, json=body, headers=headers)
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"{error_prefix}, endpoint={url}, HTTP {response.status_code}: {response.text[:800]}")
    return response.json()


def _get_json(url: str, api_key: str, error_prefix: str) -> dict:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        response = client.get(url, headers=headers)
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"{error_prefix}, endpoint={url}, HTTP {response.status_code}: {response.text[:800]}")
    return response.json()


class OpenAiCompatibleImageClient:
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
        body: dict[str, Any] = {"model": config.model, "prompt": self._normalize_prompt(prompt, negative_prompt, style)}
        if size:
            body["size"] = size.strip()
        if _is_agnes(config.provider):
            extra: dict[str, Any] = {"response_format": "url"}
            if reference_image_url:
                extra["image"] = [reference_image_url.strip()]
            body["extra_body"] = extra
        else:
            body["response_format"] = "url"
            body["n"] = max(1, min(count, 4))
            if reference_image_url:
                body["image"] = reference_image_url.strip()

        payload = _post_json(
            self._endpoint(config.api_url, config.provider), config.api_key or "", body, "OpenAI 兼容图片生成调用失败"
        )
        urls: list[str] = []
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if url:
                urls.append(url)
                continue
            b64 = item.get("b64_json")
            if b64:
                urls.append(f"data:image/png;base64,{b64}")
        return {"imageUrls": urls, "metadata": payload}

    def _endpoint(self, api_url: Optional[str], provider: Optional[str]) -> str:
        base = (api_url or "").strip() or "https://api.openai.com/v1"
        if _is_agnes(provider):
            base = _rewrite_agnes_host(base)
        base = _strip_trailing_slash(base)
        if base.endswith("/images/generations"):
            return base
        versioned = _normalize_from_versioned_path(base)
        if versioned is not None:
            return versioned + "/v1/images/generations"
        if not base.endswith("/v1"):
            base += "/v1"
        return base + "/images/generations"

    @staticmethod
    def _normalize_prompt(prompt: str, negative_prompt: Optional[str], style: Optional[str]) -> str:
        normalized = prompt.strip()
        if style:
            normalized += f"\nStyle: {style.strip()}"
        if negative_prompt:
            normalized += f"\nNegative prompt: {negative_prompt.strip()}"
        return normalized


class StepFunImageClient:
    def generate_image(
        self,
        config: ResolvedAgentPlanConfig,
        prompt: str,
        reference_image_url: Optional[str],
        size: Optional[str],
        count: int,
        negative_prompt: Optional[str],
        style: Optional[str],
        steps: int,
        cfg_scale: float,
        seed: int,
        text_mode: bool,
    ) -> dict:
        body: dict[str, Any] = {
            "model": config.model,
            "prompt": self._normalize_prompt(prompt, style),
            "response_format": "url",
            "n": max(1, min(count, 1)),
            "size": self._normalize_size(config.model, size),
            "steps": self._normalize_steps(config.model, steps),
            "cfg_scale": self._normalize_cfg_scale(config.model, cfg_scale),
        }
        if seed > 0:
            body["seed"] = seed
        if config.model == STEP_IMAGE_EDIT_2:
            body["text_mode"] = text_mode
            if negative_prompt:
                body["negative_prompt"] = negative_prompt.strip()[:MAX_NEGATIVE_PROMPT_LENGTH]

        payload = _post_json(
            self._endpoint(config.api_url, config.model), config.api_key or "", body, "StepFun 图片生成调用失败"
        )
        urls = [
            item.get("url")
            for item in payload.get("data") or []
            if isinstance(item, dict) and item.get("url")
        ]
        return {"imageUrls": urls, "metadata": payload}

    def _endpoint(self, api_url: Optional[str], model: Optional[str]) -> str:
        base = _strip_trailing_slash((api_url or "").strip() or "https://api.stepfun.com/v1")
        if base.endswith("/images/generations"):
            return base
        if model == STEP_IMAGE_EDIT_2:
            return self._extract_origin(base) + "/step_plan/v1/images/generations"
        if "/v1" not in base and "/step_plan/v1" not in base:
            base += "/v1"
        return base + "/images/generations"

    @staticmethod
    def _extract_origin(api_url: str) -> str:
        index = api_url.find("://")
        if index < 0:
            return "https://api.stepfun.com"
        path_index = api_url.find("/", index + 3)
        return api_url[:path_index] if path_index > 0 else api_url

    @staticmethod
    def _normalize_prompt(prompt: str, style: Optional[str]) -> str:
        normalized = prompt.strip()
        if style:
            normalized += f"。风格：{style.strip()}"
        return normalized[:MAX_PROMPT_LENGTH]

    @staticmethod
    def _normalize_size(model: Optional[str], size: Optional[str]) -> str:
        value = (size or "").strip()
        if not value or value.lower() in ("2k", "1k"):
            return "1024x1024"
        if model == STEP_IMAGE_EDIT_2:
            mapping = {
                "1280x800": "768x1360",
                "800x1280": "1360x768",
            }
            if value in mapping:
                return mapping[value]
            if value in ("1024x1024", "768x1360", "896x1184", "1360x768", "1184x896"):
                return value
            return "1024x1024"
        return value

    @staticmethod
    def _normalize_steps(model: Optional[str], steps: int) -> int:
        default = 8 if model == STEP_IMAGE_EDIT_2 else 50
        value = steps if steps > 0 else default
        return max(1, min(value, 50))

    @staticmethod
    def _normalize_cfg_scale(model: Optional[str], cfg_scale: float) -> float:
        default = 1.0 if model == STEP_IMAGE_EDIT_2 else (6.0 if model == STEP_2X_LARGE else 7.5)
        value = cfg_scale if cfg_scale > 0 else default
        return max(1.0, min(value, 10.0))


class AgnesVideoClient:
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
        body: dict[str, Any] = {
            "model": self.normalize_model(config.model),
            "prompt": prompt,
            "num_frames": self.normalize_num_frames(duration, DEFAULT_FRAME_RATE),
            "frame_rate": DEFAULT_FRAME_RATE,
        }
        if reference_image_url:
            body["image"] = reference_image_url.strip()
        payload = _post_json(
            self.normalize_base_url(config.api_url) + "/v1/videos",
            config.api_key or "",
            body,
            "Agnes 视频生成调用失败",
        )
        return first_text(payload.get("video_id"), payload.get("videoId"), payload.get("task_id"), payload.get("taskId"), payload.get("id"))

    def get_video_task(self, config: ResolvedAgentPlanConfig, task_id: str) -> dict:
        model = self.normalize_model(config.model)
        base = self.normalize_base_url(config.api_url)
        if task_id.startswith("video_"):
            endpoint = f"{base}/agnesapi?video_id={quote(task_id, safe='')}"
            if model:
                endpoint += f"&model_name={quote(model, safe='')}"
        else:
            endpoint = f"{base}/v1/videos/{quote(task_id or '', safe='')}"
        payload = _get_json(endpoint, config.api_key or "", "Agnes 视频生成调用失败")
        output = {
            "status": first_text(payload.get("status"), payload.get("task_status"), "running"),
            "videoUrl": self._find(payload, ("video_url", "videoUrl", "url", "remixed_from_video_id")),
            "coverUrl": self._find(payload, ("cover_url", "coverUrl", "poster_url", "first_frame_url", "last_frame_url")),
            "raw": payload,
        }
        progress = self._find(payload, ("progress", "percent"))
        if progress is not None:
            output["progress"] = progress
        return output

    @staticmethod
    def normalize_base_url(api_url: Optional[str]) -> str:
        base = _rewrite_agnes_host((api_url or "").strip() or "https://apihub.agnes-ai.com")
        base = _strip_trailing_slash(base)
        versioned = _normalize_from_versioned_path(base)
        if versioned is not None:
            return versioned
        return base[:-3] if base.endswith("/v1") else base

    @staticmethod
    def normalize_model(model: Optional[str]) -> Optional[str]:
        if not model:
            return model
        normalized = model.strip()
        lower = normalized.lower()
        if lower in ("agnes-video-2.0", "agnes-video-v20", "agnes-video-v2"):
            return "agnes-video-v2.0"
        return normalized

    @staticmethod
    def normalize_num_frames(duration: int, frame_rate: int) -> int:
        safe_duration = duration if duration > 0 else DEFAULT_DURATION_SECONDS
        safe_rate = frame_rate if frame_rate > 0 else DEFAULT_FRAME_RATE
        candidate = safe_duration * safe_rate + 1
        candidate = max(9, min(MAX_NUM_FRAMES, candidate))
        normalized = round((candidate - 1) / 8.0) * 8 + 1
        if normalized > MAX_NUM_FRAMES:
            normalized = MAX_NUM_FRAMES
        return max(9, normalized)

    @staticmethod
    def _find(payload: Any, keys: tuple[str, ...]) -> Any:
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if value is not None and value != "":
                    return value
            for child in payload.values():
                found = AgnesVideoClient._find(child, keys)
                if found is not None:
                    return found
        return None


openai_image_client = OpenAiCompatibleImageClient()
stepfun_image_client = StepFunImageClient()
agnes_video_client = AgnesVideoClient()
