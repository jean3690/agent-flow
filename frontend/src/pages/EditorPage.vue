<template>
  <div v-loading="loading" class="editor">
    <header class="editor__bar">
      <div class="editor__left">
        <el-button link @click="back">← 工作流</el-button>
        <el-input v-model="name" class="editor__name" placeholder="未命名工作流" :disabled="!ready" />
        <span class="editor__meta">{{ nodes.length }} 个节点 / v{{ detail?.version || 1 }}</span>
        <span v-if="detail?.publishedVersion" class="editor__published">
          线上 v{{ detail.publishedVersion }}
        </span>
        <span v-if="dirty" class="editor__dirty">未保存</span>
      </div>
      <div class="editor__right">
        <el-button size="small" :disabled="!ready || !canUndo" @click="undo">撤销</el-button>
        <el-button size="small" :disabled="!ready || !canRedo" @click="redo">重做</el-button>
        <el-button size="small" :disabled="!ready" @click="autoLayout">自动布局</el-button>
        <el-button size="small" :disabled="!ready" @click="openHistory">执行历史</el-button>
        <el-button size="small" :disabled="!ready" @click="triggerOpen = true">触发器</el-button>
        <el-button size="small" :disabled="!ready || saving" @click="versionOpen = true">版本</el-button>
        <el-button size="small" :disabled="!ready || saving" :loading="publishing" :type="isCurrentPublished ? 'success' : 'warning'" plain @click="togglePublish">
          {{ isCurrentPublished ? '已发布' : '发布' }}
        </el-button>
        <el-button size="small" :disabled="!ready || publishing" :loading="saving" title="Ctrl/Cmd + S" @click="save()">保存</el-button>
        <el-button size="small" :disabled="!ready || saving || publishing" type="primary" @click="run">调试运行</el-button>
      </div>
    </header>

    <el-result v-if="loadError" icon="error" title="工作流加载失败" :sub-title="loadError">
      <template #extra><el-button type="primary" @click="load">重试</el-button></template>
    </el-result>
    <div v-else-if="ready" class="editor__body">
      <NodePanel @add="addNodeCenter" />
      <FlowCanvas
        ref="canvasRef"
        v-model:nodes="nodes"
        v-model:edges="edges"
        class="editor__canvas"
        @select="onSelect"
        @add-node="addNode"
      />
    </div>

    <NodeConfigDrawer
      v-model="configOpen"
      :node="selectedNode"
      :definition="selectedDefinition"
      :nodes="nodes"
      :edges="edges"
      @remove="removeSelected"
    />

    <DebugDrawer v-model="debugOpen" :workflow-id="id" :nodes="nodes" :resume-run-id="resumeRunId" />

    <TriggerDrawer v-model="triggerOpen" :workflow-id="id" />

    <VersionDrawer
      v-model="versionOpen"
      :workflow-id="id"
      :current-version="detail?.version || 1"
      :published-version="detail?.publishedVersion"
      @changed="onVersionChanged"
    />

    <el-drawer v-model="historyOpen" title="执行历史" direction="rtl" size="520px">
      <div v-loading="historyLoading" class="history">
        <div v-for="item in executions" :key="item.runId" class="history__item">
          <div class="history__row">
            <span class="history__status" :class="'is-' + item.status.toLowerCase()">{{ item.status }}</span>
            <span class="history__time">{{ formatDate(item.startedAt) }}</span>
            <span class="history__elapsed">{{ item.elapsedMs }}ms</span>
          </div>
          <div class="history__meta mono">{{ item.runId }}</div>
          <div v-if="item.errorMessage" class="history__error">{{ item.errorMessage }}</div>
          <el-button link type="primary" size="small" @click="inspect(item.runId)">查看节点日志</el-button>
        </div>
        <div v-if="!executions.length" class="history__empty">还没有执行记录</div>
      </div>
    </el-drawer>

    <el-dialog v-model="inspectVisible" title="节点日志" width="640px">
      <div v-if="inspectDetail" class="inspect">
        <div class="inspect__head">
          <span class="mono">{{ inspectDetail.runId }}</span>
          <span>{{ inspectDetail.status }} / {{ inspectDetail.elapsedMs }}ms</span>
        </div>
        <div v-for="node in inspectDetail.nodes" :key="node.nodeId" class="inspect__node">
          <div class="inspect__row">
            <span class="inspect__name">{{ node.nodeName }} ({{ node.nodeType }})</span>
            <span class="inspect__status" :class="'is-' + node.status.toLowerCase()">{{ node.status }}</span>
            <span class="inspect__elapsed">{{ node.elapsedMs }}ms</span>
          </div>
          <OutputPreview v-if="node.output" :value="node.output" class="inspect__preview" />
          <div v-if="node.errorMessage" class="inspect__error">{{ node.errorMessage }}</div>
        </div>
        <div class="inspect__row">
          <span class="inspect__name">最终输出</span>
        </div>
        <OutputPreview :value="inspectDetail.output" class="inspect__preview" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import NodePanel from '../components/NodePanel.vue'
import FlowCanvas from '../components/FlowCanvas.vue'
import NodeConfigDrawer from '../components/NodeConfigDrawer.vue'
import DebugDrawer from '../components/DebugDrawer.vue'
import TriggerDrawer from '../components/TriggerDrawer.vue'
import VersionDrawer from '../components/VersionDrawer.vue'
import OutputPreview from '../components/OutputPreview.vue'
import { executionApi, workflowApi } from '../api'
import { useWorkflowStore } from '../stores/workflow'
import type { ExecutionDetail, ExecutionSummary, WorkflowDetail } from '../types'

const route = useRoute()
const router = useRouter()
const id = Number(route.params.id)
const workflowStore = useWorkflowStore()

const canvasRef = ref<any>(null)
const detail = ref<WorkflowDetail | null>(null)
const name = ref('')
const description = ref('')
const nodes = ref<any[]>([])
const edges = ref<any[]>([])
const selectedNode = ref<any>(null)
const configOpen = ref(false)
const debugOpen = ref(false)
const resumeRunId = ref('')
const historyOpen = ref(false)
const triggerOpen = ref(false)
const versionOpen = ref(false)
const inspectVisible = ref(false)
const saving = ref(false)
const publishing = ref(false)
const loading = ref(true)
const loadError = ref('')
const ready = computed(() => !loading.value && !loadError.value && !!detail.value)
const savedDraft = ref('')
// Compare only persisted fields, not Vue Flow's transient selection/dimensions.
const draft = computed(() => JSON.stringify(savePayload()))
const dirty = computed(() => !!savedDraft.value && draft.value !== savedDraft.value)
let savePromise: Promise<boolean> | null = null
const historyLoading = ref(false)
const executions = ref<ExecutionSummary[]>([])
const inspectDetail = ref<ExecutionDetail | null>(null)

const selectedDefinition = computed(() => {
  if (!selectedNode.value) return null
  return workflowStore.definitionMap[selectedNode.value.data.kind] || null
})

const isCurrentPublished = computed(
  () => !dirty.value && !!detail.value?.publishedVersion && detail.value.publishedVersion === detail.value.version
)

async function togglePublish() {
  if (!ready.value || publishing.value) return
  if (isCurrentPublished.value) {
    versionOpen.value = true
    return
  }
  publishing.value = true
  try {
    if (!(await ensureSaved())) return
    const result = await workflowApi.publish(id)
    detail.value = result
    ElMessage.success('已发布 v' + result.version)
  } catch {
    // The shared request interceptor displays API errors.
  } finally {
    publishing.value = false
  }
}

async function onVersionChanged() {
  await load()
}

function toVueNode(node: any) {
  return {
    id: node.id,
    type: 'flow',
    position: node.position || { x: 0, y: 0 },
    data: {
      kind: node.type,
      name: node.name,
      config: node.config || {}
    }
  }
}

type Snapshot = { name: string; description: string; nodes: any[]; edges: any[] }

const history = ref<Snapshot[]>([])
const historyIndex = ref(-1)
const snapshotText = computed(() => JSON.stringify(takeSnapshot()))
const hasPendingHistory = computed(() => historyIndex.value >= 0 && snapshotText.value !== JSON.stringify(history.value[historyIndex.value]))
const canUndo = computed(() => historyIndex.value > 0 || hasPendingHistory.value)
const canRedo = computed(() => !hasPendingHistory.value && historyIndex.value < history.value.length - 1)
let historyTimer: ReturnType<typeof setTimeout> | null = null
let restoring = false

let clipboard: {
  nodes: { id: string; kind: string; name: string; config: any; position: { x: number; y: number } }[]
  edges: { source: string; target: string }[]
} | null = null

function takeSnapshot(): Snapshot {
  return {
    name: name.value,
    description: description.value,
    nodes: nodes.value.map((node) => ({
      id: node.id,
      type: 'flow',
      position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
      data: {
        kind: node.data.kind,
        name: node.data.name,
        config: JSON.parse(JSON.stringify(node.data.config || {}))
      }
    })),
    edges: edges.value.map((edge: any) => ({ id: edge.id, source: edge.source, target: edge.target }))
  }
}

function resetHistory() {
  if (historyTimer) clearTimeout(historyTimer)
  historyTimer = null
  history.value = [takeSnapshot()]
  historyIndex.value = 0
}

function scheduleHistory() {
  if (restoring) return
  if (historyTimer) clearTimeout(historyTimer)
  historyTimer = setTimeout(recordHistory, 250)
}

function recordHistory() {
  if (historyTimer) clearTimeout(historyTimer)
  historyTimer = null
  if (!hasPendingHistory.value) return
  history.value = history.value.slice(0, historyIndex.value + 1)
  history.value.push(takeSnapshot())
  if (history.value.length > 80) history.value.shift()
  historyIndex.value = history.value.length - 1
}

function applySnapshot(snapshot: Snapshot) {
  restoring = true
  name.value = snapshot.name
  description.value = snapshot.description
  nodes.value = JSON.parse(JSON.stringify(snapshot.nodes))
  edges.value = JSON.parse(JSON.stringify(snapshot.edges))
  selectedNode.value = null
  configOpen.value = false
  nextTick(() => {
    restoring = false
  })
}

function undo() {
  // Flush the debounce so an immediate undo restores the latest edit, not an
  // older snapshot. Selection changes never enter the history.
  recordHistory()
  if (!canUndo.value) return
  historyIndex.value -= 1
  applySnapshot(history.value[historyIndex.value])
}

function redo() {
  if (!canRedo.value) return
  if (historyTimer) clearTimeout(historyTimer)
  historyTimer = null
  historyIndex.value += 1
  applySnapshot(history.value[historyIndex.value])
}

function copySelection() {
  const selected = canvasRef.value?.getSelectedNodes?.() || []
  if (!selected.length) {
    ElMessage.info('先选择节点：Ctrl/Cmd+点击或 Shift+拖动框选')
    return false
  }
  const ids = new Set(selected.map((node: any) => node.id))
  clipboard = {
    nodes: selected.map((node: any) => ({
      id: node.id,
      kind: node.data.kind,
      name: node.data.name,
      config: JSON.parse(JSON.stringify(node.data.config || {})),
      position: { x: node.position.x, y: node.position.y }
    })),
    edges: edges.value
      .filter((edge: any) => ids.has(edge.source) && ids.has(edge.target))
      .map((edge: any) => ({ source: edge.source, target: edge.target }))
  }
  ElMessage.success('已复制 ' + clipboard.nodes.length + ' 个节点')
  return true
}

function pasteClipboard() {
  if (!clipboard || !clipboard.nodes.length) return
  const idMap = new Map<string, string>()
  const newNodes = clipboard.nodes.map((node) => {
    const newId = node.kind + '-' + Math.random().toString(36).slice(2, 8)
    idMap.set(node.id, newId)
    return {
      id: newId,
      type: 'flow',
      position: { x: node.position.x + 48, y: node.position.y + 48 },
      data: {
        kind: node.kind,
        name: node.name,
        config: JSON.parse(JSON.stringify(node.config))
      }
    }
  })
  const newEdges = clipboard.edges
    .map((edge) => {
      const source = idMap.get(edge.source)
      const target = idMap.get(edge.target)
      if (!source || !target) return null
      return { id: 'edge-' + source + '-' + target, source, target }
    })
    .filter(Boolean)
  nodes.value = [...nodes.value, ...newNodes]
  edges.value = [...edges.value, ...newEdges]
  ElMessage.success('已粘贴 ' + newNodes.length + ' 个节点')
}

function autoLayout() {
  if (!nodes.value.length) return
  const ids = nodes.value.map((node) => node.id)
  const indegree = new Map<string, number>(ids.map((id) => [id, 0]))
  const adjacency = new Map<string, string[]>(ids.map((id) => [id, []]))
  edges.value.forEach((edge: any) => {
    if (!indegree.has(edge.source) || !indegree.has(edge.target)) return
    adjacency.get(edge.source)!.push(edge.target)
    indegree.set(edge.target, (indegree.get(edge.target) || 0) + 1)
  })

  const level = new Map<string, number>(ids.map((id) => [id, 0]))
  const queue = ids.filter((id) => indegree.get(id) === 0)
  const visited = new Set<string>()
  while (queue.length) {
    const current = queue.shift()!
    visited.add(current)
    for (const next of adjacency.get(current) || []) {
      level.set(next, Math.max(level.get(next) || 0, (level.get(current) || 0) + 1))
      indegree.set(next, (indegree.get(next) || 1) - 1)
      if (indegree.get(next) === 0) queue.push(next)
    }
  }
  let maxLevel = Math.max(0, ...Array.from(level.values()))
  ids.forEach((id) => {
    if (!visited.has(id)) {
      maxLevel += 1
      level.set(id, maxLevel)
    }
  })

  const groups = new Map<number, string[]>()
  ids.forEach((id) => {
    const current = level.get(id) || 0
    groups.set(current, [...(groups.get(current) || []), id])
  })
  const positions = new Map<string, { x: number; y: number }>()
  Array.from(groups.keys())
    .sort((a, b) => a - b)
    .forEach((current) => {
      groups.get(current)!.forEach((id, index) => {
        positions.set(id, { x: 80 + current * 280, y: 80 + index * 150 })
      })
    })

  nodes.value = nodes.value.map((node) => ({
    ...node,
    position: positions.get(node.id) || node.position
  }))
  nextTick(() => canvasRef.value?.fitView?.({ padding: 0.25 }))
  ElMessage.success('已按拓扑层级自动布局')
}

function isTypingTarget(target: EventTarget | null) {
  const element = target as HTMLElement | null
  return !!element && (['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName) || element.isContentEditable)
}

function onKeydown(event: KeyboardEvent) {
  if (!(event.ctrlKey || event.metaKey) || !ready.value) return
  const key = event.key.toLowerCase()
  if (key === 's') {
    event.preventDefault()
    if (!publishing.value) void save()
    return
  }
  if (isTypingTarget(event.target)) return
  if (key === 'z') {
    event.preventDefault()
    if (event.shiftKey) redo()
    else undo()
  } else if (key === 'y') {
    event.preventDefault()
    redo()
  } else if (key === 'c') {
    if (copySelection()) event.preventDefault()
  } else if (key === 'v') {
    if (clipboard) {
      event.preventDefault()
      pasteClipboard()
    }
  }
}

watch(snapshotText, () => {
  if (ready.value && !restoring) scheduleHistory()
})

watch(
  () => ready.value ? route.query.resume : undefined,
  (resume) => {
    resumeRunId.value = typeof resume === 'string' ? resume : ''
    if (resumeRunId.value) debugOpen.value = true
  },
  { immediate: true }
)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    await workflowStore.loadDefinitions()
    const result = await workflowApi.detail(id)
    detail.value = result
    name.value = result.name
    description.value = result.description || ''
    nodes.value = (result.flow?.nodes || []).map(toVueNode)
    edges.value = (result.flow?.edges || []).map((edge: any, index: number) => ({
      id: edge.id || 'edge-' + index,
      source: edge.source,
      target: edge.target
    }))
    selectedNode.value = null
    configOpen.value = false
    await nextTick()
    savedDraft.value = draft.value
    resetHistory()
  } catch (err: any) {
    loadError.value = err?.message || '请检查网络后重试'
  } finally {
    loading.value = false
  }
}

function serializeFlow() {
  return {
    name: name.value,
    engineType: 'langgraph',
    nodes: nodes.value.map((node) => ({
      id: node.id,
      type: node.data.kind,
      name: node.data.name,
      position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
      config: node.data.config || {}
    })),
    edges: edges.value.map((edge: any) => ({ id: edge.id, source: edge.source, target: edge.target }))
  }
}

function savePayload() {
  return {
    name: name.value,
    description: description.value,
    engineType: 'langgraph',
    status: detail.value?.status ?? 1,
    flow: serializeFlow()
  }
}

function save(silent = false): Promise<boolean> {
  if (savePromise) return savePromise
  if (!ready.value) return Promise.resolve(false)
  if (!name.value.trim()) {
    ElMessage.warning('请填写工作流名称')
    return Promise.resolve(false)
  }
  // Freeze the request payload before awaiting; later edits must stay dirty.
  const submittedDraft = draft.value
  const payload = JSON.parse(submittedDraft)
  saving.value = true
  savePromise = (async () => {
    try {
      const result = await workflowApi.update(id, payload)
      detail.value = result
      savedDraft.value = submittedDraft
      if (!silent) ElMessage.success(dirty.value ? '已保存，后续修改仍待保存' : '已保存')
      return true
    } catch {
      return false
    } finally {
      saving.value = false
      savePromise = null
    }
  })()
  return savePromise
}

async function ensureSaved() {
  if ((dirty.value || saving.value) && !(await save(true))) return false
  if (dirty.value) {
    ElMessage.warning('保存期间有新的修改，请再次保存后运行或发布')
    return false
  }
  return true
}

async function run() {
  if (!nodes.value.length) {
    ElMessage.warning('画布还没有节点')
    return
  }
  if (!ready.value || !(await ensureSaved())) return
  debugOpen.value = true
}

function addNode(type: string, position: { x: number; y: number }) {
  const model = workflowStore.createNode(type, position)
  nodes.value = [...nodes.value, toVueNode(model)]
}

function addNodeCenter(type: string) {
  const maxY = nodes.value.reduce((max, node) => Math.max(max, node.position.y), 0)
  addNode(type, { x: 220, y: maxY + 150 })
}

function onSelect(node: any) {
  selectedNode.value = node
  configOpen.value = !!node
}

function removeSelected() {
  if (!selectedNode.value) return
  const target = selectedNode.value.id
  nodes.value = nodes.value.filter((node) => node.id !== target)
  edges.value = edges.value.filter((edge: any) => edge.source !== target && edge.target !== target)
  selectedNode.value = null
  configOpen.value = false
}

async function openHistory() {
  historyOpen.value = true
  historyLoading.value = true
  try {
    const result = await workflowApi.executions(id, 1, 20)
    executions.value = result.records
  } finally {
    historyLoading.value = false
  }
}

async function inspect(runId: string) {
  inspectDetail.value = await executionApi.detail(runId)
  inspectVisible.value = true
}

function back() {
  router.push('/')
}

async function confirmLeave() {
  if (saving.value || publishing.value) {
    ElMessage.info('正在保存或发布，请稍候再离开')
    return false
  }
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('有未保存的修改，离开后将丢失。确定离开？', '未保存的修改', {
      confirmButtonText: '放弃修改并离开',
      cancelButtonText: '继续编辑',
      // Browser back/hash navigation fires hashchange before the guard resolves.
      closeOnHashChange: false,
      type: 'warning'
    })
    return true
  } catch {
    return false
  }
}

onBeforeRouteLeave(confirmLeave)
onBeforeRouteUpdate((to, from) => to.params.id !== from.params.id ? confirmLeave() : true)

function onBeforeUnload(event: BeforeUnloadEvent) {
  if (!dirty.value && !saving.value && !publishing.value) return
  event.preventDefault()
  event.returnValue = ''
}

function formatDate(value: string) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 19)
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('beforeunload', onBeforeUnload)
  await load()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('beforeunload', onBeforeUnload)
  if (historyTimer) clearTimeout(historyTimer)
})
</script>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.editor__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 52px;
  padding: 0 16px;
  border-bottom: 1px solid #262a36;
  background: #10131a;
  flex: none;
}

.editor__left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.editor__name {
  width: 260px;
}

.editor__meta {
  font-size: 11px;
  color: #6b7387;
  white-space: nowrap;
}

.editor__dirty {
  font-size: 11px;
  color: #f59e0b;
}

.editor__published {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  color: #4ade80;
  background: rgba(34, 197, 94, 0.14);
  white-space: nowrap;
}

.editor__right {
  display: flex;
  gap: 8px;
}

.editor__body {
  flex: 1;
  display: flex;
  min-height: 0;
}

.editor__canvas {
  flex: 1;
  min-width: 0;
}

.history__item {
  padding: 12px 0;
  border-bottom: 1px solid #232833;
}

.history__row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.history__status {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  background: #232833;
}

.history__status.is-success { background: rgba(34, 197, 94, 0.16); color: #4ade80; }
.history__status.is-failed { background: rgba(239, 68, 68, 0.16); color: #f87171; }
.history__status.is-running { background: rgba(245, 158, 11, 0.16); color: #fbbf24; }

.history__time {
  color: #8b93a7;
}

.history__elapsed {
  margin-left: auto;
  color: #6b7387;
}

.history__meta {
  margin: 6px 0;
  font-size: 11px;
  color: #4b5266;
}

.history__error {
  margin-bottom: 6px;
  font-size: 12px;
  color: #f87171;
}

.history__empty {
  padding: 30px 0;
  text-align: center;
  color: #4b5266;
  font-size: 12px;
}

.inspect__head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #8b93a7;
  margin-bottom: 12px;
}

.inspect__node {
  padding: 8px 0;
  border-top: 1px solid #232833;
}

.inspect__row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.inspect__name {
  font-weight: 600;
}

.inspect__status {
  font-size: 11px;
  color: #8b93a7;
}

.inspect__status.is-success { color: #4ade80; }
.inspect__status.is-failed { color: #f87171; }

.inspect__elapsed {
  margin-left: auto;
  color: #6b7387;
  font-size: 11px;
}

.inspect__preview {
  margin-top: 6px;
  max-height: 220px;
  overflow: auto;
}

.inspect__error {
  margin-top: 6px;
  font-size: 12px;
  color: #f87171;
}
</style>
