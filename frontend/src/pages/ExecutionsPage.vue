<template>
  <div class="executions">
    <header class="executions__bar">
      <div class="executions__brand">
        <el-button link @click="router.push('/')">← 工作流</el-button>
        <span class="executions__name">AgentFlow</span>
        <span class="executions__tag">执行记录</span>
      </div>
      <div class="executions__right">
        <span class="af-muted">{{ authStore.user?.nickname || authStore.user?.username }}</span>
        <el-button link @click="logout">退出</el-button>
      </div>
    </header>

    <main class="executions__main">
      <div class="executions__head">
        <div>
          <h1>执行记录</h1>
          <p class="af-muted">所有工作流的运行留痕，可查看节点输出或取消运行中的任务</p>
        </div>
        <div class="executions__filters">
          <el-select v-model="status" style="width: 140px" @change="reload">
            <el-option label="全部状态" value="" />
            <el-option label="运行中" value="RUNNING" />
            <el-option label="成功" value="SUCCESS" />
            <el-option label="失败" value="FAILED" />
            <el-option label="已取消" value="CANCELED" />
          </el-select>
          <el-button :loading="loading" @click="reload">刷新</el-button>
        </div>
      </div>

      <div class="af-card executions__table">
        <el-table :data="records" v-loading="loading" empty-text="还没有执行记录">
          <el-table-column label="工作流" min-width="160">
            <template #default="{ row }">
              <div class="executions__flow">{{ row.workflowName }}</div>
              <div class="executions__run mono">{{ row.runId }}</div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="nodeCount" label="节点" width="80" />
          <el-table-column label="耗时" width="100">
            <template #default="{ row }">{{ row.elapsedMs ? row.elapsedMs + ' ms' : '-' }}</template>
          </el-table-column>
          <el-table-column label="Token" width="100">
            <template #default="{ row }">{{ row.totalTokens ? row.totalTokens : '-' }}</template>
          </el-table-column>
          <el-table-column label="成本" width="100">
            <template #default="{ row }">{{ row.costUsd ? '$' + Number(row.costUsd).toFixed(6) : '-' }}</template>
          </el-table-column>
          <el-table-column label="开始时间" width="170">
            <template #default="{ row }">{{ formatDate(row.startedAt) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="200" align="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openDetail(row)">详情</el-button>
              <el-button
                v-if="row.status === 'RUNNING'"
                link
                type="danger"
                @click="cancel(row)"
              >取消</el-button>
              <el-button link type="danger" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="executions__pager">
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

    <el-dialog v-model="detailVisible" title="执行详情" width="760px">
      <div v-if="detail" class="executions__detail">
        <div class="executions__meta">
          <span class="mono">{{ detail.runId }}</span>
          <span>{{ detail.workflowName }}</span>
          <span v-if="detail.flowVersion" class="af-muted">版本 v{{ detail.flowVersion }}</span>
          <el-tag size="small" :type="statusType(detail.status)">{{ statusText(detail.status) }}</el-tag>
          <span class="af-muted">{{ detail.elapsedMs }} ms</span>
          <span v-if="detail.totalTokens" class="af-muted">
            {{ detail.totalTokens }} tokens · ${{ Number(detail.costUsd || 0).toFixed(6) }}
          </span>
        </div>
        <div v-if="detail.resumeRunId" class="af-muted">
          续跑来源：<span class="mono">{{ detail.resumeRunId }}</span>
        </div>
        <div v-if="detail.errorMessage" class="executions__error">{{ detail.errorMessage }}</div>

        <div class="executions__label">输入</div>
        <OutputPreview :value="detail.input" class="executions__preview" />

        <div class="executions__label">节点输出</div>
        <div v-for="node in detail.nodes" :key="node.nodeId" class="executions__node">
          <div class="executions__node-head">
            <span>{{ node.nodeName }} ({{ node.nodeType }})</span>
            <el-tag size="small" :type="statusType(node.status)">{{ statusText(node.status) }}</el-tag>
            <el-tag v-if="node.cacheHit" size="small" type="info">复用历史输出</el-tag>
            <span class="af-muted">{{ node.elapsedMs }} ms</span>
          </div>
          <div v-if="node.errorMessage" class="executions__error">{{ node.errorMessage }}</div>
          <OutputPreview v-else-if="node.output" :value="node.output" class="executions__preview" />
        </div>

        <div class="executions__label">最终输出</div>
        <OutputPreview :value="detail.output" class="executions__preview" />
      </div>
      <template #footer>
        <el-button
          v-if="detail && (detail.status === 'FAILED' || detail.status === 'CANCELED')"
          type="warning"
          @click="goResume"
        >去编辑器续跑</el-button>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { executionApi } from '../api'
import { useAuthStore } from '../stores/auth'
import OutputPreview from '../components/OutputPreview.vue'
import type { ExecutionDetail, ExecutionSummary } from '../types'

const router = useRouter()
const authStore = useAuthStore()

const records = ref<ExecutionSummary[]>([])
const loading = ref(false)
const status = ref('')
const page = ref(1)
const size = 10
const total = ref(0)

const detailVisible = ref(false)
const detail = ref<ExecutionDetail | null>(null)
let timer: number | null = null

async function load() {
  loading.value = true
  try {
    const result = await executionApi.page(page.value, size, {
      status: status.value || undefined
    })
    records.value = result.records
    total.value = result.total
    scheduleRefresh()
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function scheduleRefresh() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  if (records.value.some((item) => item.status === 'RUNNING')) {
    timer = window.setInterval(load, 4000)
  }
}

async function openDetail(row: ExecutionSummary) {
  detail.value = await executionApi.detail(row.runId)
  detailVisible.value = true
}

async function cancel(row: ExecutionSummary) {
  await ElMessageBox.confirm('取消后该次执行会立即停止，确定继续？', '取消执行', { type: 'warning' })
  await executionApi.cancel(row.runId)
  ElMessage.success('已发送取消请求')
  await load()
}

async function remove(row: ExecutionSummary) {
  await ElMessageBox.confirm('删除该条执行记录及其节点日志？', '确认', { type: 'warning' })
  await executionApi.remove(row.runId)
  if (detail.value?.runId === row.runId) {
    detailVisible.value = false
    detail.value = null
  }
  ElMessage.success('已删除')
  await load()
}

function goResume() {
  if (!detail.value) return
  detailVisible.value = false
  router.push('/editor/' + detail.value.workflowId + '?resume=' + detail.value.runId)
}

function statusType(value: string) {
  if (value === 'SUCCESS') return 'success'
  if (value === 'FAILED') return 'danger'
  if (value === 'RUNNING') return 'warning'
  return 'info'
}

function statusText(value: string) {
  if (value === 'SUCCESS') return '成功'
  if (value === 'FAILED') return '失败'
  if (value === 'RUNNING') return '运行中'
  if (value === 'CANCELED') return '已取消'
  return value
}

function formatDate(value?: string) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function logout() {
  authStore.logout()
  router.replace('/login')
}

onMounted(load)
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.executions {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.executions__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  height: 54px;
  border-bottom: 1px solid #262a36;
  background: #10131a;
}

.executions__brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.executions__name {
  font-weight: 600;
  font-size: 13px;
}

.executions__tag {
  font-size: 11px;
  color: #6b7387;
  padding-left: 10px;
  border-left: 1px solid #262a36;
}

.executions__right {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.executions__main {
  flex: 1;
  overflow: auto;
  padding: 32px clamp(24px, 6vw, 84px);
}

.executions__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}

.executions__head h1 {
  margin: 0;
  font-size: 26px;
}

.executions__head p {
  margin: 6px 0 0;
  font-size: 13px;
}

.executions__filters {
  display: flex;
  gap: 10px;
}

.executions__table {
  padding: 8px 16px 12px;
}

.executions__flow {
  font-weight: 600;
}

.executions__run {
  margin-top: 2px;
  font-size: 11px;
  color: #6b7387;
}

.executions__pager {
  padding-top: 10px;
  display: flex;
  justify-content: flex-end;
}

.executions__detail {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 62vh;
  overflow: auto;
}

.executions__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: #8b93a7;
}

.executions__label {
  margin-top: 6px;
  font-size: 11px;
  color: #6b7387;
}

.executions__node {
  padding: 8px 0;
  border-top: 1px solid #232833;
}

.executions__node-head {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  font-weight: 600;
}

.executions__preview {
  margin-top: 6px;
  max-height: 200px;
  overflow: auto;
}

.executions__error {
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(239, 68, 68, 0.12);
  color: #f87171;
  font-size: 12px;
}
</style>
