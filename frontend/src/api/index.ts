import http from './request'
import { fetchPlatformFile } from '../utils/protectedFiles'
import type {
  ExecutionDetail,
  ExecutionSummary,
  FileItem,
  KnowledgeBase,
  KnowledgeChunk,
  KnowledgeDocument,
  KnowledgeSearchHit,
  LlmProvider,
  NodeDefinition,
  ProviderModelsResult,
  ProviderTestResult,
  WorkflowDetail,
  WorkflowSummary,
  WorkflowTrigger,
  WorkflowVersion,
  SkillSummary,
  SkillDetail,
  McpServer,
  McpTool,
  MemoryItem,
  ApprovalTask
} from '../types'

export interface PageResult<T> {
  records: T[]
  total: number
  page: number
  size: number
}

export const authApi = {
  login: (username: string, password: string) =>
    http.post<any, { token: string; user: any }>('/auth/login', { username, password }),
  me: () => http.get<any, any>('/auth/me')
}

export const workflowApi = {
  page: (page = 1, size = 20, keyword = '') =>
    http.get<any, PageResult<WorkflowSummary>>('/workflows', { params: { page, size, keyword } }),
  detail: (id: number) => http.get<any, WorkflowDetail>('/workflows/' + id),
  create: (payload: any) => http.post<any, WorkflowDetail>('/workflows', payload),
  update: (id: number, payload: any) => http.put<any, WorkflowDetail>('/workflows/' + id, payload),
  remove: (id: number) => http.delete<any, void>('/workflows/' + id),
  duplicate: (id: number) => http.post<any, WorkflowDetail>('/workflows/' + id + '/duplicate'),
  executions: (id: number, page = 1, size = 20) =>
    http.get<any, PageResult<ExecutionSummary>>('/workflows/' + id + '/executions', { params: { page, size } }),
  versions: (id: number) => http.get<any, WorkflowVersion[]>('/workflows/' + id + '/versions'),
  versionDetail: (id: number, version: number) =>
    http.get<any, WorkflowVersion>('/workflows/' + id + '/versions/' + version),
  rollback: (id: number, version: number) =>
    http.post<any, WorkflowDetail>('/workflows/' + id + '/versions/' + version + '/rollback', {}),
  publish: (id: number) => http.post<any, WorkflowDetail>('/workflows/' + id + '/publish', {}),
  unpublish: (id: number) => http.post<any, WorkflowDetail>('/workflows/' + id + '/unpublish', {})
}

export const executionApi = {
  page: (page = 1, size = 20, params: { workflowId?: number; status?: string } = {}) =>
    http.get<any, PageResult<ExecutionSummary>>('/executions', { params: { page, size, ...params } }),
  detail: (runId: string) => http.get<any, ExecutionDetail>('/executions/' + runId),
  cancel: (runId: string) => http.post<any, void>('/executions/' + runId + '/cancel'),
  remove: (runId: string) => http.delete<any, void>('/executions/' + runId)
}

export const nodeApi = {
  list: () => http.get<any, NodeDefinition[]>('/node-definitions')
}

export const skillApi = {
  list: () => http.get<any, SkillSummary[]>('/skills'),
  detail: (name: string) => http.get<any, SkillDetail>('/skills/' + encodeURIComponent(name)),
  reload: () => http.post<any, SkillSummary[]>('/skills/reload'),
  save: (name: string, content: string) => http.put<any, SkillDetail>('/skills/' + encodeURIComponent(name), { content }),
  remove: (name: string) => http.delete('/skills/' + encodeURIComponent(name)),
  reference: (name: string, file: string) => http.get<any, { content: string }>('/skills/' + encodeURIComponent(name) + '/references/' + encodeURIComponent(file))
}

export const mcpApi = {
  list: () => http.get<any, McpServer[]>('/mcp-servers'),
  create: (payload: any) => http.post<any, McpServer>('/mcp-servers', payload),
  update: (id: number, payload: any) => http.put<any, McpServer>('/mcp-servers/' + id, payload),
  remove: (id: number) => http.delete('/mcp-servers/' + id),
  discover: (id: number) => http.post<any, { ok: boolean; tools: McpTool[]; message: string }>('/mcp-servers/' + id + '/discover'),
  tools: (id: number) => http.get<any, McpTool[]>('/mcp-servers/' + id + '/tools')
}

export const systemApi = {
  aiHealth: () => http.get<any, { up: boolean }>('/system/ai-health')
}

export const llmProviderApi = {
  list: () => http.get<any, LlmProvider[]>('/llm-providers'),
  save: (provider: string, payload: { apiKey?: string; baseUrl?: string }) =>
    http.put<any, void>('/llm-providers/' + provider, payload),
  clear: (provider: string) => http.delete<any, void>('/llm-providers/' + provider),
  test: (provider: string, payload: { apiKey?: string; baseUrl?: string; model?: string }) =>
    http.post<any, ProviderTestResult>('/llm-providers/' + provider + '/test', payload),
  models: (provider: string) =>
    http.get<any, ProviderModelsResult>('/llm-providers/' + provider + '/models')
}

function encodeFilePath(name: string) {
  return name
    .split('/')
    .filter((part) => part)
    .map((part) => encodeURIComponent(part))
    .join('/')
}

export const triggerApi = {
  list: (workflowId: number) =>
    http.get<any, WorkflowTrigger[]>('/workflows/' + workflowId + '/triggers'),
  create: (workflowId: number, payload: any) =>
    http.post<any, WorkflowTrigger>('/workflows/' + workflowId + '/triggers', payload),
  update: (id: number, payload: any) =>
    http.put<any, WorkflowTrigger>('/triggers/' + id, payload),
  remove: (id: number) => http.delete<any, void>('/triggers/' + id),
  run: (id: number) => http.post<any, WorkflowTrigger>('/triggers/' + id + '/run', {}),
  rotate: (id: number) => http.post<any, WorkflowTrigger>('/triggers/' + id + '/rotate-token', {})
}

export const fileApi = {
  list: (prefix = '', limit = 500) =>
    http.get<any, FileItem[]>('/files', { params: { prefix, limit } }),
  upload: (file: File, name = '') => {
    const form = new FormData()
    form.append('file', file)
    if (name) form.append('name', name)
    return http.post<any, FileItem>('/files/upload', form)
  },
  writeText: (payload: {
    name: string
    content: string
    encoding?: string
    overwrite?: boolean
    append?: boolean
  }) => http.post<any, FileItem>('/files/text', payload),
  remove: (name: string) => http.delete<any, FileItem>('/files/' + encodeFilePath(name)),
  url: (name: string, download = false) =>
    '/api/files/' + encodeFilePath(name) + (download ? '?download=true' : ''),
  blob: (name: string, download = false, signal?: AbortSignal) =>
    fetchPlatformFile('/api/files/' + encodeFilePath(name) + (download ? '?download=true' : ''), signal)
}

export const approvalApi = {
  list: (status = '') => http.get<any, ApprovalTask[]>('/approvals', { params: { status: status || undefined } }),
  decide: (id: number, approved: boolean, comment = '') =>
    http.post<any, ApprovalTask>('/approvals/' + id + '/decide', { approved, comment })
}

export const memoryApi = {
  list: (scope = '', workflowId?: number) =>
    http.get<any, MemoryItem[]>('/memories', { params: { scope: scope || undefined, workflowId } }),
  remove: (id: number) => http.delete<any, void>('/memories/' + id)
}

export const knowledgeApi = {
  list: () => http.get<any, KnowledgeBase[]>('/knowledge-bases'),
  create: (payload: any) => http.post<any, KnowledgeBase>('/knowledge-bases', payload),
  remove: (id: number) => http.delete<any, void>('/knowledge-bases/' + id),
  documents: (id: number) => http.get<any, KnowledgeDocument[]>('/knowledge-bases/' + id + '/documents'),
  importText: (id: number, payload: { title: string; content: string }) =>
    http.post<any, KnowledgeDocument>('/knowledge-bases/' + id + '/documents/text', payload),
  upload: (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http.post<any, KnowledgeDocument>('/knowledge-bases/' + id + '/documents/upload', form)
  },
  removeDocument: (id: number, documentId: number) =>
    http.delete<any, void>('/knowledge-bases/' + id + '/documents/' + documentId),
  preview: (id: number, documentId: number) =>
    http.post<any, KnowledgeChunk[]>('/knowledge-bases/' + id + '/documents/' + documentId + '/preview', {}),
  index: (id: number, documentId: number) =>
    http.post<any, KnowledgeDocument>('/knowledge-bases/' + id + '/documents/' + documentId + '/index'),
  search: (id: number, payload: { query: string; topK?: number }) =>
    http.post<any, KnowledgeSearchHit[]>('/knowledge-bases/' + id + '/search', payload)
}
