from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now

BIGINT = BigInteger().with_variant(Integer, "sqlite")


class Workflow(Base):
    __tablename__ = "workflow"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    flow_data: Mapped[str] = mapped_column(Text, nullable=False)
    engine_type: Mapped[str | None] = mapped_column(String(50), default="dag")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, onupdate=now)
    deleted: Mapped[int | None] = mapped_column(Integer, default=0)


class NodeDefinition(Base):
    __tablename__ = "node_definition"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    node_type: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(255))
    input_schema: Mapped[str | None] = mapped_column(Text)
    output_schema: Mapped[str | None] = mapped_column(Text)
    config_schema: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, onupdate=now)
    deleted: Mapped[int | None] = mapped_column(Integer, default=0)


class ExecutionRecord(Base):
    __tablename__ = "execution_record"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    flow_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    input_data: Mapped[str | None] = mapped_column(Text)
    output_data: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    node_results: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration: Mapped[int | None] = mapped_column(Integer)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    deleted: Mapped[int | None] = mapped_column(Integer, default=0)


class ExecutionSnapshot(Base):
    __tablename__ = "execution_snapshot"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    flow_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    node_id: Mapped[str] = mapped_column(String(100), nullable=False)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)
    node_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    input_data: Mapped[str | None] = mapped_column(Text)
    output_data: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int | None] = mapped_column(Integer, default=0)
    execution_order: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, onupdate=now)


class ExecutionVariable(Base):
    __tablename__ = "execution_variable"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    variable_name: Mapped[str] = mapped_column(String(100), nullable=False)
    variable_type: Mapped[str | None] = mapped_column(String(50), default="STRING")
    variable_value: Mapped[str | None] = mapped_column(Text)
    is_modified: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, onupdate=now)


class LLMGlobalConfig(Base):
    __tablename__ = "llm_global_config"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    config_name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    tts_model: Mapped[str | None] = mapped_column(String(100))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    image_model: Mapped[str | None] = mapped_column(String(100))
    video_model: Mapped[str | None] = mapped_column(String(100))
    memory_enabled: Mapped[int | None] = mapped_column(Integer, default=0)
    temperature: Mapped[float | None] = mapped_column(Numeric(3, 2), default=0.7)
    is_default: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, onupdate=now)
    deleted: Mapped[int | None] = mapped_column(Integer, default=0)


class McpToolConfig(Base):
    __tablename__ = "mcp_tool_config"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    tool_type: Mapped[str | None] = mapped_column(String(50), default="custom")
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    transport: Mapped[str | None] = mapped_column(String(30), default="stdio")
    command: Mapped[str] = mapped_column(String(500), nullable=False)
    args: Mapped[str | None] = mapped_column(Text)
    env: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[int | None] = mapped_column(Integer, default=1)
    preset: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, onupdate=now)
    deleted: Mapped[int | None] = mapped_column(Integer, default=0)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    config_id: Mapped[int | None] = mapped_column(BIGINT)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    chunk_size: Mapped[int | None] = mapped_column(Integer, default=800)
    chunk_overlap: Mapped[int | None] = mapped_column(Integer, default=100)
    status: Mapped[str | None] = mapped_column(String(30), default="DRAFT")
    document_count: Mapped[int | None] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int | None] = mapped_column(Integer, default=0)
    char_count: Mapped[int | None] = mapped_column(BIGINT, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, onupdate=now)
    deleted: Mapped[int | None] = mapped_column(Integer, default=0)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str | None] = mapped_column(String(30), default="TEXT")
    source_url: Mapped[str | None] = mapped_column(String(1024))
    file_name: Mapped[str | None] = mapped_column(String(255))
    raw_text: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(30), default="IMPORTED")
    char_count: Mapped[int | None] = mapped_column(BIGINT, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, onupdate=now)
    deleted: Mapped[int | None] = mapped_column(Integer, default=0)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    document_id: Mapped[int | None] = mapped_column(BIGINT)
    chunk_index: Mapped[int | None] = mapped_column(Integer, default=0)
    title: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    tags: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedding: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(30), default="READY")
    char_count: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    deleted: Mapped[int | None] = mapped_column(Integer, default=0)


class KnowledgeIndexTask(Base):
    __tablename__ = "knowledge_index_task"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    document_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    status: Mapped[str | None] = mapped_column(String(30), default="RUNNING")
    progress: Mapped[int | None] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int | None] = mapped_column(Integer, default=0)
    finished_chunks: Mapped[int | None] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, onupdate=now)
    deleted: Mapped[int | None] = mapped_column(Integer, default=0)


class AgentMemory(Base):
    __tablename__ = "agent_memory"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(50), nullable=False, default="workflow")
    memory_type: Mapped[str | None] = mapped_column(String(50), default="fact")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, onupdate=now)
    deleted: Mapped[int | None] = mapped_column(Integer, default=0)


class AgentMemoryEmbedding(Base):
    __tablename__ = "agent_memory_embedding"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    memory_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    dimension: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=now)
