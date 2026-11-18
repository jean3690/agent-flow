import { test, expect } from '@playwright/test'

async function addNode(page: any, label: string) {
  await page.locator('aside').getByText(label, { exact: true }).click()
  await page.waitForTimeout(200)
}

async function transforms(page: any) {
  return page.$$eval('.vue-flow__node', (els: any[]) => els.map((el) => el.getAttribute('style') || ''))
}

test('canvas orchestration: auto layout, undo and redo', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await expect(page.url()).toContain('#/')

  await page.getByRole('button', { name: '新建工作流' }).click()
  await page.getByPlaceholder('例如：文章摘要流水线').fill('Playwright 编排测试')
  await page.getByRole('button', { name: '创建并编辑' }).click()
  await page.waitForURL('**/#/editor/**', { timeout: 15000 })

  await addNode(page, '开始')
  await addNode(page, '文本模板')
  await addNode(page, '结束')
  await expect(page.locator('.vue-flow__node')).toHaveCount(3)

  const before = await transforms(page)
  await page.getByRole('button', { name: '自动布局' }).click()
  await page.waitForTimeout(600)
  const after = await transforms(page)
  expect(after).not.toEqual(before)

  await page.getByRole('button', { name: '撤销' }).click()
  await page.waitForTimeout(400)
  expect(await transforms(page)).toEqual(before)

  await page.getByRole('button', { name: '重做' }).click()
  await page.waitForTimeout(400)
  expect(await transforms(page)).toEqual(after)
})

test('publish workflow and inspect versions', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await expect(page.url()).toContain('#/')

  await page.getByRole('button', { name: '新建工作流' }).click()
  await page.getByPlaceholder('例如：文章摘要流水线').fill('Playwright 发布测试')
  await page.getByRole('button', { name: '创建并编辑' }).click()
  await page.waitForURL('**/#/editor/**', { timeout: 15000 })

  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.getByText('线上 v1')).toBeVisible()

  await page.getByRole('button', { name: '版本', exact: true }).click()
  const versionDialog = page.getByRole('dialog', { name: '版本历史' })
  await expect(versionDialog.getByText('v1', { exact: true }).first()).toBeVisible()
  await expect(versionDialog.getByText('已发布', { exact: true })).toBeVisible()
})
