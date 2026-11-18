<template>
  <IntegrationShell title="人工审批" description="工作流运行到「人工审批」节点时会在这里生成待办。通过后流程继续，驳回后按节点配置失败或继续。">
    <template #actions>
      <div>
        <el-select v-model="status" style="width:150px" @change="load">
          <el-option label="待处理" value="PENDING" />
          <el-option label="全部" value="" />
          <el-option label="已通过" value="APPROVED" />
          <el-option label="已驳回" value="REJECTED" />
          <el-option label="已过期" value="EXPIRED" />
        </el-select>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </template>
    <section class="integration__editor" v-loading="loading">
      <el-table :data="tasks" empty-text="没有待处理的审批。运行到人工审批节点后会自动出现在这里。" style="width:100%">
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column label="审批内容" min-width="260">
          <template #default="{ row }">
            <span class="approval__content">{{ row.content || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="runId" label="执行 ID" width="140" show-overflow-tooltip />
        <el-table-column label="到期时间" width="170">
          <template #default="{ row }">{{ formatTime(row.expiresAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button v-if="row.status === 'PENDING'" link type="primary" @click="open(row)">处理</el-button>
            <span v-else class="af-muted">{{ row.comment || '-' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialog" title="处理审批" width="640px">
      <template v-if="active">
        <h3 class="approval__title">{{ active.title }}</h3>
        <pre class="approval__body">{{ active.content || '（无审批内容）' }}</pre>
        <el-input v-model="comment" type="textarea" :rows="3" maxlength="1000" show-word-limit
                  placeholder="审批意见（驳回时必填）" />
      </template>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="danger" :loading="submitting" @click="submit(false)">驳回</el-button>
        <el-button type="primary" :loading="submitting" @click="submit(true)">通过</el-button>
      </template>
    </el-dialog>
  </IntegrationShell>
</template>
<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import IntegrationShell from '../components/IntegrationShell.vue'
import { approvalApi } from '../api'
import type { ApprovalTask } from '../types'

const tasks = ref<ApprovalTask[]>([])
const loading = ref(false)
const submitting = ref(false)
const status = ref('PENDING')
const dialog = ref(false)
const active = ref<ApprovalTask | null>(null)
const comment = ref('')
let timer: number | undefined

function statusLabel(value: string) {
  return { PENDING: '待处理', APPROVED: '已通过', REJECTED: '已驳回', EXPIRED: '已过期' }[value] || value
}
function statusType(value: string) {
  return value === 'PENDING' ? 'warning' : value === 'APPROVED' ? 'success' : value === 'REJECTED' ? 'danger' : 'info'
}
function formatTime(value?: string) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 19)
}
async function load() {
  loading.value = true
  try {
    tasks.value = await approvalApi.list(status.value)
  } finally {
    loading.value = false
  }
}
function open(task: ApprovalTask) {
  active.value = task
  comment.value = ''
  dialog.value = true
}
async function submit(approved: boolean) {
  if (!active.value) return
  if (!approved && !comment.value.trim()) {
    ElMessage.warning('请填写驳回原因')
    return
  }
  submitting.value = true
  try {
    await approvalApi.decide(active.value.id, approved, comment.value.trim())
    ElMessage.success(approved ? '已通过，流程将继续' : '已驳回')
    dialog.value = false
    await load()
  } finally {
    submitting.value = false
  }
}
onMounted(async () => {
  await load()
  timer = window.setInterval(load, 15000)
})
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>
<style scoped>
.approval__content { display: inline-block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: middle; }
.approval__title { margin: 0 0 12px; font-size: 16px; }
.approval__body { margin: 0 0 16px; padding: 12px; max-height: 45vh; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: #0f1219; border: 1px solid #262a36; border-radius: 6px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; line-height: 1.7; }
</style>
