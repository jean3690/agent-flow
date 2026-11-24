import { MarkerType } from '@vue-flow/core'

export const WORKFLOW_EDGE_STYLE = {
  stroke: '#8b9bb4',
  strokeWidth: 2,
}

export const WORKFLOW_EDGE_MARKER = {
  type: MarkerType.ArrowClosed,
  width: 20,
  height: 20,
}

export type WorkflowNodeData = {
  label?: string
  type?: string
  provider?: string
  model?: string
  skillName?: string
  inputParams?: unknown[]
  outputParams?: unknown[]
  maxSteps?: number
  agentStrategy?: string
  tools?: string[]
  knowledgeBaseId?: string
  knowledgeBaseName?: string
  conditions?: Array<{ id: string; field?: string; operator?: string; value?: string }>
  [key: string]: unknown
}

export const getDefaultNodeData = (type: string) => {
  switch (type) {
    case 'image_generate':
      return {
        inputParams: [{ name: 'prompt', type: 'reference', value: '' }],
        outputParams: [{ name: 'image_url', value: 'imageUrl' }],
      }
    case 'video_generate':
      return {
        inputParams: [{ name: 'prompt', type: 'reference', value: '' }],
        outputParams: [{ name: 'video_url', value: 'videoUrl' }],
      }
    case 'react_agent':
      return { agentStrategy: 'react', maxSteps: 5, tools: [] }
    default:
      return {}
  }
}

export const nodeMeta: Record<string, { icon: string; tone: string; caption: string }> = {
  input: { icon: 'IN', tone: 'node-tone-green', caption: 'Start input' },
  output: { icon: 'OUT', tone: 'node-tone-purple', caption: 'Final response' },
  llm: { icon: 'AI', tone: 'node-tone-blue', caption: 'Model call' },
  react_agent: { icon: 'AG', tone: 'node-tone-blue', caption: 'Agent (ReAct)' },
  openai: { icon: 'AI', tone: 'node-tone-blue', caption: 'OpenAI' },
  deepseek: { icon: 'DS', tone: 'node-tone-blue', caption: 'DeepSeek' },
  qwen: { icon: 'QW', tone: 'node-tone-blue', caption: 'Qwen' },
  zhipu: { icon: 'ZP', tone: 'node-tone-blue', caption: 'ZhiPu' },
  ai_ping: { icon: 'AP', tone: 'node-tone-blue', caption: 'AIPing' },
  tts: { icon: 'TTS', tone: 'node-tone-amber', caption: 'Audio tool' },
  image_generate: { icon: 'IMG', tone: 'node-tone-amber', caption: 'Image generation' },
  video_generate: { icon: 'VID', tone: 'node-tone-amber', caption: 'Video generation' },
  condition: { icon: 'IF', tone: 'node-tone-orange', caption: 'Condition branch' },
}

export const getNodeMeta = (type?: string) =>
  nodeMeta[type || ''] || { icon: 'FN', tone: 'node-tone-slate', caption: 'Workflow node' }

export const getToolLabels = (tools: string[]) => {
  const labels: string[] = []
  if (tools.includes('web_search') || tools.includes('web_fetch')) {
    labels.push('联网搜索')
  }
  if (tools.includes('memory_write')) {
    labels.push('写入记忆')
  }
  return labels
}

export const getKnowledgeBaseLabel = (data: WorkflowNodeData) => {
  if (!data.knowledgeBaseId) {
    return ''
  }
  return data.knowledgeBaseName || '已启用'
}