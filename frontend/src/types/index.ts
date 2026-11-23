export interface NodePosition {
  x: number
  y: number
}

export interface FlowNodeModel {
  id: string
  type: string
  name: string
  position: NodePosition
  config: Record<string, any>
}

export interface FlowEdgeModel {
  id?: string
  source: string
  target: string
}

export interface FlowModel {
  name?: string
  engineType?: string
  nodes: FlowNodeModel[]
  edges: FlowEdgeModel[]
}

export interface WorkflowSummary {
  id: number
  name: string
  description?: string
  engineType: string
  status: number
  version: number
  publishedVersion?: number
  nodeCount: number
  createdAt: string
  updatedAt: string
}

export interface WorkflowDetail {
  id: number
  name: string
  description?: string
  engineType: string
  status: number
  version: number
  publishedVersion?: number
  publishedAt?: string
  flow: FlowModel
  createdAt: string
  updatedAt: string
}

export interface WorkflowVersion {
  id: number
  workflowId: number
  version: number
  name: string
  description?: string
  engineType: string
  note?: string
  createdBy?: number
  createdAt: string
  published: boolean
  current: boolean
  flow?: FlowModel
}

export interface ConfigOption {
  label: string
  value: string | number
}

export interface OutputFieldDef {
  key: string
  label: string
  type: string
}

export interface NodeOutputFieldConfig {
  key: string
  alias?: string
  hidden?: boolean
}

export interface ConfigField {
  visibleWhen?: Record<string, Array<string | number | boolean>>
  key: string
  label: string
  type:
    | 'input'
    | 'textarea'
    | 'number'
    | 'select'
    | 'multiselect'
    | 'tags'
    | 'keyvalue'
    | 'node'
    | 'nodes'
    | 'workflow'
    | 'switch'
    | 'file'
    | 'knowledge'
    | 'skills'
    | 'mcpServer'
    | 'mcpServers'
    | 'mcpTool'
    | 'outputSchema'
  options?: ConfigOption[]
  default?: any
  placeholder?: string
  help?: string
  rows?: number
  min?: number
  max?: number
  step?: number
  dynamic?: string
  providerField?: string
  fields?: OutputFieldDef[]
  hasValueKey?: boolean
}

export interface NodeDefinition {
  type: string
  name: string
  category: string
  icon: string
  color: string
  description: string
  configSchema: ConfigField[]
  sort: number
}

export interface SkillSummary {
  name: string
  title: string
  description: string
  version: string
  tags: string[]
  editable: boolean
}
export interface SkillDetail extends SkillSummary {
  content: string
  rawContent: string
  references: Array<{ name: string; file: string; size: number }>
}
export interface McpTool {
  name: string
  description: string
  inputSchema: Record<string, any>
}
export interface McpServer {
  id: number
  name: string
  url: string
  enabled: boolean
  timeoutMs: number
  hasCredentials: boolean
  allowedTools: string[]
  tools: McpTool[]
}

export interface ExecutionSummary {
  id: number
  runId: string
  workflowId: number
  workflowName: string
  status: string
  nodeCount: number
  flowVersion?: number
  promptTokens?: number
  completionTokens?: number
  totalTokens?: number
  costUsd?: number
  elapsedMs: number
  errorMessage?: string
  startedAt: string
  finishedAt?: string
}

export interface NodeLog {
  nodeId: string
  nodeType: string
  nodeName: string
  seq: number
  status: string
  cacheHit?: boolean
  output?: string
  errorMessage?: string
  elapsedMs: number
}

export interface ExecutionDetail {
  runId: string
  resumeRunId?: string
  workflowId: number
  workflowName: string
  status: string
  flowVersion?: number
  promptTokens?: number
  completionTokens?: number
  totalTokens?: number
  costUsd?: number
  input?: string
  output?: string
  errorMessage?: string
  elapsedMs: number
  nodes: NodeLog[]
}

export interface LlmProvider {
  provider: string
  label: string
  defaultModel: string
  models: string[]
  supportsTts: boolean
  configured: boolean
  source: 'DB' | 'ENV' | 'NONE'
  baseUrl?: string
  apiKeyMasked?: string
}

export interface ProviderTestResult {
  ok: boolean
  latencyMs?: number
  model?: string
  message?: string
}

export interface ProviderModelsResult {
  ok: boolean
  source: 'upstream' | 'static'
  provider: string
  models: string[]
  message?: string
}

export interface KnowledgeBase {
  id: number
  name: string
  description?: string
  embeddingProvider: string
  embeddingModel: string
  chunkSize: number
  chunkOverlap: number
  documentCount: number
  chunkCount: number
  createdAt?: string
}

export interface KnowledgeDocument {
  id: number
  title: string
  sourceType: string
  charCount: number
  status: string
  chunkCount: number
  errorMessage?: string
  createdAt?: string
}

export interface KnowledgeChunk {
  chunkIndex: number
  content: string
  charCount: number
}

export interface KnowledgeSearchHit {
  chunkId: number
  documentId: number
  title: string
  content: string
  score: number
}

export interface WorkflowTrigger {
  id: number
  workflowId: number
  name: string
  type: 'CRON' | 'WEBHOOK'
  enabled: boolean
  cronExpression?: string
  timezone?: string
  webhookPath?: string
  input: Record<string, any>
  lastRunId?: string
  lastStatus?: string
  lastRunAt?: string
  nextRunAt?: string
  createdAt?: string
  updatedAt?: string
}

export interface FileItem {
  name: string
  fileName: string
  originalName?: string
  path: string
  url: string
  size: number
  contentType: string
  createdAt: number
  updatedAt: number
}
export interface MemoryItem {
  id: number
  workflowId?: number | null
  userId?: number | null
  scope: string
  memoryType: string
  content: string
  tags: string[]
  sourceNodeId?: string | null
  score?: number
  createdAt?: string
}
export interface ApprovalTask {
  id: number
  runId: string
  workflowId?: number | null
  nodeId: string
  userId?: number | null
  title: string
  content?: string
  status: string
  comment?: string
  decidedBy?: number | null
  expiresAt?: string
  decidedAt?: string
  createdAt?: string
}
