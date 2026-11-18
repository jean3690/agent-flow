import { expect, test } from '@playwright/test'
import { parseEventStream, type SseEvent } from '../../src/utils/eventStream'

function stream(text: string, byteByByte = false) {
  const bytes = new TextEncoder().encode(text)
  return new ReadableStream<Uint8Array>({
    start(controller) {
      if (byteByByte) {
        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte))
      } else {
        controller.enqueue(bytes)
      }
      controller.close()
    }
  })
}

async function collect(body: ReadableStream<Uint8Array>) {
  const result: SseEvent[] = []
  for await (const event of parseEventStream(body)) result.push(event)
  expect(body.locked).toBe(false)
  return result
}

for (const newline of ['\n', '\r\n', '\r']) {
  test(`parses multiline JSON and multiple events with ${JSON.stringify(newline)}`, async () => {
    const text = [
      ': heartbeat', 'event: node_finished', 'data: {', 'data: "output":"你好"}', '',
      'event: run_finished', 'data: {"elapsedMs":12}', '', ''
    ].join(newline)
    expect(await collect(stream(text))).toEqual([
      { event: 'node_finished', data: { output: '你好' } },
      { event: 'run_finished', data: { elapsedMs: 12 } }
    ])
  })
}

for (const suffix of ['', '\n', '\r\n', '\r']) {
  test(`retains final event without blank separator (${JSON.stringify(suffix)})`, async () => {
    expect(await collect(stream('event: run_finished\ndata: {"output":"完成"}' + suffix))).toEqual([
      { event: 'run_finished', data: { output: '完成' } }
    ])
  })
}

test('decodes byte-split UTF-8 and CRLF without corrupting tokens', async () => {
  expect(await collect(stream('event: node_token\r\ndata: {"delta":"中文🎉"}\r\n\r\n', true))).toEqual([
    { event: 'node_token', data: { delta: '中文🎉' } }
  ])
})

test('resets event names, ignores comments and preserves plain-text whitespace', async () => {
  const text = ': heartbeat\nevent: node_log\ndata:  indented  \n\ndata: raw text\n\n'
  expect(await collect(stream(text))).toEqual([
    { event: 'node_log', data: ' indented  ' },
    { event: 'message', data: 'raw text' }
  ])
})

test('ignores heartbeat/event-only blocks and accepts empty data fields', async () => {
  expect(await collect(stream(': heartbeat\n\nevent: ignored\n\ndata:\n\n'))).toEqual([
    { event: 'message', data: '' }
  ])
})

test('cancels and unlocks the response when a consumer stops early', async () => {
  let canceled = false
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('data: {"ok":true}\n\n'))
    },
    cancel() { canceled = true }
  })
  for await (const event of parseEventStream(body)) {
    expect(event.data).toEqual({ ok: true })
    break
  }
  expect(canceled).toBe(true)
  expect(body.locked).toBe(false)
})

test('releases the reader after a network failure', async () => {
  const body = new ReadableStream<Uint8Array>({
    start(controller) { controller.error(new Error('connection lost')) }
  })
  await expect(collect(body)).rejects.toThrow('connection lost')
  expect(body.locked).toBe(false)
})

test('preserves callback errors even if cancellation fails', async () => {
  const body = new ReadableStream<Uint8Array>({
    start(controller) { controller.enqueue(new TextEncoder().encode('data: {}\n\n')) },
    cancel() { throw new Error('cleanup failed') }
  })
  async function consume() {
    for await (const _ of parseEventStream(body)) throw new Error('consumer failed')
  }
  await expect(consume()).rejects.toThrow('consumer failed')
  expect(body.locked).toBe(false)
})
