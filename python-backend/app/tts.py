from __future__ import annotations

import logging
import struct
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from . import llm_config_service
from .db import first_text, text_or_none, to_float, to_int
from .minio_client import minio_service

logger = logging.getLogger("paiagent.tts")

QWEN_MAX_TTS_INPUT_LENGTH = 400
QWEN_MAX_TTS_INPUT_BYTES = 600
STEP_MAX_TTS_INPUT_LENGTH = 1000
STEP_INSTRUCTION_MAX_LENGTH = 200


@dataclass
class TtsRuntimeConfig:
    provider: str
    api_url: Optional[str]
    api_key: Optional[str]
    model: Optional[str]
    voice: str
    language_type: str
    instruction: Optional[str]
    speed: float
    volume: float
    sample_rate: int

    @property
    def max_input_length(self) -> int:
        return STEP_MAX_TTS_INPUT_LENGTH if self.provider == "step" else QWEN_MAX_TTS_INPUT_LENGTH

    @property
    def max_input_bytes(self) -> int:
        return 2**31 - 1 if self.provider == "step" else QWEN_MAX_TTS_INPUT_BYTES


def _canonicalize_provider(provider: Optional[str]) -> Optional[str]:
    if not provider:
        return None
    normalized = provider.strip().lower()
    if normalized in ("stepfun", "阶跃星辰"):
        return "step"
    if normalized in ("通义千问", "dashscope", "aliyun"):
        return "qwen"
    return normalized


def _infer_provider_from_model(model: Optional[str]) -> str:
    if not model:
        return "qwen"
    normalized = model.strip().lower()
    if normalized.startswith("step") or "stepaudio" in normalized:
        return "step"
    return "qwen"


def _normalize_tts_model(provider: Optional[str], model: Optional[str], explicit_tts_model: bool) -> Optional[str]:
    if explicit_tts_model:
        return text_or_none(model)
    trimmed = text_or_none(model)
    lower = (trimmed or "").lower()
    if provider == "step":
        if "step" in lower and "tts" in lower:
            return trimmed
        return "stepaudio-2.5-tts"
    if provider == "qwen":
        if "tts" in lower:
            return trimmed
        return "qwen3-tts-flash"
    return trimmed


def resolve_config(db: Session, data: dict) -> TtsRuntimeConfig:
    config_id = to_int(data.get("configId"))
    provider = None
    api_url = None
    api_key = None
    model = None
    explicit_tts_model = False

    if config_id is not None:
        global_config = llm_config_service.get_by_id(db, config_id)
        if global_config is not None:
            provider = _canonicalize_provider(global_config.provider)
            api_url = text_or_none(global_config.api_url)
            api_key = text_or_none(global_config.api_key)
            model = text_or_none(global_config.tts_model)
            explicit_tts_model = bool(model)
            if not explicit_tts_model:
                model = text_or_none(global_config.model)

    if not api_key:
        api_key = text_or_none(data.get("apiKey"))
    if not api_url:
        api_url = text_or_none(data.get("apiUrl"))
    if not model:
        model = text_or_none(data.get("model"))
    if not provider:
        provider = _canonicalize_provider(text_or_none(data.get("provider")))
    if not provider:
        provider = _infer_provider_from_model(model)

    voice = text_or_none(data.get("voice")) or ("cixingnansheng" if provider == "step" else "Cherry")
    language_type = text_or_none(data.get("languageType")) or "Auto"
    instruction = text_or_none(data.get("instruction"))
    speed = to_float(data.get("speed"), 1.0) or 1.0
    volume = to_float(data.get("volume"), 1.0) or 1.0
    sample_rate = to_int(data.get("sampleRate"), 24000) or 24000
    model = _normalize_tts_model(provider, model, explicit_tts_model)

    return TtsRuntimeConfig(
        provider=provider or "",
        api_url=api_url,
        api_key=api_key,
        model=model,
        voice=voice,
        language_type=language_type,
        instruction=instruction,
        speed=speed,
        volume=volume,
        sample_rate=sample_rate,
    )


def validate_config(config: TtsRuntimeConfig) -> None:
    if not config.provider:
        raise ValueError("TTS 节点缺少供应商配置，请选择全局配置或手动选择供应商")
    if not config.api_key:
        raise ValueError("TTS API Key 不能为空，请选择全局配置或在节点配置中设置")
    if not config.model:
        raise ValueError("TTS 模型名称不能为空")
    if config.provider not in ("qwen", "step"):
        raise ValueError(f"TTS 暂不支持的供应商: {config.provider}")
    if config.provider == "step" and config.instruction and len(config.instruction) > STEP_INSTRUCTION_MAX_LENGTH:
        raise ValueError("StepAudio 2.5 TTS 的 instruction 不能超过 200 字符")


def _normalize_dashscope_base_url(api_url: Optional[str]) -> Optional[str]:
    if not api_url:
        return None
    normalized = api_url.strip().rstrip("/")
    normalized = normalized.replace("/services/aigc/multimodal-generation/generation", "")
    normalized = normalized.replace("/compatible-mode/v1", "/api/v1")
    normalized = normalized.replace("/compatible-mode", "/api/v1")
    if not normalized.endswith("/api/v1"):
        normalized = normalized + "/api/v1"
    return normalized


def _normalize_step_speech_endpoint(api_url: Optional[str]) -> str:
    normalized = (api_url or "").strip() or "https://api.stepfun.com/v1"
    normalized = normalized.rstrip("/")
    if normalized.endswith("/audio/speech"):
        return normalized
    if normalized.endswith("/v1"):
        return normalized + "/audio/speech"
    if normalized.endswith("/step_plan/v1"):
        return normalized + "/audio/speech"
    return normalized + "/v1/audio/speech"


def _download_audio(url: str) -> bytes:
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=30.0), follow_redirects=True) as client:
        response = client.get(url)
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"下载音频失败, HTTP {response.status_code}")
    return response.content


def _call_qwen_tts(config: TtsRuntimeConfig, chunk: str) -> bytes:
    base = _normalize_dashscope_base_url(config.api_url) or "https://dashscope.aliyuncs.com/api/v1"
    endpoint = base + "/services/aigc/multimodal-generation/generation"
    body = {
        "model": config.model,
        "input": {
            "text": chunk,
            "voice": config.voice,
            "language_type": config.language_type,
        },
    }
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
        response = client.post(endpoint, json=body, headers=headers)
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"阿里百炼 TTS 调用失败, HTTP {response.status_code}: {response.text[:800]}")
    payload = response.json()
    audio_url = (((payload.get("output") or {}).get("audio")) or {}).get("url")
    if not audio_url:
        raise RuntimeError("阿里百炼 TTS 返回的音频URL为空")
    return _download_audio(audio_url)


def _call_step_tts(config: TtsRuntimeConfig, chunk: str) -> bytes:
    endpoint = _normalize_step_speech_endpoint(config.api_url)
    body: dict[str, Any] = {
        "model": config.model,
        "input": chunk,
        "voice": config.voice,
        "response_format": "wav",
        "speed": config.speed,
        "volume": config.volume,
        "sample_rate": config.sample_rate,
    }
    if config.instruction:
        body["instruction"] = config.instruction
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "Accept": "audio/wav,application/json",
    }
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
        response = client.post(endpoint, json=body, headers=headers)
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"StepAudio TTS 调用失败, HTTP {response.status_code}: {response.text[:800]}")
    if not response.content:
        raise RuntimeError("StepAudio TTS 返回的音频为空")
    return response.content


def split_text(text: str, max_length: int, max_bytes: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + max_length, length)
        while end > start:
            candidate = text[start:end]
            if len(candidate.encode("utf-8")) <= max_bytes:
                if end < length:
                    last_punctuation = _find_last_punctuation(text, start, end)
                    if last_punctuation > start:
                        end = last_punctuation + 1
                        candidate = text[start:end]
                chunks.append(candidate)
                start = end
                break
            end -= 10
        if end <= start:
            end = start + 1
            while end <= length:
                candidate = text[start:end]
                if len(candidate.encode("utf-8")) > max_bytes:
                    if end - 1 > start:
                        chunks.append(text[start : end - 1])
                        start = end - 1
                    else:
                        raise ValueError("单个字符超过 600 字节,无法处理")
                    break
                end += 1
    return chunks


def _find_last_punctuation(text: str, start: int, end: int) -> int:
    punctuations = "。！？；,.!?;"
    for index in range(end - 1, start - 1, -1):
        if text[index] in punctuations:
            return index
    return -1


def merge_wav_files(audio_chunks: list[bytes]) -> bytes:
    if not audio_chunks:
        raise ValueError("音频片段列表为空")
    if len(audio_chunks) == 1:
        return audio_chunks[0]
    first = audio_chunks[0]
    if len(first) < 44:
        raise ValueError("无效的 WAV 文件格式")
    merged = bytearray(first[:44])
    for chunk in audio_chunks:
        if len(chunk) > 44:
            merged.extend(chunk[44:])
    data_size = len(merged) - 44
    file_size = len(merged) - 8
    merged[4:8] = struct.pack("<I", file_size)
    merged[40:44] = struct.pack("<I", data_size)
    return bytes(merged)


def extract_input_text(node_data: dict, input_data: dict) -> Optional[str]:
    input_params = node_data.get("inputParams")
    if isinstance(input_params, list) and input_params:
        for param in input_params:
            if not isinstance(param, dict) or param.get("name") != "text":
                continue
            param_type = param.get("type")
            if param_type == "input":
                value = param.get("value")
                return None if value is None else str(value)
            if param_type == "reference":
                reference = param.get("referenceNode")
                if reference:
                    parts = str(reference).split(".")
                    if len(parts) == 2:
                        value = input_data.get(parts[1])
                        if isinstance(value, str):
                            return value
    for key in ("output", "input", "text"):
        value = input_data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def synthesize(db: Session, node_data: dict, input_data: dict, progress) -> dict:
    text = extract_input_text(node_data, input_data)
    if not text or not text.strip():
        raise ValueError("输入文本不能为空")

    config = resolve_config(db, node_data)
    validate_config(config)

    text_chunks = split_text(text, config.max_input_length, config.max_input_bytes)
    logger.info("TTS: provider=%s model=%s chunks=%s", config.provider, config.model, len(text_chunks))
    if progress:
        progress("文本已分割为 %d 个片段" % len(text_chunks), {"totalChunks": len(text_chunks), "currentChunk": 0})

    audio_chunks: list[bytes] = []
    for index, chunk in enumerate(text_chunks):
        if progress:
            progress(
                f"正在处理第 {index + 1}/{len(text_chunks)} 个片段",
                {"totalChunks": len(text_chunks), "currentChunk": index + 1, "chunkText": chunk[:50] + "..."},
            )
        if config.provider == "step":
            data = _call_step_tts(config, chunk)
        else:
            data = _call_qwen_tts(config, chunk)
        audio_chunks.append(data)
        if progress:
            progress(
                f"已完成第 {index + 1}/{len(text_chunks)} 个片段",
                {"totalChunks": len(text_chunks), "currentChunk": index + 1, "completedChunks": index + 1},
            )

    if progress:
        progress(f"正在合并 {len(audio_chunks)} 个音频片段...", None)

    merged = merge_wav_files(audio_chunks)
    file_name = f"audio_{uuid.uuid4().hex}.wav"
    url = minio_service.upload_from_bytes(merged, f"audio/{file_name}", "audio/wav")
    return {"audioUrl": url, "fileName": file_name, "output": url, "chunks": len(text_chunks)}
