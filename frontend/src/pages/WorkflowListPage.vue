<template>
  <div class="list-page">
    <header class="list-page__bar">
      <div class="list-page__brand">
        <span class="list-page__logo">AF</span>
        <span class="list-page__name">AgentFlow</span>
        <span class="list-page__tag">工作流</span>
      </div>
      <div class="list-page__right">
        <span class="af-muted">{{ authStore.user?.nickname || authStore.user?.username }}</span>
        <el-button link @click="logout">退出</el-button>
      </div>
    </header>

    <main class="list-page__main">
      <div class="list-page__head">
        <div>
          <h1>工作流</h1>
          <p class="af-muted">编排、运行、查看执行记录</p>
        </div>
        <div class="list-page__tools">
          <el-input v-model="keyword" placeholder="搜索名称" clearable style="width: 220px" @change="load" />
          <el-button @click="router.push('/knowledge')">知识库</el-button>
          <el-button @click="router.push('/executions')">执行记录</el-button>
          <el-button @click="router.push('/providers')">模型配置</el-button>
          <el-button @click="importInput?.click()">导入</el-button>
          <input ref="importInput" type="file" accept=".json,application/json" style="display: none" @change="onImportFile" />
          <el-button type="primary" @click="openCreate">新建工作流</el-button>
        </div>
      </div>

      <div class="af-card list-page__table">
        <el-table :data="records" v-loading="loading" style="width: 100%" empty-text="还没有工作流">
          <el-table-column prop="name" label="名称" min-width="200">
            <template #default="{ row }">
              <a class="list-page__link" @click="openEditor(row.id)">{{ row.name }}</a>
              <div class="list-page__desc">{{ row.description || '未填写描述' }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="nodeCount" label="节点" width="80" />
          <el-table-column prop="version" label="版本" width="80">
            <template #default="{ row }">v{{ row.version }}</template>
          </el-table-column>
          <el-table-column label="更新时间" width="180">
            <template #default="{ row }">{{ formatDate(row.updatedAt) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="250" align="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEditor(row.id)">编辑</el-button>
              <el-button link @click="exportWorkflow(row)">导出</el-button>
              <el-button link @click="duplicate(row)">复制</el-button>
              <el-button link type="danger" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="list-page__pager">
          <el-pagination
            v-model:current-page="page"
            :page-size="size"
            :total="total"
            layout="prev, pager, next"
            @current-change="load"
          />
        </div>
      </div>
    </main>

    <el-dialog v-model="createVisible" title="新建工作流" width="440px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="例如：文章摘要流水线" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="这条工作流解决什么问题" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="create">创建并编辑</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { workflowApi } from '../api'
import { useAuthStore } from '../stores/auth'
import type { WorkflowSummary } from '../types'

const router = useRouter()
const authStore = useAuthStore()

const records = ref<WorkflowSummary[]>([])
const loading = ref(false)
const keyword = ref('')
const page = ref(1)
const size = 10
const total = ref(0)

const createVisible = ref(false)
const creating = ref(false)
const form = reactive({ name: '', description: '' })

async function load() {
  loading.value = true
  try {
    const result = await workflowApi.page(page.value, size, keyword.value)
    records.value = result.records
    total.value = result.total
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.name = ''
  form.description = ''
  createVisible.value = true
}

async function create() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  creating.value = true
  try {
    const detail = await workflowApi.create({
      name: form.name,
      description: form.description,
      engineType: 'langgraph',
      status: 1,
      flow: { nodes: [], edges: [] }
    })
    createVisible.value = false
    router.push('/editor/' + detail.id)
  } finally {
    creating.value = false
  }
}

const importInput = ref<HTMLInputElement | null>(null)

async function onImportFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  let parsed: any
  try {
    parsed = JSON.parse(await file.text())
  } catch {
    ElMessage.error('不是合法的 JSON 文件')
    return
  }
  if (!parsed?.name || !Array.isArray(parsed?.flow?.nodes)) {
    ElMessage.error('文件缺少 name 或 flow.nodes')
    return
  }
  const detail = await workflowApi.create({
    name: String(parsed.name),
    description: parsed.description || '',
    engineType: parsed.engineType || 'langgraph',
    status: 1,
    flow: parsed.flow
  })
  ElMessage.success('导入成功')
  router.push('/editor/' + detail.id)
}

async function exportWorkflow(row: WorkflowSummary) {
  const detail = await workflowApi.detail(row.id)
  const payload = {
    name: detail.name,
    description: detail.description,
    engineType: detail.engineType,
    flow: detail.flow
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = (detail.name || 'workflow') + '.json'
  link.click()
  URL.revokeObjectURL(url)
}

function openEditor(id: number) {
  router.push('/editor/' + id)
}

async function duplicate(row: WorkflowSummary) {
  const detail = await workflowApi.duplicate(row.id)
  ElMessage.success('已复制')
  await load()
  openEditor(detail.id)
}

async function remove(row: WorkflowSummary) {
  await ElMessageBox.confirm('删除后不可恢复，确认删除「' + row.name + '」？', '删除工作流', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消'
  })
  await workflowApi.remove(row.id)
  ElMessage.success('已删除')
  await load()
}

function logout() {
  authStore.logout()
  router.replace('/login')
}

function formatDate(value: string) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}

onMounted(async () => {
  await Promise.all([load(), authStore.loadUser().catch(() => null)])
})
</script>

<style scoped>
.list-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.list-page__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  height: 54px;
  border-bottom: 1px solid #262a36;
  background: #10131a;
}

.list-page__brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.list-page__logo {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: #6366f1;
  font-size: 11px;
  color: #fff;
}

.list-page__name {
  font-weight: 600;
  font-size: 13px;
}

.list-page__tag {
  font-size: 11px;
  color: #6b7387;
  padding-left: 10px;
  border-left: 1px solid #262a36;
}

.list-page__right {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.list-page__main {
  flex: 1;
  overflow: auto;
  padding: 32px clamp(24px, 6vw, 84px);
}

.list-page__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 20px;
}

.list-page__head h1 {
  margin: 0;
  font-size: 26px;
  letter-spacing: -0.01em;
}

.list-page__head p {
  margin: 6px 0 0;
  font-size: 13px;
}

.list-page__tools {
  display: flex;
  gap: 10px;
}

.list-page__table {
  padding: 8px 16px 12px;
}

.list-page__link {
  font-weight: 600;
  cursor: pointer;
}

.list-page__desc {
  margin-top: 2px;
  font-size: 12px;
  color: #6b7387;
}

.list-page__pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 12px;
}

:deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: transparent;
  --el-table-border-color: #232833;
  --el-table-row-hover-bg-color: #1a1e29;
}
</style>
