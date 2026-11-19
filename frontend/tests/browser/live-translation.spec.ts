import { test, expect, type Page } from '@playwright/test'

test.use({
  permissions: ['microphone'],
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] }
})

async function setup(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('agentflow_token', 'test-token')
    const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await getUserMedia(constraints)
      ;(window as any).__translationStream = stream
      return stream
    }
  })
  await page.route('**/api/auth/me', route => route.fulfill({ json: { code: 0, data: { id: 1, username: 'admin', role: 'ADMIN' } } }))
  await page.route('**/api/translations/realtime/sessions', route => route.fulfill({ json: { code: 0, data: { ticket: 'a'.repeat(43), mock: false } } }))
}

test('microphone streams PCM and drains final subtitles after finish', async ({ page }) => {
  await setup(page)
  let audioFrames = 0
  let resultSent = false
  await page.routeWebSocket('**/api/translations/realtime/ws', ws => {
    expect(ws.url()).not.toContain('ticket')
    ws.onMessage(raw => {
      const message = JSON.parse(String(raw))
      if (message.type === 'connect') {
        expect(message.ticket).toBe('a'.repeat(43))
        ws.send(JSON.stringify({ type: 'session.ready', mock: false }))
      } else if (message.type === 'audio') {
        audioFrames++
        expect(Buffer.from(message.audio, 'base64').length).toBeLessThanOrEqual(16000)
        if (!resultSent) {
          resultSent = true
          ws.send(JSON.stringify({ type: 'transcript.delta', itemId: 'source', delta: '你好' }))
          ws.send(JSON.stringify({ type: 'transcript.done', itemId: 'source', text: '你好世界' }))
          ws.send(JSON.stringify({ type: 'translation.delta', itemId: 'target', delta: 'Hello' }))
          ws.send(JSON.stringify({ type: 'audio.delta', delta: Buffer.alloc(480).toString('base64'), sampleRate: 24000 }))
        }
      } else if (message.type === 'finish') {
        ws.send(JSON.stringify({ type: 'translation.done', itemId: 'target', text: 'Hello world' }))
        ws.send(JSON.stringify({ type: 'usage', usage: { total_tokens: 15 } }))
        ws.send(JSON.stringify({ type: 'usage', usage: { total_tokens: 20 } }))
        ws.send(JSON.stringify({ type: 'session.finished' }))
      }
    })
  })
  await page.goto('/#/live-translation')
  await page.getByRole('button', { name: '开始翻译' }).click()
  await expect(page.getByText('正在翻译', { exact: true })).toBeVisible()
  await expect(page.getByText('你好世界', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '结束并收尾' }).click()
  await expect(page.getByText('已结束', { exact: true })).toBeVisible()
  await expect(page.getByText('Hello world', { exact: true })).toBeVisible()
  await expect(page.getByText('累计 20 tokens', { exact: false })).toBeVisible()
  expect(audioFrames).toBeGreaterThan(0)
  expect(await page.evaluate(() => (window as any).__translationStream.getTracks().every((track: MediaStreamTrack) => track.readyState === 'ended'))).toBe(true)
})

test('provider error stops capture and preserves an actionable error', async ({ page }) => {
  await setup(page)
  await page.routeWebSocket('**/api/translations/realtime/ws', ws => {
    ws.onMessage(raw => {
      if (JSON.parse(String(raw)).type === 'connect') ws.send(JSON.stringify({ type: 'error', message: '请检查业务空间和模型权限' }))
    })
  })
  await page.goto('/#/live-translation')
  await page.getByRole('button', { name: '开始翻译' }).click()
  await expect(page.getByText('请检查业务空间和模型权限')).toBeVisible()
  await expect(page.getByRole('button', { name: '开始翻译' })).toBeEnabled()
  expect(await page.evaluate(() => (window as any).__translationStream.getTracks().every((track: MediaStreamTrack) => track.readyState === 'ended'))).toBe(true)
})

test('microphone denial never creates a cloud session', async ({ page }) => {
  await setup(page)
  let requested = false
  await page.route('**/api/translations/realtime/sessions', route => { requested = true; return route.abort() })
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new Error('麦克风权限已拒绝，请在浏览器中允许') }
  })
  await page.goto('/#/live-translation')
  await page.getByRole('button', { name: '开始翻译' }).click()
  await expect(page.getByText('麦克风权限已拒绝，请在浏览器中允许')).toBeVisible()
  expect(requested).toBe(false)
})

test('cancel during session creation cannot revive the old recording', async ({ page }) => {
  await setup(page)
  let release: (() => void) | undefined
  await page.route('**/api/translations/realtime/sessions', async route => {
    await new Promise<void>(resolve => { release = resolve })
    await route.fulfill({ json: { code: 0, data: { ticket: 'a'.repeat(43) } } })
  })
  let connected = false
  await page.routeWebSocket('**/api/translations/realtime/ws', () => { connected = true })
  await page.goto('/#/live-translation')
  await page.getByRole('button', { name: '开始翻译' }).click()
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.getByRole('button', { name: '取消', exact: true }).click()
  release?.()
  await expect(page.getByText('未开始', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始翻译' })).toBeEnabled()
  expect(connected).toBe(false)
  expect(await page.evaluate(() => (window as any).__translationStream.getTracks().every((track: MediaStreamTrack) => track.readyState === 'ended'))).toBe(true)
})
