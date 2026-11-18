import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { mockEditor } from './fixtures'

const definitions = JSON.parse(readFileSync('../java-service/src/main/resources/node-definitions.json', 'utf-8'))
const tools = [{ name:'echo', description:'回声工具', inputSchema:{ type:'object', properties:{ text:{ type:'string' } } } }]

async function mockManagement(page: Page, admin = true) {
  const saved: any[] = []
  const skills: any[] = []
  const servers: any[] = []
  await page.addInitScript(() => localStorage.setItem('agentflow_token', 'test-token'))
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    let data: any = []
    if (path === '/api/auth/me') data = { id:1, username:'test', role:admin ? 'ADMIN' : 'USER' }
    else if (path === '/api/skills') data = skills
    else if (path.startsWith('/api/skills/')) {
      const name = path.split('/').pop()
      if (method === 'PUT') {
        const body = route.request().postDataJSON(); saved.push(body)
        data = { name, title:'测试技能', description:'说明', version:'1', tags:[], editable:true, content:body.content, rawContent:body.content, references:[] }
        skills.push(data)
      } else if (method === 'DELETE') skills.splice(0)
      else data = skills.find(item => item.name === name)
    } else if (path === '/api/mcp-servers' && method === 'GET') data = servers
    else if (path.endsWith('/discover')) { servers[0].tools = tools; data = { ok:true, tools, message:'连接成功，发现 1 个工具' } }
    else if (path.startsWith('/api/mcp-servers')) {
      const payload = route.request().postDataJSON(); saved.push(payload)
      data = { ...payload, headers:undefined, id:1, tools:servers[0]?.tools || [], hasCredentials:!!payload.headers || servers[0]?.hasCredentials || false }
      servers.splice(0, servers.length, data)
    }
    await route.fulfill({ json:{ code:0, data } })
  })
  return { saved, servers, skills }
}

test('Skills manager creates and deletes a SKILL.md', async ({ page }) => {
  const { saved } = await mockManagement(page)
  await page.goto('/#/skills')
  await page.getByRole('button', { name:'新建技能', exact:true }).click()
  await page.getByPlaceholder('report-helper').fill('testing')
  await page.getByRole('button', { name:'保存技能', exact:true }).click()
  await expect(page.getByText('技能已保存', { exact:true })).toBeVisible()
  expect(saved[0].content).toContain('name: testing')
  await page.getByRole('button', { name:'删除技能', exact:true }).click()
  await page.getByRole('button', { name:'确定', exact:true }).click()
  await expect(page.getByText('还没有技能。管理员可新建或导入 SKILL.md，然后在模型节点选择挂载。')).toBeVisible()
})

test('Skills write controls are hidden for a non-admin user', async ({ page }) => {
  await mockManagement(page, false)
  await page.goto('/#/skills')
  await expect(page.getByText('还没有技能。管理员可新建或导入 SKILL.md，然后在模型节点选择挂载。')).toBeVisible()
  await expect(page.getByRole('button', { name:'新建技能', exact:true })).toHaveCount(0)
  await expect(page.getByRole('button', { name:'导入 SKILL.md', exact:true })).toHaveCount(0)
})

test('MCP configuration saves headers without echoing them and grants tools only after discovery', async ({ page }) => {
  const { saved } = await mockManagement(page)
  await page.goto('/#/mcp')
  await page.getByRole('button', { name:'添加 MCP 服务', exact:true }).click()
  await page.getByPlaceholder('文档检索服务').fill('Docs')
  await page.getByPlaceholder('https://example.com/mcp').fill('https://docs.example/mcp')
  const headers = page.getByPlaceholder('{"Authorization":"Bearer …"}')
  await headers.fill('{"Authorization":"Bearer SECRET"}')
  await page.getByRole('button', { name:'保存配置', exact:true }).click()
  await expect(headers).toHaveValue('')
  expect(saved[0].headers.Authorization).toBe('Bearer SECRET')
  expect(saved[0].allowedTools).toEqual([])
  await page.getByRole('button', { name:'测试连接 / 发现工具', exact:true }).click()
  await expect(page.getByRole('status')).toContainText('发现 1 个工具')
  await page.getByText('echo', { exact:true }).click()
  await expect(page.getByRole('checkbox', { name:'echo', exact:true })).toBeChecked()
  await page.getByRole('button', { name:'保存配置', exact:true }).click()
  await expect(page.getByText('Docs', { exact:true })).toBeVisible()
  expect(saved.at(-1).allowedTools).toEqual(['echo'])
  expect(saved.at(-1).headers).toBeUndefined()
})

test('MCP node selects an accessible service and approved tool', async ({ page }) => {
  const { updates } = await mockEditor(page, false, definitions)
  await page.route('**/api/mcp-servers', route => route.fulfill({ json:{ code:0, data:[{ id:1, name:'Docs', enabled:true, tools, allowedTools:['echo'] }] } }))
  await page.route('**/api/mcp-servers/1/tools', route => route.fulfill({ json:{ code:0, data:tools } }))
  await page.locator('aside').getByText('MCP 工具', { exact:true }).click()
  await page.locator('.vue-flow__node').filter({ hasText:'MCP 工具' }).click()
  const drawer = page.getByRole('dialog')
  await drawer.locator('.el-form-item').filter({ has:page.getByText('MCP 服务', { exact:true }) }).locator('.el-select').click()
  await page.getByRole('option', { name:'Docs', exact:true }).click()
  await drawer.locator('.el-form-item').filter({ has:page.getByText('工具', { exact:true }) }).locator('.el-select').click()
  await page.getByRole('option', { name:'echo', exact:true }).click()
  await expect(drawer.locator('pre').first()).toContainText('text')
  await drawer.getByText('MCP 工具 配置', { exact:true }).click()
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await page.getByRole('button', { name:'保存', exact:true }).click()
  await expect(page.locator('.editor__dirty')).toHaveCount(0)
  const config = updates[0].flow.nodes.find((node:any) => node.type === 'mcp_tool').config
  expect(config.serverId).toBe('1')
  expect(config.toolName).toBe('echo')
})
