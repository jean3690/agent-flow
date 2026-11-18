// 生成 README / 简历材料用的界面截图。
//
// 前置：整栈已启动（./start.sh），并已灌入演示数据（python3 e2e/seed_demo.py）。
// 用法：cd frontend && node scripts/capture-docs.mjs
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const WEB = process.env.WEB_URL || 'http://localhost:5173'
const API = process.env.API_URL || 'http://127.0.0.1:8084'
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), '../../docs/images')

async function login() {
  const resp = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'admin123' })
  })
  const body = await resp.json()
  if (body.code !== 0) throw new Error(`login failed: ${JSON.stringify(body)}`)
  return body.data
}

async function main() {
  mkdirSync(OUT, { recursive: true })
  const { token, user } = await login()
  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: { width: 1600, height: 950 },
    deviceScaleFactor: 2,
    locale: 'zh-CN'
  })
  await context.addInitScript(([token, user]) => {
    localStorage.setItem('agentflow_token', token)
    localStorage.setItem('agentflow_user', JSON.stringify(user))
  }, [token, user])
  const page = await context.newPage()

  async function fitCanvas() {
    // 画布按定义里的坐标渲染，fit-view 让整条链路进入视野且保持可读
    await page.locator('.vue-flow__controls-fitview').click({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(800)
  }

  const shots = [
    { path: '/#/', file: '01-workflows.png', wait: '.workflow-card, .el-empty, .page' },
    { path: '/#/editor/1', file: '02-editor.png', wait: '.vue-flow__node', fit: true },
    { path: '/#/executions', file: '03-executions.png', wait: '.el-table__row, .el-empty' },
    { path: '/#/editor/2', file: '04-triage.png', wait: '.vue-flow__node', fit: true }
  ]

  for (const shot of shots) {
    await page.goto(WEB + shot.path, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1200)
    if (shot.wait) await page.locator(shot.wait).first().waitFor({ timeout: 15000 }).catch(() => {})
    if (shot.fit) await fitCanvas()
    await page.waitForTimeout(600)
    await page.screenshot({ path: `${OUT}/${shot.file}` })
    console.log('saved', shot.file)
  }

  // 执行详情：节点级输出与 token 汇总
  await page.goto(WEB + '/#/executions')
  await page.reload({ waitUntil: 'networkidle' })
  await page.locator('.el-table__row').first().waitFor({ timeout: 20000 })
  await page.getByText('详情', { exact: true }).first().click({ timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${OUT}/05-execution-detail.png` })
  console.log('saved 05-execution-detail.png')

  await browser.close()
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})