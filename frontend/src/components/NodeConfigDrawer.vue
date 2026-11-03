<template>
  <el-drawer
    :model-value="modelValue"
    direction="rtl"
    size="380px"
    :with-header="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="node && definition" class="config">
      <div class="config__head">
        <div>
          <div class="config__kind mono">{{ node.data.kind }}</div>
          <div class="config__title">{{ definition.name }} 配置</div>
        </div>
        <el-button link type="danger" @click="emit('remove')">删除节点</el-button>
      </div>

      <el-form label-position="top" size="small">
        <el-form-item label="节点名称">
          <el-input v-model="node.data.name" placeholder="节点显示名" />
        </el-form-item>

        <el-form-item v-for="field in definition.configSchema" :key="field.key" :label="field.label">
          <el-input
            v-if="field.type === 'input'"
            v-model="config[field.key]"
            :placeholder="field.placeholder"
          />

          <el-input
            v-else-if="field.type === 'textarea'"
            v-model="config[field.key]"
            type="textarea"
            :rows="field.rows || 4"
            :placeholder="field.placeholder"
          />

          <el-input-number
            v-else-if="field.type === 'number'"
            v-model="config[field.key]"
            :min="field.min"
            :max="field.max"
            :step="field.step || 1"
            controls-position="right"
            style="width: 100%"
          />

          <el-select
            v-else-if="field.type === 'knowledge'"
            v-model="config[field.key]"
            style="width: 100%"
            filterable
            placeholder="选择知识库"
          >
            <el-option v-for="kb in knowledgeBases" :key="kb.id" :label="kb.name" :value="String(kb.id)" />
          </el-select>

          <el-select
            v-else-if="field.type === 'select'"
            v-model="config[field.key]"
            style="width: 100%"
            filterable
          >
            <el-option v-for="option in field.options || []" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>

          <el-select
            v-else-if="field.type === 'multiselect'"
            v-model="config[field.key]"
            multiple
            style="width: 100%"
            placeholder="可多选"
          >
            <el-option v-for="option in field.options || []" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>

          <el-select
            v-else-if="field.type === 'tags'"
            v-model="config[field.key]"
            multiple
            filterable
            allow-create
            default-first-option
            style="width: 100%"
            :placeholder="field.placeholder || '输入后回车'"
          />

          <el-select
            v-else-if="field.type === 'node'"
            v-model="config[field.key]"
            style="width: 100%"
            clearable
            placeholder="选择目标节点"
          >
            <el-option
              v-for="item in otherNodes"
              :key="item.id"
              :label="item.data?.name || item.id"
              :value="item.id"
            />
          </el-select>

          <el-switch v-else-if="field.type === 'switch'" v-model="config[field.key]" />

          <div v-else-if="field.type === 'keyvalue'" class="kv">
            <div v-for="(row, index) in kvRows[field.key] || []" :key="index" class="kv__row">
              <el-input v-model="row.k" placeholder="key" @change="syncKv(field.key)" />
              <el-input v-model="row.v" placeholder="value" @change="syncKv(field.key)" />
              <el-button link type="danger" @click="removeRow(field.key, index)">×</el-button>
            </div>
            <el-button link type="primary" @click="addRow(field.key)">+ 添加一项</el-button>
          </div>

          <div v-if="field.help" class="config__help">{{ field.help }}</div>
        </el-form-item>

        <el-form-item v-if="config.variables || definition.type === 'input'" label="运行时输入">
          <div class="config__help">在调试面板填写 JSON，键名与模板里的变量对应。</div>
        </el-form-item>
      </el-form>

      <div v-if="liveTokens" class="config__tokens">
        <div class="config__tokens-title">本次运行输出（实时）</div>
        <pre class="mono">{{ liveTokens }}</pre>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRunStore } from '../stores/run'
import { knowledgeApi } from '../api'
import type { KnowledgeBase } from '../types'

const props = defineProps<{
  modelValue: boolean
  node: any
  definition: any
  nodes: any[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'remove'): void
}>()

const runStore = useRunStore()
const kvRows = reactive<Record<string, { k: string; v: string }[]>>({})
const knowledgeBases = ref<KnowledgeBase[]>([])

onMounted(async () => {
  try {
    knowledgeBases.value = await knowledgeApi.list()
  } catch {
    knowledgeBases.value = []
  }
})

const config = computed<Record<string, any>>(() => props.node?.data?.config || {})
const otherNodes = computed(() => (props.nodes || []).filter((item) => item.id !== props.node?.id))
const liveTokens = computed(() => (props.node ? runStore.tokens[props.node.id] : '') || '')

watch(
  () => props.node?.id,
  () => {
    Object.keys(kvRows).forEach((key) => delete kvRows[key])
    if (!props.node) return
    props.definition?.configSchema?.forEach((field: any) => {
      if (field.type === 'keyvalue') {
        const source = props.node.data.config[field.key] || {}
        kvRows[field.key] = Object.entries(source).map(([k, v]) => ({ k, v: String(v ?? '') }))
        if (!kvRows[field.key].length) kvRows[field.key] = [{ k: '', v: '' }]
      }
    })
  },
  { immediate: true }
)

function addRow(key: string) {
  kvRows[key] = kvRows[key] || []
  kvRows[key].push({ k: '', v: '' })
}

function removeRow(key: string, index: number) {
  kvRows[key]?.splice(index, 1)
  syncKv(key)
}

function syncKv(key: string) {
  const rows = kvRows[key] || []
  const result: Record<string, string> = {}
  rows.forEach((row) => {
    if (row.k) result[row.k] = row.v
  })
  config.value[key] = result
}
</script>

<style scoped>
.config {
  padding: 18px 18px 60px;
}

.config__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 18px;
}

.config__kind {
  font-size: 11px;
  color: #6b7387;
}

.config__title {
  margin-top: 2px;
  font-size: 15px;
  font-weight: 600;
}

.config__help {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.5;
  color: #6b7387;
}

.config__tokens {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid #262a36;
}

.config__tokens-title {
  font-size: 12px;
  color: #8b93a7;
  margin-bottom: 6px;
}

.config__tokens pre {
  max-height: 200px;
  overflow: auto;
  padding: 10px;
  border-radius: 8px;
  background: #11141c;
  font-size: 11px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.kv {
  width: 100%;
}

.kv__row {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}
</style>
