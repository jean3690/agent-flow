import {
  Column,
  Entity,
  PrimaryGeneratedColumn,
} from 'typeorm';
import { isSqlite } from '../config';

const JSON_TYPE = isSqlite ? 'simple-json' : 'json';
const JSON_COLUMN = { type: JSON_TYPE as any, nullable: true };
const TIMESTAMP_COLUMN = { type: 'datetime' as const, nullable: true };
const SMALL_INT_TYPE = isSqlite ? 'integer' : 'tinyint';

@Entity('workflow')
export class Workflow {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: 'varchar', length: 255 }) name!: string;
  @Column({ type: 'text', nullable: true }) description!: string | null;
  @Column({ type: 'text' }) flowData!: string;
  @Column({ type: 'varchar', length: 50, nullable: true }) engineType!: string | null;
  @Column(TIMESTAMP_COLUMN) createdAt!: Date | null;
  @Column(TIMESTAMP_COLUMN) updatedAt!: Date | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) deleted!: number | null;
}

@Entity('node_definition')
export class NodeDefinition {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: 'varchar', length: 100 }) nodeType!: string;
  @Column({ type: 'varchar', length: 255 }) displayName!: string;
  @Column({ type: 'varchar', length: 50 }) category!: string;
  @Column({ type: 'varchar', length: 255, nullable: true }) icon!: string | null;
  @Column({ type: 'text', nullable: true }) inputSchema!: string | null;
  @Column({ type: 'text', nullable: true }) outputSchema!: string | null;
  @Column({ type: 'text', nullable: true }) configSchema!: string | null;
  @Column(TIMESTAMP_COLUMN) createdAt!: Date | null;
  @Column(TIMESTAMP_COLUMN) updatedAt!: Date | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) deleted!: number | null;
}

@Entity('execution_record')
export class ExecutionRecord {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: isSqlite ? 'integer' : 'bigint' }) flowId!: number;
  @Column(JSON_COLUMN) inputData!: string | null;
  @Column(JSON_COLUMN) outputData!: string | null;
  @Column({ type: 'varchar', length: 50 }) status!: string;
  @Column(JSON_COLUMN) nodeResults!: string | null;
  @Column({ type: 'text', nullable: true }) errorMessage!: string | null;
  @Column({ type: 'int', nullable: true }) duration!: number | null;
  @Column(TIMESTAMP_COLUMN) executedAt!: Date | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) deleted!: number | null;
}

@Entity('execution_snapshot')
export class ExecutionSnapshot {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: isSqlite ? 'integer' : 'bigint' }) executionId!: number;
  @Column({ type: isSqlite ? 'integer' : 'bigint' }) flowId!: number;
  @Column({ type: 'varchar', length: 100 }) nodeId!: string;
  @Column({ type: 'varchar', length: 50 }) nodeType!: string;
  @Column({ type: 'varchar', length: 255, nullable: true }) nodeName!: string | null;
  @Column({ type: 'varchar', length: 50 }) status!: string;
  @Column(JSON_COLUMN) inputData!: string | null;
  @Column(JSON_COLUMN) outputData!: string | null;
  @Column({ type: 'text', nullable: true }) errorMessage!: string | null;
  @Column(TIMESTAMP_COLUMN) startedAt!: Date | null;
  @Column(TIMESTAMP_COLUMN) completedAt!: Date | null;
  @Column({ type: 'int', nullable: true }) duration!: number | null;
  @Column({ type: 'int', nullable: true, default: 0 }) retryCount!: number | null;
  @Column({ type: 'int', nullable: true, default: 0 }) executionOrder!: number | null;
  @Column(TIMESTAMP_COLUMN) createdAt!: Date | null;
  @Column(TIMESTAMP_COLUMN) updatedAt!: Date | null;
}

@Entity('execution_variable')
export class ExecutionVariable {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: isSqlite ? 'integer' : 'bigint' }) executionId!: number;
  @Column({ type: 'varchar', length: 100 }) variableName!: string;
  @Column({ type: 'varchar', length: 50, nullable: true }) variableType!: string | null;
  @Column({ type: 'text', nullable: true }) variableValue!: string | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) isModified!: number | null;
  @Column(TIMESTAMP_COLUMN) createdAt!: Date | null;
  @Column(TIMESTAMP_COLUMN) updatedAt!: Date | null;
}

@Entity('llm_global_config')
export class LLMGlobalConfig {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: 'varchar', length: 50 }) provider!: string;
  @Column({ type: 'varchar', length: 100 }) configName!: string;
  @Column({ type: 'varchar', length: 255 }) apiUrl!: string;
  @Column({ type: 'text' }) apiKey!: string;
  @Column({ type: 'varchar', length: 100 }) model!: string;
  @Column({ type: 'varchar', length: 100, nullable: true }) ttsModel!: string | null;
  @Column({ type: 'varchar', length: 100, nullable: true }) embeddingModel!: string | null;
  @Column({ type: 'varchar', length: 100, nullable: true }) imageModel!: string | null;
  @Column({ type: 'varchar', length: 100, nullable: true }) videoModel!: string | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) memoryEnabled!: number | null;
  @Column({ type: isSqlite ? 'float' : 'decimal', precision: 3, scale: 2, nullable: true, default: 0.7 }) temperature!: number | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) isDefault!: number | null;
  @Column(TIMESTAMP_COLUMN) createdAt!: Date | null;
  @Column(TIMESTAMP_COLUMN) updatedAt!: Date | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) deleted!: number | null;
}

@Entity('mcp_tool_config')
export class McpToolConfig {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: 'varchar', length: 100 }) name!: string;
  @Column({ type: 'varchar', length: 500, nullable: true }) description!: string | null;
  @Column({ type: 'varchar', length: 50, nullable: true }) toolType!: string | null;
  @Column({ type: 'varchar', length: 100 }) toolName!: string;
  @Column({ type: 'varchar', length: 30, nullable: true }) transport!: string | null;
  @Column({ type: 'varchar', length: 500 }) command!: string;
  @Column(JSON_COLUMN) args!: string | null;
  @Column(JSON_COLUMN) env!: string | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 1 }) enabled!: number | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) preset!: number | null;
  @Column(TIMESTAMP_COLUMN) createdAt!: Date | null;
  @Column(TIMESTAMP_COLUMN) updatedAt!: Date | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) deleted!: number | null;
}

@Entity('knowledge_base')
export class KnowledgeBase {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: 'varchar', length: 100 }) name!: string;
  @Column({ type: 'varchar', length: 500, nullable: true }) description!: string | null;
  @Column({ type: isSqlite ? 'integer' : 'bigint', nullable: true }) configId!: number | null;
  @Column({ type: 'varchar', length: 100, nullable: true }) embeddingModel!: string | null;
  @Column({ type: 'int', nullable: true, default: 800 }) chunkSize!: number | null;
  @Column({ type: 'int', nullable: true, default: 100 }) chunkOverlap!: number | null;
  @Column({ type: 'varchar', length: 30, nullable: true }) status!: string | null;
  @Column({ type: 'int', nullable: true, default: 0 }) documentCount!: number | null;
  @Column({ type: 'int', nullable: true, default: 0 }) chunkCount!: number | null;
  @Column({ type: isSqlite ? 'integer' : 'bigint', nullable: true, default: 0 }) charCount!: number | null;
  @Column(TIMESTAMP_COLUMN) createdAt!: Date | null;
  @Column(TIMESTAMP_COLUMN) updatedAt!: Date | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) deleted!: number | null;
}

@Entity('knowledge_document')
export class KnowledgeDocument {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: isSqlite ? 'integer' : 'bigint' }) knowledgeBaseId!: number;
  @Column({ type: 'varchar', length: 255, nullable: true }) title!: string | null;
  @Column({ type: 'varchar', length: 30, nullable: true }) sourceType!: string | null;
  @Column({ type: 'varchar', length: 1024, nullable: true }) sourceUrl!: string | null;
  @Column({ type: 'varchar', length: 255, nullable: true }) fileName!: string | null;
  @Column({ type: 'text', nullable: true }) rawText!: string | null;
  @Column(JSON_COLUMN) tags!: string | null;
  @Column({ type: 'varchar', length: 30, nullable: true }) status!: string | null;
  @Column({ type: isSqlite ? 'integer' : 'bigint', nullable: true, default: 0 }) charCount!: number | null;
  @Column({ type: 'text', nullable: true }) errorMessage!: string | null;
  @Column(TIMESTAMP_COLUMN) createdAt!: Date | null;
  @Column(TIMESTAMP_COLUMN) updatedAt!: Date | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) deleted!: number | null;
}

@Entity('knowledge_chunk')
export class KnowledgeChunk {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: isSqlite ? 'integer' : 'bigint' }) knowledgeBaseId!: number;
  @Column({ type: isSqlite ? 'integer' : 'bigint', nullable: true }) documentId!: number | null;
  @Column({ type: 'int', nullable: true, default: 0 }) chunkIndex!: number | null;
  @Column({ type: 'varchar', length: 255, nullable: true }) title!: string | null;
  @Column({ type: 'text' }) content!: string;
  @Column({ type: 'varchar', length: 1024, nullable: true }) sourceUrl!: string | null;
  @Column(JSON_COLUMN) tags!: string | null;
  @Column({ type: 'varchar', length: 100, nullable: true }) embeddingModel!: string | null;
  @Column(JSON_COLUMN) embedding!: string | null;
  @Column({ type: 'varchar', length: 30, nullable: true }) status!: string | null;
  @Column({ type: 'int', nullable: true, default: 0 }) charCount!: number | null;
  @Column(TIMESTAMP_COLUMN) createdAt!: Date | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) deleted!: number | null;
}

@Entity('knowledge_index_task')
export class KnowledgeIndexTask {
  @PrimaryGeneratedColumn() id!: number;
  @Column({ type: isSqlite ? 'integer' : 'bigint' }) knowledgeBaseId!: number;
  @Column({ type: isSqlite ? 'integer' : 'bigint' }) documentId!: number;
  @Column({ type: 'varchar', length: 30, nullable: true }) status!: string | null;
  @Column({ type: 'int', nullable: true, default: 0 }) progress!: number | null;
  @Column({ type: 'int', nullable: true, default: 0 }) totalChunks!: number | null;
  @Column({ type: 'int', nullable: true, default: 0 }) finishedChunks!: number | null;
  @Column({ type: 'text', nullable: true }) errorMessage!: string | null;
  @Column(TIMESTAMP_COLUMN) createdAt!: Date | null;
  @Column(TIMESTAMP_COLUMN) updatedAt!: Date | null;
  @Column({ type: SMALL_INT_TYPE as any, nullable: true, default: 0 }) deleted!: number | null;
}

export const ENTITIES = [
  Workflow,
  NodeDefinition,
  ExecutionRecord,
  ExecutionSnapshot,
  ExecutionVariable,
  LLMGlobalConfig,
  McpToolConfig,
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeChunk,
  KnowledgeIndexTask,
];
