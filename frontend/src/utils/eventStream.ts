export interface SseEvent {
  event: string
  data: any
}

/** Decode SSE incrementally, including CRLF/UTF-8 split across chunks. */
export async function* parseEventStream(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let line = ''
  let skipLF = false
  let event = 'message'
  let data: string[] = []

  function dispatch(): SseEvent | undefined {
    let result: SseEvent | undefined
    if (data.length) {
      const raw = data.join('\n')
      try {
        result = { event, data: JSON.parse(raw) }
      } catch {
        result = { event, data: raw }
      }
    }
    event = 'message'
    data = []
    return result
  }

  function consumeLine(value: string): SseEvent | undefined {
    if (!value) return dispatch()
    if (value.startsWith(':')) return
    const colon = value.indexOf(':')
    const field = colon < 0 ? value : value.slice(0, colon)
    let content = colon < 0 ? '' : value.slice(colon + 1)
    if (content.startsWith(' ')) content = content.slice(1)
    if (field === 'event') event = content || 'message'
    if (field === 'data') data.push(content)
  }

  function* consumeText(text: string): Generator<SseEvent> {
    for (const char of text) {
      if (skipLF) {
        skipLF = false
        if (char === '\n') continue
      }
      if (char === '\r' || char === '\n') {
        const parsed = consumeLine(line)
        line = ''
        skipLF = char === '\r'
        if (parsed) yield parsed
      } else {
        line += char
      }
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      yield* consumeText(decoder.decode(value, { stream: true }))
    }
    yield* consumeText(decoder.decode())
    if (line) consumeLine(line)
    // Keep compatibility with servers omitting the final blank line.
    const tail = dispatch()
    if (tail) yield tail
  } finally {
    try {
      await reader.cancel()
    } catch {
      // A cleanup error must not hide the original network/callback error.
    }
    reader.releaseLock()
  }
}
