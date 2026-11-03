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
  flow: FlowModel
  createdAt: string
  updatedAt: string
}

export interface ConfigOption {
  label: string
  value: string | number
}

export interface ConfigField {
  key: string
  label: string
  type: 'input' | 'textarea' | 'number' | 'select' | 'multiselect' | 'tags' | 'keyvalue' | 'node' | 'switch'
  options?: ConfigOption[]
  default?: any
  placeholder?: string
  help?: string
  rows?: number
  min?: number
  max?: number
  step?: number
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

export interface ExecutionSummary {
  id: number
  runId: string
  workflowId: number
  workflowName: string
  status: string
  nodeCount: number
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
  output?: string
  errorMessage?: string
  elapsedMs: number
}

export interface ExecutionDetail {
  runId: string
  workflowId: number
  workflowName: string
  status: string
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
