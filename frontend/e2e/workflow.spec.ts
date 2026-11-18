import { test, expect } from '@playwright/test'

async function nodeIds(page: any) {
  return page.$$eval('.vue-flow__node', (els: any[]) => els.map((e) => e.getAttribute('data-id') || ''))
}

async function nodeCount(page: any) {
  return page.locator('.vue-flow__node').count()
}

// Click a palette item in the left sidebar. Adding a node must NOT open the config drawer.
async function addNode(page: any, label: string) {
  await page.locator('aside').getByText(label, { exact: true }).click()
  await page.waitForTimeout(200)
}

async function fitView(page: any) {
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('.vue-flow__controls-button'))
    const fit = btns.find((b) => /fit/i.test((b as any).title || b.getAttribute('aria-label') || b.textContent || ''))
    if (fit) (fit as any).click()
  })
  await page.waitForTimeout(300)
}

// Read a handle's center in viewport coordinates via the DOM (no stability wait),
// so connection setup never blocks on Vue Flow's re-render animations.
async function handleCenter(page: any, nodeId: string, kind: string) {
  return page.evaluate(
    (args: any) => {
      const cls = args.kind === 'source' ? 'vue-flow__handle.source' : 'vue-flow__handle.target'
      const el = document.querySelector('[data-id="' + args.id + '"] .' + cls)
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
    },
    { id: nodeId, kind }
  )
}

// Drag from the source handle of sourceId to the target handle of targetId.
async function connect(page: any, sourceId: string, targetId: string) {
  for (let i = 0; i < 12; i++) {
    const s: any = await handleCenter(page, sourceId, 'source')
    const t: any = await handleCenter(page, targetId, 'target')
    if (s && t) {
      await page.mouse.move(s.x, s.y)
      await page.mouse.down()
      await page.mouse.move((s.x + t.x) / 2, (s.y + t.y) / 2, { steps: 5 })
      await page.mouse.move(t.x, t.y, { steps: 8 })
      await page.mouse.up()
    }
    await page.waitForTimeout(300)
    const ok: boolean = await page.evaluate(
      (args: any) => {
        const edges = Array.from(document.querySelectorAll('.vue-flow__edge'))
        return edges.some((e) => {
          const id = e.getAttribute('data-id') || ''
          return id.indexOf(args.s) !== -1 && id.indexOf(args.t) !== -1
        })
      },
      { s: sourceId, t: targetId }
    )
    if (ok) return
  }
  throw new Error('failed to connect ' + sourceId + ' -> ' + targetId)
}

test('build and run a minimal workflow through the canvas', async ({ page }) => {
  const errors: string[] = []
  page.on('console', (msg: any) => {
    if (msg.type() === 'error') {
      const text = String(msg.text())
      if (text.indexOf('favicon') === -1) errors.push(text)
    }
  })
  page.on('pageerror', (err: any) => errors.push(String(err)))

  await page.goto('/')

  // login (credentials are prefilled)
  await page.getByRole('button', { name: '进入工作台' }).click()
  await expect(page.url()).toContain('#/')

  // create a new workflow
  await page.getByRole('button', { name: '新建工作流' }).click()
  await page.getByPlaceholder('例如：文章摘要流水线').waitFor()
  await page.getByPlaceholder('例如：文章摘要流水线').fill('Playwright UI E2E')
  await page.getByRole('button', { name: '创建并编辑' }).click()
  await page.waitForURL('**/#/editor/**', { timeout: 15000 })

  // add nodes: 开始 -> 文本模板 -> 结束
  // (adding 开始 previously threw DataCloneError; this asserts it no longer does)
  await addNode(page, '开始')
  await expect(nodeCount(page)).resolves.toBe(1)
  await addNode(page, '文本模板')
  await expect(nodeCount(page)).resolves.toBe(2)
  await addNode(page, '结束')
  await expect(nodeCount(page)).resolves.toBe(3)

  const ids: string[] = await nodeIds(page)
  const inputId = ids.find((id) => id.indexOf('input-') === 0)
  const templateId = ids.find((id) => id.indexOf('template-') === 0)
  const outputId = ids.find((id) => id.indexOf('output-') === 0)
  expect(inputId).toBeTruthy()
  expect(templateId).toBeTruthy()
  expect(outputId).toBeTruthy()

  // bring all nodes into view so handles are reachable
  await fitView(page)

  // connect them
  await connect(page, inputId as string, templateId as string)
  await connect(page, templateId as string, outputId as string)
  await expect(page.locator('.vue-flow__edge').count()).resolves.toBe(2)

  // save
  await page.getByRole('button', { name: '保存' }).click()
  await page.waitForTimeout(300)

  // debug run
  await page.getByRole('button', { name: '调试运行' }).click()
  const box = page.locator('div[role="dialog"]').getByRole('textbox')
  await box.fill('{"input":"Playwright UI e2e 验证"}')
  await page.getByRole('button', { name: '运行', exact: true }).click()

  // assert the whole graph executed
  await expect(page.getByText('执行完成')).toBeVisible({ timeout: 30000 })
  await expect(page.getByText(/input-.*完成/)).toBeVisible()
  await expect(page.getByText(/template-.*完成/)).toBeVisible()
  await expect(page.getByText(/output-.*完成/)).toBeVisible()

  // no uncaught console errors (direct guard for the structuredClone regression)
  expect(errors).toEqual([])
})

test('config drawer opens only on node click and lists direct upstream nodes', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await expect(page.url()).toContain('#/')

  await page.getByRole('button', { name: '新建工作流' }).click()
  await page.getByPlaceholder('例如：文章摘要流水线').fill('Playwright 抽屉交互')
  await page.getByRole('button', { name: '创建并编辑' }).click()
  await page.waitForURL('**/#/editor/**', { timeout: 15000 })

  await addNode(page, '开始')
  await addNode(page, '文本模板')
  await expect(nodeCount(page)).resolves.toBe(2)

  // 添加节点不再自动弹出配置抽屉
  await expect(page.locator('.config__title')).toBeHidden()

  const ids: string[] = await nodeIds(page)
  const inputId = ids.find((id) => id.indexOf('input-') === 0) as string
  const templateId = ids.find((id) => id.indexOf('template-') === 0) as string

  await page.locator(`[data-id="${templateId}"]`).click()
  await expect(page.locator('.config__title')).toBeVisible()

  // 无上游时提示连接
  await expect(page.getByText('连接上游节点后，可在提示词里点击插入其输出字段。')).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(page.locator('.config__title')).toBeHidden()

  await fitView(page)
  await connect(page, inputId, templateId)

  await page.locator(`[data-id="${templateId}"]`).click()
  await expect(page.getByText('直接上游 / 可引用变量')).toBeVisible()
  await expect(page.locator('.config__upstream')).toHaveCount(1)

  // 点击上游输出字段 chip，应把安全引用插入当前聚焦的模板输入框
  const templateInput = page.locator('.config textarea').first()
  await templateInput.click()
  await page.locator('.config__upstream .config__chip').first().click()
  await expect(templateInput).toHaveValue(/outputs\["/)
})
