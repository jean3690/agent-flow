import { expect, test } from '@playwright/test'
import { mockEditor } from './fixtures'

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR6kAAAAASUVORK5CYII=', 'base64')

async function executionWithOutput(page: any, output: any) {
  const record = { id: 1, runId: 'file-run', workflowId: 1, workflowName: '文件输出', status: 'SUCCESS',
    nodeCount: 0, elapsedMs: 1, startedAt: '2026-11-23T10:00:00' }
  await page.route((url: URL) => url.pathname === '/api/executions', (route: any) => route.fulfill({
    json: { code: 0, data: { records: [record], total: 1 } }
  }))
  await page.route('**/api/executions/file-run', (route: any) => route.fulfill({
    json: { code: 0, data: { ...record, input: '{}', output: JSON.stringify(output), nodes: [] } }
  }))
  await page.goto('/#/executions')
  await page.getByRole('button', { name: '详情', exact: true }).click()
}

test('file-center preview and download carry auth without placing tokens in URLs', async ({ page }) => {
  await mockEditor(page)
  const requests: any[] = []
  await page.route((url) => url.pathname === '/api/files', route => route.fulfill({ json: { code: 0, data: [
    { name: 'a.txt', path: 'a.txt', fileName: 'a.txt', url: '/files/users/1/a.txt', contentType: 'text/plain', size: 7, updatedAt: 1 }
  ] } }))
  await page.route('**/api/files/users/1/a.txt*', async route => {
    requests.push({ url: route.request().url(), auth: route.request().headers().authorization })
    await route.fulfill({ contentType: 'text/plain', body: 'private' })
  })
  await page.goto('/#/files')
  await page.getByRole('button', { name: '预览', exact: true }).click()
  await expect(page.getByRole('dialog').locator('pre')).toHaveText('private')
  const download = page.waitForEvent('download')
  await page.getByRole('dialog').getByRole('button', { name: '下载', exact: true }).click()
  expect((await download).suggestedFilename()).toBe('a.txt')
  expect(requests).toHaveLength(2)
  expect(requests.every(request => request.auth === 'Bearer test-token')).toBe(true)
  expect(requests.every(request => !request.url.includes('test-token'))).toBe(true)
})

test('protected media uses blobs, remote media never receives JWT, and navigation revokes blobs', async ({ page }) => {
  await page.addInitScript(() => {
    ;(window as any).revoked = []
    const revoke = URL.revokeObjectURL
    URL.revokeObjectURL = url => { (window as any).revoked.push(url); revoke.call(URL, url) }
  })
  await mockEditor(page)
  const auth: Record<string, string | undefined> = {}
  await page.route('**/api/files/users/1/image.png', async route => {
    auth.local = route.request().headers().authorization
    await route.fulfill({ contentType: 'image/png', body: png })
  })
  await page.route('https://remote.example/api/files/public.png', async route => {
    auth.remote = route.request().headers().authorization
    await route.fulfill({ contentType: 'image/png', body: png })
  })
  await executionWithOutput(page, { imageUrl: '/files/users/1/image.png', posterUrl: 'https://remote.example/api/files/public.png' })
  const image = page.getByRole('dialog').locator('img[src^="blob:"]')
  await expect(image).toBeVisible()
  const url = await image.getAttribute('src')
  await expect(page.getByRole('dialog').locator('img[src^="https://remote.example"]')).toBeVisible()
  expect(auth.local).toBe('Bearer test-token')
  expect(auth.remote).toBeUndefined()
  await page.goto('/#/editor/1')
  await page.waitForFunction(value => (window as any).revoked.includes(value), url)
})

test('a denied file never falls back to an anonymous image request', async ({ page }) => {
  await mockEditor(page)
  const requests: string[] = []
  await page.route('**/api/files/users/2/private.png', async route => {
    requests.push(route.request().headers().authorization)
    await route.fulfill({ status: 404, json: { code: 4040, message: '文件不存在' } })
  })
  await executionWithOutput(page, { imageUrl: '/files/users/2/private.png' })
  await expect(page.getByRole('dialog').getByText('文件不可访问（HTTP 404）', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog').locator('img')).toHaveCount(0)
  expect(requests).toEqual(['Bearer test-token'])
})

test('file fetch helper refuses foreign look-alike origins before making a credentialed request', async ({ page }) => {
  await mockEditor(page)
  const result = await page.evaluate(async () => {
    const { fetchPlatformFile, platformFileUrl } = await import('/src/utils/protectedFiles.ts')
    const original = window.fetch
    let calls = 0
    window.fetch = async () => { calls++; return new Response('unexpected') }
    try {
      let rejected = false
      try { await fetchPlatformFile('https://remote.example/api/files/private.png') } catch { rejected = true }
      return { calls, rejected, local: platformFileUrl('/files/users/1/a.png'),
        foreign: platformFileUrl('https://remote.example/api/files/private.png') }
    } finally { window.fetch = original }
  })
  expect(result).toEqual({ calls: 0, rejected: true, local: '/api/files/users/1/a.png', foreign: null })
})

test('leaving the file center aborts an unfinished authenticated download', async ({ page }) => {
  await mockEditor(page)
  await page.route((url) => url.pathname === '/api/files', route => route.fulfill({ json: { code: 0, data: [
    { path: 'a.txt', fileName: 'a.txt', url: '/files/users/1/a.txt', contentType: 'text/plain', size: 7, updatedAt: 1 }
  ] } }))
  let pending: any
  let started!: () => void
  const requested = new Promise<void>(resolve => { started = resolve })
  await page.route('**/api/files/users/1/a.txt?download=true', route => { pending = route; started() })
  await page.goto('/#/files')
  await page.getByRole('button', { name: '下载', exact: true }).click()
  await requested
  expect(pending.request().headers().authorization).toBe('Bearer test-token')
  const failed = page.waitForEvent('requestfailed', { predicate: request => request.url().includes('/api/files/users/1/a.txt') })
  await page.goto('/#/editor/1')
  await failed
  await pending.fulfill({ contentType: 'text/plain', body: 'late private file' }).catch(() => {})
})
