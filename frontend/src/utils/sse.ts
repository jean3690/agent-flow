import { TOKEN_KEY } from '../api/request'

export interface SseEvent {
  event: string
  data: any
}

interface RunOptions {
  workflowId: number
  input: Record<string, any>
  resumeRunId?: string
  signal: AbortSignal
  onEvent: (event: SseEvent) => void
}

/**
 * The execute endpoint is a POST with an Authorization header, so EventSource
 * cannot be used; we parse the SSE stream from fetch manually.
 */
export async function runWorkflow({ workflowId, input, resumeRunId, signal, onEvent }: RunOptions): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY) || ''
  const response = await fetch('/api/workflows/' + workflowId + '/execute', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      Authorization: 'Bearer ' + token
    },
    body: JSON.stringify({ input, resumeRunId: resumeRunId || undefined }),
    signal
  })

  if (!response.ok || !response.body) {
    const text = await response.text()
    throw new Error(text || 'HTTP ' + response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const parsed = parseBlock(block)
      if (parsed) onEvent(parsed)
      boundary = buffer.indexOf('\n\n')
    }
  }

  const tail = parseBlock(buffer)
  if (tail) onEvent(tail)
}

function parseBlock(block: string): SseEvent | null {
  if (!block.trim()) return null
  let event = 'message'
  const dataLines: string[] = []
  for (const rawLine of block.split('\n')) {
    const line = rawLine.trim()
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }
  if (!dataLines.length) return null
  const raw = dataLines.join('\n')
  try {
    return { event, data: JSON.parse(raw) }
  } catch {
    return { event, data: raw }
  }
}
