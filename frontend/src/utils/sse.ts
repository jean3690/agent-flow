import { API_BASE_URL, TOKEN_KEY } from '../api/request'
import { parseEventStream, type SseEvent } from './eventStream'

export type { SseEvent } from './eventStream'

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
  const response = await fetch(API_BASE_URL + '/workflows/' + workflowId + '/execute', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      Authorization: 'Bearer ' + token
    },
    body: JSON.stringify({ input, resumeRunId: resumeRunId || undefined }),
    signal
  })

  if (!response.ok || !response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
    const text = await response.text()
    let message = text || 'HTTP ' + response.status
    try {
      message = JSON.parse(text).message || message
    } catch {
      // Some proxies return a plain-text error response.
    }
    if (response.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      location.hash = '#/login'
    }
    throw new Error(message)
  }

  for await (const event of parseEventStream(response.body)) {
    onEvent(event)
    // A terminal event is sufficient; don't wait for a lingering connection.
    if (event.event === 'run_finished' || event.event === 'run_failed') break
  }
}
