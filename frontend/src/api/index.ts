import http from './request'
import type {
  ExecutionDetail,
  ExecutionSummary,
  KnowledgeBase,
  KnowledgeChunk,
  KnowledgeDocument,
  KnowledgeSearchHit,
  LlmProvider,
  NodeDefinition,
  ProviderTestResult,
  WorkflowDetail,
  WorkflowSummary
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
    http.get<any, PageResult<ExecutionSummary>>('/workflows/' + id + '/executions', { params: { page, size } })
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
  list: () => http.get<any, any[]>('/skills'),
  detail: (name: string) => http.get<any, any>('/skills/' + name),
  reload: () => http.post<any, any>('/skills/reload')
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
    http.post<any, ProviderTestResult>('/llm-providers/' + provider + '/test', payload)
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
