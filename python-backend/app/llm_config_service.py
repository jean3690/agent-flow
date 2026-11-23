from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .db import format_dt, first_text, to_int, to_float
from .models import LLMGlobalConfig


PROVIDER_ALIASES = {
    "open ai": "openai",
    "deep seek": "deepseek",
    "通义千问": "qwen",
    "dashscope": "qwen",
    "aliyun": "qwen",
    "stepfun": "step",
    "阶跃星辰": "step",
    "ai ping": "ai_ping",
    "智谱": "zhipu",
    "agnes": "agnes",
    "agnes ai": "agnes",
    "api free": "apifree",
    "apifree.ai": "apifree",
    "skyclaw": "apifree",
    "skyclaw-v1": "apifree",
    "skyclaw-v1.0": "apifree",
    "skyclaw-v1-lite": "apifree",
    "skyclaw-v1.0-lite": "apifree",
    "skywork-ai/skyclaw-v1": "apifree",
    "skywork-ai/skyclaw-v1-lite": "apifree",
    "volcengine": "volcengine_agent_plan",
    "ark": "volcengine_agent_plan",
    "agent_plan": "volcengine_agent_plan",
    "agent plan": "volcengine_agent_plan",
    "火山方舟": "volcengine_agent_plan",
}


def canonicalize_provider(provider: Optional[str]) -> Optional[str]:
    if provider is None:
        return None
    normalized = provider.strip().lower()
    return PROVIDER_ALIASES.get(normalized, normalized)


def _trim_to_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def llm_config_to_dict(config: LLMGlobalConfig) -> dict:
    return {
        "id": config.id,
        "provider": config.provider,
        "configName": config.config_name,
        "apiUrl": config.api_url,
        "apiKey": config.api_key,
        "model": config.model,
        "ttsModel": config.tts_model,
        "embeddingModel": config.embedding_model,
        "imageModel": config.image_model,
        "videoModel": config.video_model,
        "memoryEnabled": config.memory_enabled or 0,
        "temperature": float(config.temperature) if config.temperature is not None else None,
        "isDefault": config.is_default or 0,
        "createdAt": format_dt(config.created_at),
        "updatedAt": format_dt(config.updated_at),
    }


def get_by_id(db: Session, config_id: Any) -> Optional[LLMGlobalConfig]:
    ident = to_int(config_id)
    if ident is None:
        return None
    return db.execute(
        select(LLMGlobalConfig).where(LLMGlobalConfig.id == ident, LLMGlobalConfig.deleted == 0)
    ).scalar_one_or_none()


def list_by_provider(db: Session, provider: str) -> list[LLMGlobalConfig]:
    return list(
        db.execute(
            select(LLMGlobalConfig)
            .where(LLMGlobalConfig.provider == provider, LLMGlobalConfig.deleted == 0)
            .order_by(LLMGlobalConfig.is_default.desc(), LLMGlobalConfig.updated_at.desc())
        ).scalars()
    )


def list_all(db: Session) -> list[LLMGlobalConfig]:
    return list(
        db.execute(select(LLMGlobalConfig).where(LLMGlobalConfig.deleted == 0)).scalars()
    )


def get_default_config(db: Session, provider: str) -> Optional[LLMGlobalConfig]:
    return db.execute(
        select(LLMGlobalConfig)
        .where(
            LLMGlobalConfig.provider == provider,
            LLMGlobalConfig.is_default == 1,
            LLMGlobalConfig.deleted == 0,
        )
        .limit(1)
    ).scalar_one_or_none()


def set_default_config(db: Session, config_id: int) -> None:
    config = get_by_id(db, config_id)
    if config is None:
        raise ValueError("配置不存在")
    db.execute(
        update(LLMGlobalConfig)
        .where(
            LLMGlobalConfig.provider == config.provider,
            LLMGlobalConfig.deleted == 0,
        )
        .values(is_default=0)
    )
    config.is_default = 1
    db.commit()


def _normalize(config: LLMGlobalConfig) -> None:
    config.provider = canonicalize_provider(_trim_to_none(config.provider))
    config.config_name = _trim_to_none(config.config_name)
    config.api_url = _trim_to_none(config.api_url)
    config.api_key = _trim_to_none(config.api_key)
    config.model = _trim_to_none(config.model)
    config.tts_model = _trim_to_none(config.tts_model)
    config.embedding_model = _trim_to_none(config.embedding_model)
    config.image_model = _trim_to_none(config.image_model)
    config.video_model = _trim_to_none(config.video_model)
    config.memory_enabled = 1 if to_int(config.memory_enabled, 0) == 1 else 0


def _validate(config: LLMGlobalConfig) -> None:
    checks = [
        (config.provider, "供应商不能为空"),
        (config.config_name, "配置别名不能为空"),
        (config.api_url, "API 地址不能为空"),
        (config.api_key, "API 密钥不能为空"),
        (config.model, "模型名称不能为空"),
    ]
    for value, message in checks:
        if not value:
            raise ValueError(message)


def save_config(db: Session, payload: dict) -> LLMGlobalConfig:
    config_id = to_int(payload.get("id"))
    config = get_by_id(db, config_id) if config_id is not None else None
    is_new = config is None
    if is_new:
        config = LLMGlobalConfig()
        config.deleted = 0
        config.is_default = 0
        config.memory_enabled = 0
        config.temperature = 0.7

    field_map = [
        ("provider", "provider"),
        ("config_name", "configName"),
        ("api_url", "apiUrl"),
        ("api_key", "apiKey"),
        ("model", "model"),
        ("tts_model", "ttsModel"),
        ("embedding_model", "embeddingModel"),
        ("image_model", "imageModel"),
        ("video_model", "videoModel"),
    ]
    for attribute, key in field_map:
        if is_new or key in payload:
            setattr(config, attribute, _trim_to_none(payload.get(key)))

    # MyBatis-Plus only skips nulls, and memoryEnabled is normalized to 0 when absent.
    config.memory_enabled = 1 if to_int(payload.get("memoryEnabled"), 0) == 1 else 0
    if is_new:
        temperature = to_float(payload.get("temperature"), 0.7)
        config.temperature = 0.7 if temperature is None else temperature
    elif "temperature" in payload and payload.get("temperature") is not None:
        config.temperature = to_float(payload.get("temperature"), 0.7)
    if "isDefault" in payload:
        config.is_default = 1 if to_int(payload.get("isDefault"), 0) == 1 else 0

    config.provider = canonicalize_provider(config.provider)
    _validate(config)

    # Purge a previously soft-deleted row with the same provider/config name (hard delete).
    existing = db.execute(
        select(LLMGlobalConfig)
        .where(
            LLMGlobalConfig.provider == config.provider,
            LLMGlobalConfig.config_name == config.config_name,
            LLMGlobalConfig.id != (config.id or -1),
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None and (existing.deleted or 0) == 1:
        db.execute(delete(LLMGlobalConfig).where(LLMGlobalConfig.id == existing.id))
        db.flush()

    duplicate = db.execute(
        select(LLMGlobalConfig)
        .where(
            LLMGlobalConfig.provider == config.provider,
            LLMGlobalConfig.config_name == config.config_name,
            LLMGlobalConfig.deleted == 0,
            LLMGlobalConfig.id != (config.id or -1),
        )
        .limit(1)
    ).scalar_one_or_none()
    if duplicate is not None:
        raise ValueError("同一供应商下的配置别名不能重复")

    count = len(list_by_provider(db, config.provider)) if config.id else len(
        list(db.execute(
            select(LLMGlobalConfig).where(
                LLMGlobalConfig.provider == config.provider,
                LLMGlobalConfig.deleted == 0,
            )
        ).scalars())
    )

    if config.id is None:
        if count == 0:
            config.is_default = 1
        elif payload.get("isDefault") is None:
            config.is_default = 0
        db.add(config)
        db.commit()
    else:
        if (config.is_default or 0) == 1:
            db.execute(
                update(LLMGlobalConfig)
                .where(
                    LLMGlobalConfig.provider == config.provider,
                    LLMGlobalConfig.id != config.id,
                    LLMGlobalConfig.deleted == 0,
                )
                .values(is_default=0)
            )
        db.commit()
    db.refresh(config)
    return config


def delete_config(db: Session, config_id: int) -> None:
    config = get_by_id(db, config_id)
    if config is None:
        return
    provider = config.provider
    was_default = (config.is_default or 0) == 1
    db.execute(delete(LLMGlobalConfig).where(LLMGlobalConfig.id == config_id))
    db.commit()

    if was_default:
        remaining = list_by_provider(db, provider)
        if remaining:
            remaining[0].is_default = 1
            db.commit()
