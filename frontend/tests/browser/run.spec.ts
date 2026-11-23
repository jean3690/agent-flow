import { expect, test } from '@playwright/test'
import { mockEditor } from './fixtures'

test('the run store handles CRLF events and surfaces an incomplete stream', async ({ page }) => {
  await mockEditor(page)
  const result = await page.evaluate(async () => {
    // Import via Vite so this exercises the same store instance as the UI.
    const { useRunStore } = await import('/src/stores/run.ts')
    const store = useRunStore()
    const originalFetch = window.fetch
    const started = 'event: run_started\r\ndata: {"runId":"r1","nodeCount":1}\r\n\r\n'
      + 'event: node_started\r\ndata: {"nodeId":"n1","nodeName":"节点"}\r\n\r\n'
    let body = started + 'event: node_finished\r\ndata: {"nodeId":"n1","output":"你好","elapsedMs":1}\r\n\r\n'
      + 'event: run_finished\r\ndata: {"output":"完成","elapsedMs":2}\r\n\r\n'
    window.fetch = async () => new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
    try {
      await store.start(1, {})
      const completed = { output: store.output, error: store.error, status: store.nodeStatus.n1, running: store.running }
      body = started
      await store.start(1, {})
      return { completed, interrupted: { error: store.error, status: store.nodeStatus.n1, running: store.running } }
    } finally {
      window.fetch = originalFetch
    }
  })
  expect(result.completed).toEqual({ output: '完成', error: '', status: 'success', running: false })
  expect(result.interrupted.error).toContain('未收到结束事件')
  expect(result.interrupted.status).toBe('interrupted')
  expect(result.interrupted.running).toBe(false)
})

test('a late aborted request cannot clear or corrupt the next running session', async ({ page }) => {
  await mockEditor(page)
  const result = await page.evaluate(async () => {
    const { useRunStore } = await import('/src/stores/run.ts')
    const store = useRunStore()
    const originalFetch = window.fetch
    let rejectFirst!: (reason: Error) => void
    let streamController!: ReadableStreamDefaultController<Uint8Array>
    let calls = 0
    window.fetch = async () => {
      if (++calls === 1) return new Promise<Response>((_, reject) => { rejectFirst = reject })
      return new Response(new ReadableStream<Uint8Array>({
        start(controller) { streamController = controller }
      }), { headers: { 'Content-Type': 'text/event-stream' } })
    }
    try {
      const first = store.start(1, {})
      store.stop()
      const second = store.start(1, {})
      rejectFirst(new DOMException('aborted', 'AbortError'))
      await first
      const stillRunning = store.running
      streamController.enqueue(new TextEncoder().encode('event: run_finished\ndata: {"output":"第二次运行"}\n\n'))
      await second
      return { stillRunning, output: store.output, error: store.error, running: store.running }
    } finally {
      window.fetch = originalFetch
      store.stop()
    }
  })
  expect(result).toEqual({ stillRunning: true, output: '第二次运行', error: '', running: false })
})

test('terminal events cancel lingering streams and failure clears active node status', async ({ page }) => {
  await mockEditor(page)
  const result = await page.evaluate(async () => {
    const { useRunStore } = await import('/src/stores/run.ts')
    const store = useRunStore()
    const originalFetch = window.fetch
    let canceled = false
    window.fetch = async () => new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(
          'event: run_started\ndata: {"runId":"failed-run","nodeCount":1}\n\n'
          + 'event: node_started\ndata: {"nodeId":"n1"}\n\n'
          + 'event: run_failed\ndata: {"error":{"message":"模型不可用"}}\n\n'
        ))
      },
      cancel() { canceled = true }
    }), { headers: { 'Content-Type': 'text/event-stream' } })
    try {
      await store.start(1, {})
      const failure = { error: store.error, status: store.nodeStatus.n1, failedRunId: store.failedRunId, running: store.running }
      store.reset()
      return { canceled, failure, clearedResume: store.failedRunId }
    } finally {
      window.fetch = originalFetch
    }
  })
  expect(result.canceled).toBe(true)
  expect(result.failure).toEqual({ error: '模型不可用', status: 'failed', failedRunId: 'failed-run', running: false })
  expect(result.clearedResume).toBe('')
})

test('HTTP execution errors display the API message instead of raw JSON', async ({ page }) => {
  await mockEditor(page)
  await page.route('**/api/workflows/1/execute', async (route) => {
    await route.fulfill({ status: 503, json: { code: 503, message: '执行队列已满', data: null } })
  })
  await page.getByRole('button', { name: '调试运行', exact: true }).click()
  await page.locator('.debug').getByRole('button', { name: '运行', exact: true }).click()
  await expect(page.locator('.debug__msg').filter({ hasText: '执行队列已满' })).toHaveText('执行队列已满')
  await expect(page.locator('.debug').getByRole('button', { name: '运行', exact: true })).toBeEnabled()
})

for (const entry of ['initial mount', 'query update']) {
  test(`resume query loads original input once on ${entry}`, async ({ page }) => {
    await mockEditor(page)
    const requests: any[] = []
    await page.route('**/api/executions/previous-run', async (route) => {
      await route.fulfill({ json: { code: 0, data: { input: '{"topic":"原始输入"}' } } })
    })
    await page.route('**/api/workflows/1/execute', async (route) => {
      requests.push(route.request().postDataJSON())
      await route.fulfill({ contentType: 'text/event-stream', body: 'event: run_finished\ndata: {"output":"续跑完成"}\n\n' })
    })
    if (entry === 'initial mount') await page.goto('/#/')
    await page.goto('/#/editor/1?resume=previous-run')
    await expect(page.locator('.debug__msg').filter({ hasText: '执行完成' })).toBeVisible()
    expect(requests).toEqual([{ input: { topic: '原始输入' }, resumeRunId: 'previous-run' }])
    await page.locator('.debug').getByRole('button', { name: '收起', exact: true }).click()
    await page.getByRole('button', { name: '调试运行', exact: true }).click()
    await expect(page.locator('.debug')).toBeVisible()
    expect(requests).toHaveLength(1)
  })
}

test('debug input rejects non-object JSON before submitting an execution', async ({ page }) => {
  await mockEditor(page)
  let requests = 0
  await page.route('**/api/workflows/1/execute', async (route) => {
    requests++
    await route.fulfill({ contentType: 'text/event-stream', body: 'event: run_finished\ndata: {}\n\n' })
  })
  await page.getByRole('button', { name: '调试运行', exact: true }).click()
  for (const value of ['null', '[]', '"字符串"']) {
    await page.locator('.debug textarea').fill(value)
    await page.locator('.debug').getByRole('button', { name: '运行', exact: true }).click()
  }
  await expect(page.getByText('输入必须是 JSON 对象，例如 {"topic":"主题"}', { exact: true }).first()).toBeVisible()
  expect(requests).toBe(0)
})

test('an incompatible resume displays the conflict without silently running the full workflow', async ({ page }) => {
  await mockEditor(page)
  const requests: any[] = []
  await page.route('**/api/executions/old-run', async (route) => {
    await route.fulfill({ json: { code: 0, data: { input: '{"topic":"原始输入"}' } } })
  })
  await page.route('**/api/workflows/1/execute', async (route) => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ status: 409, json: { code: 4090, message: '执行输入、工作流定义或运行配置已变化，请完整重跑' } })
  })
  await page.goto('/#/editor/1?resume=old-run')
  await expect(page.locator('.debug__msg').filter({ hasText: '运行配置已变化' })).toBeVisible()
  await expect(page.locator('.debug').getByRole('button', { name: '运行', exact: true })).toBeEnabled()
  expect(requests).toEqual([{ input: { topic: '原始输入' }, resumeRunId: 'old-run' }])
})

test('execution details distinguish cached output and show the resume source', async ({ page }) => {
  await mockEditor(page)
  const record = { id: 1, runId: 'resumed-run', workflowId: 1, workflowName: '续跑示例', status: 'SUCCESS',
    nodeCount: 1, elapsedMs: 1, startedAt: '2026-11-23T10:00:00', totalTokens: 0 }
  await page.route((url) => url.pathname === '/api/executions', async (route) => {
    await route.fulfill({ json: { code: 0, data: { records: [record], total: 1 } } })
  })
  await page.route('**/api/executions/resumed-run', async (route) => {
    await route.fulfill({ json: { code: 0, data: { ...record, resumeRunId: 'old-run', nodes: [
      { nodeId: 't', nodeType: 'template', nodeName: '模板', status: 'SUCCESS', cacheHit: true, elapsedMs: 0, output: '{"text":"cached"}' }
    ] } } })
  })
  await page.goto('/#/executions')
  await page.getByRole('button', { name: '详情', exact: true }).click()
  const detail = page.getByRole('dialog')
  await expect(detail.getByText('复用历史输出', { exact: true })).toBeVisible()
  await expect(detail.getByText('续跑来源：old-run', { exact: true })).toBeVisible()
})
