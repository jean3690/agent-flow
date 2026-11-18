import { expect, test } from '@playwright/test'
import { mockEditor } from './fixtures'

test('renaming tracks unsaved changes and undo restores the clean draft', async ({ page }) => {
  const { workflow } = await mockEditor(page)
  await page.getByPlaceholder('未命名工作流').fill('新的名称')
  await expect(page.locator('.editor__dirty')).toBeVisible()
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(page.getByPlaceholder('未命名工作流')).toHaveValue(workflow.name)
  await expect(page.locator('.editor__dirty')).toHaveCount(0)
  await page.getByRole('button', { name: '重做', exact: true }).click()
  await expect(page.getByPlaceholder('未命名工作流')).toHaveValue('新的名称')
  await expect(page.locator('.editor__dirty')).toBeVisible()
})

test('selecting a node changes neither dirty state nor undo history', async ({ page }) => {
  await mockEditor(page)
  await page.locator('.vue-flow__node').first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.locator('.editor__dirty')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
})

test('immediate undo includes a change still in the debounce window', async ({ page }) => {
  await mockEditor(page)
  await page.locator('aside').getByText('开始', { exact: true }).click()
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(page.locator('.vue-flow__node')).toHaveCount(2)
  await expect(page.locator('.editor__dirty')).toHaveCount(0)
  await page.getByRole('button', { name: '重做', exact: true }).click()
  await expect(page.locator('.vue-flow__node')).toHaveCount(3)
})

test('Ctrl+S works in the name field and preserves the workflow status', async ({ page }) => {
  const { updates } = await mockEditor(page)
  await page.getByPlaceholder('未命名工作流').fill('快捷键保存')
  await page.getByPlaceholder('未命名工作流').press('Control+s')
  await expect(page.locator('.editor__dirty')).toHaveCount(0)
  expect(updates).toHaveLength(1)
  expect(updates[0].name).toBe('快捷键保存')
  expect(updates[0].status).toBe(0)
})

test('in-flight saves freeze the payload, retain later edits, and deduplicate requests', async ({ page }) => {
  const { workflow } = await mockEditor(page)
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  const requests: any[] = []
  await page.route('**/api/workflows/1', async (route) => {
    if (route.request().method() !== 'PUT') return route.fallback()
    const payload = route.request().postDataJSON()
    requests.push(payload)
    await gate
    await route.fulfill({ json: { code: 0, data: { ...workflow, ...payload, version: 2 } } })
  })
  await page.getByPlaceholder('未命名工作流').fill('提交时的名称')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => requests.length).toBe(1)
  await page.getByPlaceholder('未命名工作流').fill('保存期间的新名称')
  await page.getByPlaceholder('未命名工作流').press('Control+s')
  await page.getByPlaceholder('未命名工作流').press('Control+s')
  expect(requests).toHaveLength(1)
  release()
  await expect(page.getByText('已保存，后续修改仍待保存', { exact: true })).toBeVisible()
  await expect(page.locator('.editor__dirty')).toBeVisible()
  expect(requests[0].name).toBe('提交时的名称')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.editor__dirty')).toHaveCount(0)
  expect(requests).toHaveLength(2)
  expect(requests[1].name).toBe('保存期间的新名称')
})

test('failed saves keep the draft and prevent starting a different server graph', async ({ page }) => {
  await mockEditor(page)
  await page.route('**/api/workflows/1', async (route) => {
    if (route.request().method() !== 'PUT') return route.fallback()
    await route.fulfill({ status: 503, json: { message: '暂时不可用' } })
  })
  await page.getByPlaceholder('未命名工作流').fill('不能丢失的修改')
  await page.getByRole('button', { name: '调试运行', exact: true }).click()
  await expect(page.getByText('暂时不可用', { exact: true })).toBeVisible()
  await expect(page.locator('.editor__dirty')).toBeVisible()
  await expect(page.locator('.debug')).toHaveCount(0)
})

test('editing during automatic save does not launch the stale graph', async ({ page }) => {
  const { workflow } = await mockEditor(page)
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  let submitted = false
  await page.route('**/api/workflows/1', async (route) => {
    if (route.request().method() !== 'PUT') return route.fallback()
    const payload = route.request().postDataJSON()
    submitted = true
    await gate
    await route.fulfill({ json: { code: 0, data: { ...workflow, ...payload, version: 2 } } })
  })
  await page.getByPlaceholder('未命名工作流').fill('自动保存的名称')
  await page.getByRole('button', { name: '调试运行', exact: true }).click()
  await expect.poll(() => submitted).toBe(true)
  await page.getByPlaceholder('未命名工作流').fill('更新但未保存的名称')
  release()
  await expect(page.getByText('保存期间有新的修改，请再次保存后运行或发布', { exact: true })).toBeVisible()
  await expect(page.locator('.editor__dirty')).toBeVisible()
  await expect(page.locator('.debug')).toHaveCount(0)
})

test('leaving prompts to keep or discard unsaved changes', async ({ page }) => {
  await mockEditor(page)
  await page.getByPlaceholder('未命名工作流').fill('未保存的名称')
  await page.getByRole('button', { name: '← 工作流' }).click()
  await page.getByRole('button', { name: '继续编辑', exact: true }).click()
  await expect(page).toHaveURL(/#\/editor\/1$/)
  await expect(page.getByPlaceholder('未命名工作流')).toHaveValue('未保存的名称')
  await page.getByRole('button', { name: '← 工作流' }).click()
  await page.getByRole('button', { name: '放弃修改并离开', exact: true }).click()
  await expect(page).toHaveURL(/#\/$/)
})

test('refresh protection is enabled only for unsaved changes', async ({ page }) => {
  await mockEditor(page)
  const isPrevented = () => page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return event.defaultPrevented
  })
  expect(await isPrevented()).toBe(false)
  await page.getByPlaceholder('未命名工作流').fill('刷新前需保存')
  expect(await isPrevented()).toBe(true)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.editor__dirty')).toHaveCount(0)
  expect(await isPrevented()).toBe(false)
})

test('renaming a published workflow saves before publishing the new draft', async ({ page }) => {
  const { updates } = await mockEditor(page, true)
  await expect(page.getByRole('button', { name: '已发布', exact: true })).toBeVisible()
  await page.getByPlaceholder('未命名工作流').fill('新发布的名称')
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.getByText('线上 v2', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '已发布', exact: true })).toBeVisible()
  expect(updates[0].name).toBe('新发布的名称')
})

test('switching editor route IDs confirms changes and loads the correct workflow', async ({ page }) => {
  await mockEditor(page)
  await page.getByPlaceholder('未命名工作流').fill('当前修改')
  await page.evaluate(() => { location.hash = '#/editor/2' })
  await page.getByRole('button', { name: '放弃修改并离开', exact: true }).click()
  await expect(page.getByPlaceholder('未命名工作流')).toHaveValue('另一个工作流')
  await expect(page.locator('.editor__dirty')).toHaveCount(0)
})

test('a loading failure offers retry and cannot overwrite an unloaded workflow', async ({ page }) => {
  await mockEditor(page)
  let fail = true
  await page.route('**/api/workflows/2', async (route) => {
    if (!fail) return route.fallback()
    await route.fulfill({ status: 503, json: { message: '读取失败' } })
  })
  await page.evaluate(() => { location.hash = '#/editor/2' })
  await expect(page.getByText('工作流加载失败', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
  fail = false
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.getByPlaceholder('未命名工作流')).toHaveValue('另一个工作流')
  await expect(page.getByRole('button', { name: '保存', exact: true })).toBeEnabled()
})
