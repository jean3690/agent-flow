import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { mockEditor } from './fixtures'

// Exercise the real catalog rather than simplified test-only config schemas.
const definitions = JSON.parse(readFileSync('../java-service/src/main/resources/node-definitions.json', 'utf-8'))
const nodeNames = ['JSON 解析', '字段映射', '列表处理', '文本处理', 'CSV 转换', '日期时间', '数据校验', '编码与摘要']

for (const name of nodeNames) {
  test(`${name}: palette entry, defaults, configuration and output fields`, async ({ page }) => {
    await mockEditor(page, false, definitions)
    await page.locator('aside').getByText(name, { exact: true }).click()
    const node = page.locator('.vue-flow__node').filter({ hasText: name })
    await expect(node).toBeVisible()
    await node.click()
    const drawer = page.getByRole('dialog')
    await expect(drawer.getByText(name + ' 配置', { exact: true })).toBeVisible()
    await expect(drawer.getByText('配置本节点输出字段', { exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(drawer).toBeHidden()
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await expect(page.locator('.editor__dirty')).toHaveCount(0)
  })
}

test('list operation switches display only relevant fields without dropping their values', async ({ page }) => {
  const { updates } = await mockEditor(page, false, definitions)
  await page.locator('aside').getByText('列表处理', { exact: true }).click()
  await page.locator('.vue-flow__node').filter({ hasText: '列表处理' }).click()
  const drawer = page.getByRole('dialog')
  const action = drawer.locator('.el-form-item').filter({ has: page.getByText('操作', { exact: true }) }).locator('.el-select')
  await expect(drawer.getByText('比较值', { exact: true })).toHaveCount(0)
  await action.click()
  await page.getByRole('option', { name: '筛选', exact: true }).click()
  await expect(drawer.getByText('比较值', { exact: true })).toBeVisible()
  const field = drawer.locator('.el-form-item').filter({ has: page.getByText('字段路径', { exact: true }) }).locator('input')
  await field.fill('score')
  await action.click()
  await page.getByRole('option', { name: '截取', exact: true }).click()
  await expect(drawer.getByText('字段路径', { exact: true })).toHaveCount(0)
  await expect(drawer.getByText('起始下标（包含）', { exact: true })).toBeVisible()
  await action.click()
  await page.getByRole('option', { name: '筛选', exact: true }).click()
  await expect(field).toHaveValue('score')
  // Move focus off ElSelect: its Escape handler consumes the key even after
  // selecting an option, so the drawer should receive Escape only afterwards.
  await drawer.getByText('列表处理 配置', { exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.editor__dirty')).toHaveCount(0)
  const list = updates[0].flow.nodes.find((node: any) => node.type === 'list_process')
  expect(list.config.action).toBe('filter')
  expect(list.config.field).toBe('score')
})
