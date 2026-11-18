<template>
  <el-drawer
    :model-value="modelValue"
    direction="rtl"
    size="560px"
    title="触发器"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="triggers">
      <div class="triggers__intro">
        <span>触发器优先运行<strong>已发布</strong>版本；未发布时运行当前草稿。</span>
        <el-button type="primary" size="small" @click="openCreate">新建触发器</el-button>
      </div>

      <div v-loading="loading" class="triggers__list">
        <div v-for="item in triggers" :key="item.id" class="triggers__item">
          <div class="triggers__row">
            <div class="triggers__title">
              <span class="triggers__name">{{ item.name }}</span>
              <el-tag size="small" :type="item.type === 'CRON' ? 'warning' : 'success'">
                {{ item.type === 'CRON' ? '定时' : 'Webhook' }}
              </el-tag>
              <el-tag v-if="item.lastStatus" size="small" :type="statusType(item.lastStatus)">
                {{ item.lastStatus }}
              </el-tag>
            </div>
            <el-switch :model-value="item.enabled" @change="toggle(item, $event)" />
          </div>

          <div v-if="item.type === 'CRON'" class="triggers__desc mono">
            {{ item.cronExpression }} · {{ item.timezone }}
            <span v-if="item.nextRunAt"> · 下次 {{ formatTime(item.nextRunAt) }}</span>
          </div>

          <div v-else class="triggers__webhook">
            <el-input :model-value="webhookUrl(item)" readonly size="small" />
            <el-button size="small" @click="copy(item)">复制</el-button>
            <el-button size="small" @click="rotate(item)">重置令牌</el-button>
          </div>

          <div class="triggers__meta">
            <span class="mono">input {{ JSON.stringify(item.input || {}) }}</span>
            <span v-if="item.lastRunAt">最近运行 {{ formatTime(item.lastRunAt) }}</span>
          </div>

          <div class="triggers__actions">
            <el-button link type="primary" size="small" @click="run(item)">立即运行</el-button>
            <el-button link size="small" @click="openEdit(item)">编辑</el-button>
            <el-button link type="danger" size="small" @click="remove(item)">删除</el-button>
          </div>
        </div>
        <div v-if="!triggers.length && !loading" class="triggers__empty">还没有触发器</div>
      </div>
    </div>

    <el-dialog
      v-model="dialogOpen"
      :title="editingId ? '编辑触发器' : '新建触发器'"
      width="520px"
      append-to-body
    >
      <el-form label-position="top" size="small">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="例如：每天 9 点生成日报" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="form.type">
            <el-radio-button value="CRON">定时</el-radio-button>
            <el-radio-button value="WEBHOOK">Webhook</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="form.type === 'CRON'">
          <el-form-item label="CRON 表达式">
            <el-input v-model="form.cronExpression" placeholder="0 9 * * *（每天 9:00）" />
            <div class="triggers__presets">
              <el-button
                v-for="preset in presets"
                :key="preset.value"
                link
                size="small"
                @click="form.cronExpression = preset.value"
              >{{ preset.label }}</el-button>
            </div>
            <div class="triggers__help">支持 5 段（分 时 日 月 周）或 6 段（秒 分 时 日 月 周）</div>
          </el-form-item>
          <el-form-item label="时区">
            <el-input v-model="form.timezone" placeholder="Asia/Shanghai" />
          </el-form-item>
        </template>
        <div v-else class="triggers__help triggers__help--block">
          保存后会生成专属 Webhook 地址，外部系统 POST JSON 即可触发，无需账号或 API Key。
        </div>

        <el-form-item label="静态输入（JSON 对象）">
          <el-input
            v-model="form.inputText"
            type="textarea"
            :rows="5"
            placeholder='{"topic": "每日简报"}'
          />
          <div class="triggers__help">会作为工作流 input；Webhook 请求体中的同名字段优先</div>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { triggerApi } from '../api'
import type { WorkflowTrigger } from '../types'

const props = defineProps<{ modelValue: boolean; workflowId: number }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const triggers = ref<WorkflowTrigger[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogOpen = ref(false)
const editingId = ref<number | null>(null)

const presets = [
  { label: '每小时', value: '0 * * * *' },
  { label: '每天 9 点', value: '0 9 * * *' },
  { label: '每周一 9 点', value: '0 9 * * 1' },
  { label: '每月 1 号 9 点', value: '0 9 1 * *' }
]

const form = reactive({
  name: '',
  type: 'CRON' as 'CRON' | 'WEBHOOK',
  cronExpression: '0 9 * * *',
  timezone: 'Asia/Shanghai',
  inputText: '{}',
  enabled: true
})

watch(
  () => props.modelValue,
  (open) => {
    if (open) load()
  }
)

async function load() {
  loading.value = true
  try {
    triggers.value = await triggerApi.list(props.workflowId)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.name = ''
  form.type = 'CRON'
  form.cronExpression = '0 9 * * *'
  form.timezone = 'Asia/Shanghai'
  form.inputText = '{}'
  form.enabled = true
  dialogOpen.value = true
}

function openEdit(item: WorkflowTrigger) {
  editingId.value = item.id
  form.name = item.name
  form.type = item.type
  form.cronExpression = item.cronExpression || '0 9 * * *'
  form.timezone = item.timezone || 'Asia/Shanghai'
  form.inputText = JSON.stringify(item.input || {}, null, 2)
  form.enabled = item.enabled
  dialogOpen.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  let input: Record<string, any>
  try {
    const parsed = JSON.parse(form.inputText || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('not object')
    }
    input = parsed
  } catch {
    ElMessage.warning('静态输入必须是 JSON 对象')
    return
  }
  if (form.type === 'CRON' && !form.cronExpression.trim()) {
    ElMessage.warning('请填写 CRON 表达式')
    return
  }

  const payload = {
    name: form.name.trim(),
    type: form.type,
    cronExpression: form.type === 'CRON' ? form.cronExpression.trim() : null,
    timezone: form.timezone.trim() || 'Asia/Shanghai',
    input,
    enabled: form.enabled
  }
  saving.value = true
  try {
    if (editingId.value) {
      await triggerApi.update(editingId.value, payload)
    } else {
      await triggerApi.create(props.workflowId, payload)
    }
    ElMessage.success('已保存')
    dialogOpen.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function toggle(item: WorkflowTrigger, enabled: any) {
  try {
    await triggerApi.update(item.id, {
      name: item.name,
      type: item.type,
      cronExpression: item.type === 'CRON' ? item.cronExpression : null,
      timezone: item.timezone || 'Asia/Shanghai',
      input: item.input || {},
      enabled: Boolean(enabled)
    })
    await load()
  } catch {
    await load()
  }
}

async function run(item: WorkflowTrigger) {
  await triggerApi.run(item.id)
  ElMessage.success('已提交执行，可在执行记录中查看')
  await load()
}

async function remove(item: WorkflowTrigger) {
  try {
    await ElMessageBox.confirm('确定删除触发器「' + item.name + '」？', '删除触发器', { type: 'warning' })
  } catch {
    return
  }
  await triggerApi.remove(item.id)
  ElMessage.success('已删除')
  await load()
}

async function rotate(item: WorkflowTrigger) {
  try {
    await ElMessageBox.confirm('重置后旧 Webhook 地址立即失效，确定继续？', '重置令牌', { type: 'warning' })
  } catch {
    return
  }
  await triggerApi.rotate(item.id)
  ElMessage.success('已重置')
  await load()
}

function webhookUrl(item: WorkflowTrigger) {
  return item.webhookPath ? location.origin + item.webhookPath : ''
}

async function copy(item: WorkflowTrigger) {
  const url = webhookUrl(item)
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('已复制 Webhook 地址')
  } catch {
    ElMessage.warning('复制失败，请手动选择地址复制')
  }
}

function statusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'SUCCESS') return 'success'
  if (status === 'RUNNING') return 'warning'
  if (status === 'FAILED') return 'danger'
  return 'info'
}

function formatTime(value?: string) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.triggers {
  padding: 0 4px;
}

.triggers__intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  font-size: 12px;
  color: #8b93a7;
}

.triggers__item {
  padding: 12px 14px;
  margin-bottom: 10px;
  border: 1px solid #262a36;
  border-radius: 10px;
  background: #141821;
}

.triggers__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.triggers__title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.triggers__name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.triggers__desc {
  margin-top: 8px;
  font-size: 11px;
  color: #8b93a7;
}

.triggers__webhook {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.triggers__meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 8px;
  font-size: 11px;
  color: #6b7387;
}

.triggers__actions {
  margin-top: 6px;
  display: flex;
  justify-content: flex-end;
}

.triggers__empty {
  padding: 40px 0;
  text-align: center;
  font-size: 12px;
  color: #6b7387;
}

.triggers__presets {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.triggers__help {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.5;
  color: #6b7387;
}

.triggers__help--block {
  margin-bottom: 14px;
}
</style>
