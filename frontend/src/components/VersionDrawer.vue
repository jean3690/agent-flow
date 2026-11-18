<template>
  <el-drawer
    :model-value="modelValue"
    direction="rtl"
    size="560px"
    title="版本历史"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="versions">
      <div class="versions__intro">
        <div>
          <div class="versions__line">当前 v{{ currentVersion }}</div>
          <div class="versions__line af-muted">
            {{ publishedVersion ? '线上 v' + publishedVersion : '尚未发布' }}
          </div>
        </div>
        <div class="versions__actions">
          <el-button v-if="publishedVersion" size="small" @click="unpublish">取消发布</el-button>
          <el-button size="small" type="primary" @click="publish">发布 v{{ currentVersion }}</el-button>
        </div>
      </div>

      <div v-loading="loading" class="versions__list">
        <div v-for="item in versions" :key="item.id" class="versions__item">
          <div class="versions__row">
            <div class="versions__title">
              <span class="versions__version mono">v{{ item.version }}</span>
              <el-tag v-if="item.current" size="small" type="primary">当前</el-tag>
              <el-tag v-if="item.published" size="small" type="success">已发布</el-tag>
            </div>
            <span class="versions__time">{{ formatTime(item.createdAt) }}</span>
          </div>
          <div class="versions__note">{{ item.note || '手动保存' }}</div>
          <div class="versions__foot">
            <span class="af-muted">{{ item.name }}</span>
            <div>
              <el-button link type="primary" size="small" @click="inspect(item)">查看</el-button>
              <el-button
                v-if="!item.current"
                link
                size="small"
                @click="rollback(item)"
              >回滚</el-button>
            </div>
          </div>
        </div>
        <div v-if="!versions.length && !loading" class="versions__empty">还没有版本记录</div>
      </div>
    </div>

    <el-dialog v-model="inspectVisible" :title="'版本 v' + (inspectItem?.version || '')" width="720px" append-to-body>
      <div v-if="inspectItem" class="versions__inspect">
        <div class="af-muted versions__inspect-meta">
          {{ inspectItem.note || '手动保存' }} · {{ formatTime(inspectItem.createdAt) }}
        </div>
        <pre class="mono">{{ JSON.stringify(inspectItem.flow || {}, null, 2) }}</pre>
      </div>
      <template #footer>
        <el-button @click="inspectVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { workflowApi } from '../api'
import type { WorkflowVersion } from '../types'

const props = defineProps<{
  modelValue: boolean
  workflowId: number
  currentVersion: number
  publishedVersion?: number
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'changed'): void
}>()

const versions = ref<WorkflowVersion[]>([])
const loading = ref(false)
const inspectVisible = ref(false)
const inspectItem = ref<WorkflowVersion | null>(null)

watch(
  () => props.modelValue,
  (open) => {
    if (open) load()
  }
)

async function load() {
  loading.value = true
  try {
    versions.value = await workflowApi.versions(props.workflowId)
  } finally {
    loading.value = false
  }
}

async function inspect(item: WorkflowVersion) {
  inspectItem.value = await workflowApi.versionDetail(props.workflowId, item.version)
  inspectVisible.value = true
}

async function rollback(item: WorkflowVersion) {
  try {
    await ElMessageBox.confirm(
      '回滚会把 v' + item.version + ' 的内容复制为新的当前版本，历史版本不会丢失。确定继续？',
      '回滚版本',
      { type: 'warning' }
    )
  } catch {
    return
  }
  await workflowApi.rollback(props.workflowId, item.version)
  ElMessage.success('已回滚到 v' + item.version)
  emit('changed')
  await load()
}

async function publish() {
  try {
    await ElMessageBox.confirm(
      '发布后 Cron / Webhook 触发器将固定执行 v' + props.currentVersion + '，确定发布？',
      '发布版本',
      { type: 'warning' }
    )
  } catch {
    return
  }
  await workflowApi.publish(props.workflowId)
  ElMessage.success('已发布 v' + props.currentVersion)
  emit('changed')
  await load()
}

async function unpublish() {
  try {
    await ElMessageBox.confirm('取消发布后触发器将回退到执行当前草稿，确定继续？', '取消发布', {
      type: 'warning'
    })
  } catch {
    return
  }
  await workflowApi.unpublish(props.workflowId)
  ElMessage.success('已取消发布')
  emit('changed')
  await load()
}

function formatTime(value?: string) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.versions {
  padding: 0 4px;
}

.versions__intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  margin-bottom: 14px;
  border: 1px solid #262a36;
  border-radius: 10px;
  background: #141821;
}

.versions__line {
  font-size: 12px;
  line-height: 1.8;
}

.versions__actions {
  display: flex;
  gap: 8px;
}

.versions__item {
  padding: 12px 14px;
  margin-bottom: 10px;
  border: 1px solid #262a36;
  border-radius: 10px;
  background: #141821;
}

.versions__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.versions__title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.versions__version {
  font-size: 13px;
  font-weight: 600;
}

.versions__time {
  font-size: 11px;
  color: #6b7387;
}

.versions__note {
  margin-top: 6px;
  font-size: 12px;
  color: #c7ccd8;
}

.versions__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 11px;
}

.versions__empty {
  padding: 40px 0;
  text-align: center;
  font-size: 12px;
  color: #6b7387;
}

.versions__inspect {
  max-height: 62vh;
  overflow: auto;
}

.versions__inspect-meta {
  margin-bottom: 8px;
  font-size: 12px;
}

.versions__inspect pre {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: #11141c;
  font-size: 11px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
