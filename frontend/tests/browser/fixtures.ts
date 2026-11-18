import { expect, type Page } from '@playwright/test'

export async function mockEditor(page: Page, published = false, nodeDefinitions?: any[]) {
  const updates: any[] = []
  const workflow: any = {
    id: 1, name: '回归测试工作流', description: '', engineType: 'langgraph',
    status: 0, version: 1, publishedVersion: published ? 1 : undefined,
    flow: {
      nodes: [
        { id: 'input-1', type: 'input', name: '开始', position: { x: 80, y: 80 }, config: {} },
        { id: 'output-1', type: 'output', name: '结束', position: { x: 360, y: 80 }, config: {} }
      ],
      edges: [{ id: 'edge-1', source: 'input-1', target: 'output-1' }]
    }
  }
  await page.addInitScript(() => localStorage.setItem('agentflow_token', 'test-token'))
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path === '/api/node-definitions') {
      data = nodeDefinitions || ['input', 'output'].map((type) => ({
        type, name: type === 'input' ? '开始' : '结束', category: '基础',
        description: '', color: '#6366f1', configSchema: [], outputSchema: []
      }))
    } else if (path === '/api/workflows') {
      data = { records: [workflow], total: 1, page: 1, size: 20 }
    } else if (path === '/api/workflows/1') {
      if (route.request().method() === 'PUT') {
        const payload = route.request().postDataJSON()
        updates.push(payload)
        Object.assign(workflow, payload, { version: workflow.version + 1 })
      }
      data = workflow
    } else if (path === '/api/workflows/2') {
      data = { ...workflow, id: 2, name: '另一个工作流' }
    } else if (path === '/api/workflows/1/publish') {
      workflow.publishedVersion = workflow.version
      data = workflow
    } else if (path === '/api/auth/me') {
      data = { id: 1, username: 'admin', role: 'ADMIN' }
    } else if (path === '/api/system/ai-health') {
      data = { up: true }
    }
    await route.fulfill({ json: { code: 0, message: 'ok', data } })
  })
  await page.goto('/#/editor/1')
  await expect(page.getByPlaceholder('未命名工作流')).toHaveValue(workflow.name)
  await expect(page.locator('.vue-flow__node')).toHaveCount(2)
  await expect(page.locator('.editor__dirty')).toHaveCount(0)
  return { workflow, updates }
}
