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

        <el-form-item v-for="field in schema" :key="field.key" :label="field.label">
          <el-input
            v-if="field.type === 'input'"
            v-model="config[field.key]"
            :placeholder="field.placeholder"
            @focus="onFieldFocus(field.key, $event)"
          />

          <el-input
            v-else-if="field.type === 'textarea'"
            v-model="config[field.key]"
            type="textarea"
            :rows="field.rows || 4"
            :placeholder="field.placeholder"
            @focus="onFieldFocus(field.key, $event)"
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

          <template v-else-if="field.type === 'select'">
            <el-select
              v-model="config[field.key]"
              style="width: 100%"
              filterable
              :loading="field.dynamic === 'providerModels' && modelLoading"
            >
              <el-option v-for="option in optionsFor(field)" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
            <div v-if="field.dynamic === 'providerModels'" class="config__model-state">
              <span>{{ modelResult?.ok ? '实时模型' : '内置清单' }}</span>
              <el-button link type="primary" size="small" :loading="modelLoading" @click="refreshModels">刷新</el-button>
            </div>
            <div v-if="field.dynamic === 'providerModels' && modelResult?.message" class="config__help">
              {{ modelResult.message }}
            </div>
          </template>

          <el-select
            v-else-if="field.type === 'multiselect'"
            v-model="config[field.key]"
            multiple
            style="width: 100%"
            filterable
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

          <el-select
            v-else-if="field.type === 'nodes'"
            v-model="config[field.key]"
            multiple
            filterable
            clearable
            style="width: 100%"
            placeholder="留空自动取直接上游"
          >
            <el-option
              v-for="item in otherNodes"
              :key="item.id"
              :label="item.data?.name || item.id"
              :value="item.id"
            />
          </el-select>

          <el-select
            v-else-if="field.type === 'workflow'"
            v-model="config[field.key]"
            style="width: 100%"
            filterable
            clearable
            placeholder="选择已保存的工作流"
          >
            <el-option
              v-for="item in workflows"
              :key="item.id"
              :label="item.name"
              :value="String(item.id)"
            />
          </el-select>

          <el-select v-else-if="field.type === 'skills'" v-model="config[field.key]" multiple filterable style="width:100%" placeholder="选择已配置技能">
            <el-option v-for="item in skillList" :key="item.name" :label="item.title" :value="item.name" />
          </el-select>
          <el-select v-else-if="field.type === 'mcpServer' || field.type === 'mcpServers'" v-model="config[field.key]" :multiple="field.type === 'mcpServers'" filterable style="width:100%" placeholder="先在 MCP 页面配置服务">
            <el-option v-for="item in mcpServers.filter(s => s.enabled)" :key="item.id" :label="item.name" :value="String(item.id)" />
          </el-select>
          <template v-else-if="field.type === 'mcpTool'">
            <el-select v-model="config[field.key]" :loading="mcpLoading" filterable style="width:100%" placeholder="选择已授权工具">
              <el-option v-for="item in mcpTools" :key="item.name" :label="item.name" :value="item.name" />
            </el-select>
            <pre v-if="selectedMcpTool" class="config__help mono" style="white-space:pre-wrap">{{ JSON.stringify(selectedMcpTool.inputSchema, null, 2) }}</pre>
          </template>
          <el-switch v-else-if="field.type === 'switch'" v-model="config[field.key]" />

          <FilePicker
            v-else-if="field.type === 'file'"
            v-model="config[field.key]"
            :placeholder="field.placeholder"
          />

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

        <template v-if="definition.type !== 'input' && definition.type !== 'output'">
          <div class="config__section">执行选项（容错）</div>
          <el-form-item label="失败重试次数">
            <el-input-number v-model="config.retry" :min="0" :max="5" :step="1" controls-position="right" style="width: 100%" />
            <div class="config__help">首次执行失败后最多再重试几次（0-5）</div>
          </el-form-item>
          <el-form-item label="重试间隔（毫秒）">
            <el-input-number v-model="config.retryDelayMs" :min="0" :max="30000" :step="100" controls-position="right" style="width: 100%" />
          </el-form-item>
          <el-form-item label="节点超时（毫秒）">
            <el-input-number v-model="config.timeoutMs" :min="0" :max="3600000" :step="1000" controls-position="right" style="width: 100%" />
            <div class="config__help">0 表示不限；超时会计入失败并触发重试</div>
          </el-form-item>
          <el-form-item label="失败后">
            <el-select v-model="config.onError" style="width: 100%">
              <el-option label="终止工作流（默认）" value="fail" />
              <el-option label="继续执行下游（输出 failed=true）" value="continue" />
            </el-select>
          </el-form-item>
        </template>

        <el-form-item v-if="config.variables || definition.type === 'input'" label="运行时输入">
          <div class="config__help">在调试面板填写 JSON，键名与模板里的变量对应。</div>
        </el-form-item>

        <div v-if="declaredOutputFields.length" class="config__section">输出字段（别名 / 隐藏）</div>
        <el-collapse v-if="declaredOutputFields.length" class="config__collapse">
          <el-collapse-item title="配置本节点输出字段" name="outputs">
            <div class="config__help">别名会作为额外字段加到输出里；隐藏只影响此处的引用列表，不会删除运行时字段。</div>
            <div v-for="field in declaredOutputFields" :key="field.key" class="config__out-row">
              <span class="mono config__out-key">{{ field.key }}</span>
              <el-input
                :model-value="outputOverride(field.key).alias"
                size="small"
                placeholder="别名（可选）"
                @update:model-value="setOutputOverride(field.key, { alias: $event })"
              />
              <el-switch
                :model-value="outputOverride(field.key).hidden"
                size="small"
                @update:model-value="setOutputOverride(field.key, { hidden: $event })"
              />
            </div>
          </el-collapse-item>
        </el-collapse>
      </el-form>

      <div class="config__section">直接上游 / 可引用变量</div>
      <div v-if="!upstreamRefs.length" class="config__help">连接上游节点后，可在提示词里点击插入其输出字段。</div>
      <div v-for="item in upstreamRefs" :key="item.id" class="config__upstream">
        <div class="config__upstream-head">
          <span class="mono">{{ item.id }}</span>
          <span>{{ item.name }}</span>
        </div>
        <div class="config__chips">
          <el-tooltip v-for="field in item.fields" :key="field.refKey" :content="field.safe" placement="top">
            <el-tag size="small" class="config__chip" @click="insertRef(field.safe)">{{ field.refKey }}</el-tag>
          </el-tooltip>
          <el-tag
            v-for="field in item.shortFields"
            :key="field.refKey + '-short'"
            size="small"
            type="info"
            class="config__chip"
            @click="insertRef(field.short)"
          >
            {{ field.refKey }} 短引用
          </el-tag>
        </div>
        <div v-if="item.hasValueKey" class="config__help">该节点输出含 value，已使用 outputs[...] 形式引用。</div>
      </div>

      <div class="config__section">本次运行输出</div>
      <el-tabs v-model="outputTab" size="small">
        <el-tab-pane label="结构化输出" name="structured">
          <div v-if="selfOutputKeys.length" class="config__chips">
            <el-tooltip v-for="key in selfOutputKeys" :key="key" :content="selfRef(key)" placement="top">
              <el-tag size="small" class="config__chip" @click="insertRef(selfRef(key))">{{ key }}</el-tag>
            </el-tooltip>
          </div>
          <OutputPreview v-if="nodeOutput != null" :value="nodeOutput" />
          <div v-else class="config__help">运行后在这里查看结构化输出。</div>
        </el-tab-pane>
        <el-tab-pane label="实时文本" name="tokens">
          <pre class="mono config__tokens-pre">{{ liveTokens || '暂无实时文本' }}</pre>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRunStore } from '../stores/run'
import { useWorkflowStore } from '../stores/workflow'
import { knowledgeApi, llmProviderApi, workflowApi } from '../api'
import type {
  ConfigField,
  ConfigOption,
  KnowledgeBase,
  NodeOutputFieldConfig,
  ProviderModelsResult,
  WorkflowSummary
} from '../types'
import {
  buildRef,
  hasValueKeyOf,
  outputMetaOf,
  outputFieldsOf,
  visibleSchema
} from '../utils/nodeSchema'
import FilePicker from './FilePicker.vue'
import { skillApi, mcpApi } from '../api'
import type { SkillSummary, McpServer, McpTool } from '../types'
import OutputPreview from './OutputPreview.vue'

const props = defineProps<{
  modelValue: boolean
  node: any
  definition: any
  nodes: any[]
  edges: any[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'remove'): void
}>()

const runStore = useRunStore()
const workflowStore = useWorkflowStore()
const kvRows = reactive<Record<string, { k: string; v: string }[]>>({})
const knowledgeBases = ref<KnowledgeBase[]>([])
const workflows = ref<WorkflowSummary[]>([])
const skillList = ref<SkillSummary[]>([])
const mcpServers = ref<McpServer[]>([])
const mcpTools = ref<McpTool[]>([])
const mcpLoading = ref(false)
let mcpRequest = 0
const selectedMcpTool = computed(() => mcpTools.value.find(item => item.name === config.value.toolName))

watch(() => props.modelValue, async (open) => {
  if (!open) return
  const results = await Promise.allSettled([skillApi.list(), mcpApi.list()])
  skillList.value = results[0].status === 'fulfilled' ? results[0].value : []
  mcpServers.value = results[1].status === 'fulfilled' ? results[1].value : []
})

watch(() => [props.node?.id, props.node?.data?.config?.serverId], async ([nodeId, serverId], previous) => {
  const request = ++mcpRequest
  mcpTools.value = []
  mcpLoading.value = false
  if (!serverId || props.node?.data?.kind !== 'mcp_tool') return
  if (previous && previous[0] === nodeId && previous[1] !== serverId) config.value.toolName = ''
  mcpLoading.value = true
  try {
    const tools = await mcpApi.tools(Number(serverId))
    if (request === mcpRequest) mcpTools.value = tools
  } catch {
    // Shared request handling shows the error; never retain stale tools.
  } finally {
    if (request === mcpRequest) mcpLoading.value = false
  }
})

onMounted(async () => {
  try {
    knowledgeBases.value = await knowledgeApi.list()
  } catch {
    knowledgeBases.value = []
  }
  try {
    workflows.value = (await workflowApi.page(1, 200)).records || []
  } catch {
    workflows.value = []
  }
})

const config = computed<Record<string, any>>(() => props.node?.data?.config || {})
const schema = computed<ConfigField[]>(() => visibleSchema(props.definition, config.value))
const otherNodes = computed(() => (props.nodes || []).filter((item) => item.id !== props.node?.id))
const liveTokens = computed(() => (props.node ? runStore.tokens[props.node.id] : '') || '')
const nodeOutput = computed(() => (props.node ? runStore.nodeOutputs[props.node.id] : null))
const outputTab = ref('structured')

const declaredOutputFields = computed(() => outputMetaOf(props.definition)?.fields || [])

const upstreamRefs = computed(() => {
  if (!props.node) return []
  const ids = new Set(
    (props.edges || [])
      .filter((edge: any) => edge.target === props.node.id)
      .map((edge: any) => edge.source)
  )
  return (props.nodes || [])
    .filter((item) => ids.has(item.id))
    .map((item) => {
      const def = workflowStore.definitionMap[item.data?.kind] || null
      const hasValue = hasValueKeyOf(def)
      const fields = outputFieldsOf(def, item.data?.config).map((field) => ({
        ...field,
        ...buildRef(item.id, field.refKey, hasValue)
      }))
      return {
        id: item.id,
        name: item.data?.name || item.id,
        hasValueKey: hasValue,
        fields,
        shortFields: fields
          .filter((field) => !!field.short)
          .map((field) => ({ refKey: field.refKey, short: field.short as string }))
      }
    })
})

// ---- 动态模型列表（只写本地 ref，绝不写 config，避免误触发 dirty / 历史快照）----
const modelOptions = ref<string[]>([])
const modelLoading = ref(false)
const modelResult = ref<ProviderModelsResult | null>(null)
const hasDynamicModelField = computed(() =>
  (props.definition?.configSchema || []).some((field: any) => field.dynamic === 'providerModels')
)
let requestSeq = 0

async function refreshModels() {
  if (!props.modelValue || !props.node || !hasDynamicModelField.value) return
  const provider = String(config.value.provider || 'openai').trim() || 'openai'
  const seq = ++requestSeq
  modelLoading.value = true
  try {
    const result = await llmProviderApi.models(provider)
    if (seq !== requestSeq) return
    modelResult.value = result
    modelOptions.value = Array.isArray(result.models) ? result.models : []
  } catch {
    if (seq !== requestSeq) return
    modelResult.value = null
    modelOptions.value = []
  } finally {
    if (seq === requestSeq) modelLoading.value = false
  }
}

watch(
  () => [props.modelValue, props.node?.id, config.value.provider] as const,
  () => refreshModels(),
  { immediate: true }
)

function optionsFor(field: ConfigField): ConfigOption[] {
  if (field.dynamic === 'providerModels' && modelOptions.value.length) {
    return modelOptions.value.map((model) => ({ label: model, value: model }))
  }
  return field.options || []
}

// ---- 输出字段别名 / 隐藏 ----
function outputOverride(key: string): { alias: string; hidden: boolean } {
  const items = (config.value.outputFields || []) as NodeOutputFieldConfig[]
  const found = items.find((item) => item.key === key)
  return { alias: found?.alias || '', hidden: !!found?.hidden }
}

function setOutputOverride(key: string, patch: { alias?: unknown; hidden?: boolean }) {
  const items = [...((config.value.outputFields || []) as NodeOutputFieldConfig[])]
  const index = items.findIndex((item) => item.key === key)
  const current = index >= 0 ? items[index] : { key, alias: '', hidden: false }
  const alias = patch.alias === undefined ? (current.alias || '') : String(patch.alias ?? '')
  const hidden = patch.hidden === undefined ? !!current.hidden : !!patch.hidden
  const next: NodeOutputFieldConfig = { key, alias, hidden }
  if (!alias && !hidden) {
    if (index >= 0) items.splice(index, 1)
  } else if (index >= 0) {
    items[index] = next
  } else {
    items.push(next)
  }
  config.value.outputFields = items
}

// ---- 点击变量插入到最近聚焦的输入框 ----
let activeKey = ''
let activeEl: HTMLInputElement | HTMLTextAreaElement | null = null

function onFieldFocus(key: string, event: FocusEvent) {
  activeKey = key
  activeEl = event.target as HTMLInputElement | HTMLTextAreaElement | null
}

function insertRef(token: string) {
  if (!activeKey) {
    ElMessage.info('先点一下要插入的输入框')
    return
  }
  const current = String(config.value[activeKey] ?? '')
  const el = activeEl
  let caret = current.length
  if (el && el.value === current) {
    const start = el.selectionStart ?? current.length
    const end = el.selectionEnd ?? current.length
    config.value[activeKey] = current.slice(0, start) + token + current.slice(end)
    caret = start + token.length
  } else {
    config.value[activeKey] = current + token
  }
  nextTick(() => {
    if (el) {
      el.focus()
      el.setSelectionRange?.(caret, caret)
    }
  })
}

const selfOutputKeys = computed(() => {
  const value = nodeOutput.value
  return value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value) : []
})

function selfRef(key: string) {
  return buildRef(props.node.id, key, hasValueKeyOf(props.definition)).safe
}

watch(
  () => props.node?.id,
  () => {
    Object.keys(kvRows).forEach((key) => delete kvRows[key])
    activeKey = ''
    activeEl = null
    if (!props.node) return
    props.definition?.configSchema?.forEach((field: any) => {
      if (field.type === 'outputSchema') return
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

.config__section {
  margin: 18px 0 10px;
  padding-top: 12px;
  border-top: 1px solid #262a36;
  font-size: 11px;
  color: #8b93a7;
  letter-spacing: 0.04em;
}

.config__help {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.5;
  color: #6b7387;
}

.config__model-state {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
  font-size: 11px;
  color: #8b93a7;
}

.config__collapse {
  margin-bottom: 4px;
}

.config__out-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.config__out-key {
  width: 86px;
  flex: none;
  font-size: 11px;
  color: #c7ccd8;
  overflow: hidden;
  text-overflow: ellipsis;
}

.config__upstream {
  margin-bottom: 12px;
}

.config__upstream-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 11px;
  color: #8b93a7;
}

.config__upstream-head .mono {
  color: #c7ccd8;
}

.config__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.config__chip {
  cursor: pointer;
}

.config__tokens-pre {
  max-height: 200px;
  overflow: auto;
  margin: 0;
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
