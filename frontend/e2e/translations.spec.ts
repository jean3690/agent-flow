import { test, expect } from '@playwright/test'

test.use({
  permissions: ['microphone'],
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] }
})

test('browser microphone reaches the real platform/Python bridge in explicit mock mode', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async options => {
      const stream = await original(options)
      ;(window as any).__translationStream = stream
      return stream
    }
  })
  await page.goto('/')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await page.getByRole('button', { name: '实时翻译', exact: true }).click()
  await page.waitForURL('**/#/live-translation')
  await page.locator('.live-page__form .el-select').first().click()
  await page.getByRole('option', { name: 'Mock（仅验证链路）' }).click()
  await page.getByRole('button', { name: '开始翻译' }).click()
  await expect(page.getByText('正在翻译', { exact: true })).toBeVisible()
  await expect(page.getByText('当前为模拟模式：不识别语音，不生成真实译文或译音')).toBeVisible()
  await page.getByRole('button', { name: '结束并收尾' }).click()
  await expect(page.getByText('已结束', { exact: true })).toBeVisible()
  await expect(page.getByText('[mock] 模拟链路已结束，未识别或翻译麦克风语音。')).toBeVisible()
  expect(await page.evaluate(() => (window as any).__translationStream.getTracks().every((track: MediaStreamTrack) => track.readyState === 'ended'))).toBe(true)
  expect(errors).toEqual([])
})
