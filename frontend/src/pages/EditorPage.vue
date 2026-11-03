<template>
  <div class="editor">
    <header class="editor__bar">
      <div class="editor__left">
        <el-button link @click="back">← 工作流</el-button>
        <el-input v-model="name" class="editor__name" placeholder="未命名工作流" />
        <span class="editor__meta">{{ nodes.length }} 个节点 / v{{ detail?.version || 1 }}</span>
        <span v-if="dirty" class="editor__dirty">未保存</span>
      </div>
      <div class="editor__right">
        <el-button size="small" @click="openHistory">执行历史</el-button>
        <el-button size="small" :loading="saving" @click="save">保存</el-button>
        <el-button size="small" type="primary" @click="run">调试运行</el-button>
      </div>
    </header>

    <div class="editor__body">
      <NodePanel @add="addNodeCenter" />
      <FlowCanvas
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
      @remove="removeSelected"
    />

    <DebugDrawer v-model="debugOpen" :workflow-id="id" :nodes="nodes" :resume-run-id="resumeRunId" />

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
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import NodePanel from '../components/NodePanel.vue'
import FlowCanvas from '../components/FlowCanvas.vue'
import NodeConfigDrawer from '../components/NodeConfigDrawer.vue'
import DebugDrawer from '../components/DebugDrawer.vue'
import OutputPreview from '../components/OutputPreview.vue'
import { executionApi, workflowApi } from '../api'
import { useWorkflowStore } from '../stores/workflow'
import type { ExecutionDetail, ExecutionSummary, WorkflowDetail } from '../types'

const route = useRoute()
const router = useRouter()
const id = Number(route.params.id)
const workflowStore = useWorkflowStore()

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
const inspectVisible = ref(false)
const saving = ref(false)
const dirty = ref(false)
const historyLoading = ref(false)
const executions = ref<ExecutionSummary[]>([])
const inspectDetail = ref<ExecutionDetail | null>(null)

const selectedDefinition = computed(() => {
  if (!selectedNode.value) return null
  return workflowStore.definitionMap[selectedNode.value.data.kind] || null
})

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

async function load() {
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
  await nextTick()
  dirty.value = false
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

async function save(silent = false) {
  if (!name.value.trim()) {
    ElMessage.warning('请填写工作流名称')
    return false
  }
  saving.value = true
  try {
    const result = await workflowApi.update(id, {
      name: name.value,
      description: description.value,
      engineType: 'langgraph',
      status: 1,
      flow: serializeFlow()
    })
    detail.value = result
    dirty.value = false
    if (!silent) ElMessage.success('已保存')
    return true
  } catch {
    return false
  } finally {
    saving.value = false
  }
}

async function run() {
  if (!nodes.value.length) {
    ElMessage.warning('画布还没有节点')
    return
  }
  if (dirty.value) {
    const ok = await save(true)
    if (!ok) return
  }
  debugOpen.value = true
}

function addNode(type: string, position: { x: number; y: number }) {
  const model = workflowStore.createNode(type, position)
  nodes.value = [...nodes.value, toVueNode(model)]
  dirty.value = true
  selectedNode.value = nodes.value[nodes.value.length - 1]
  configOpen.value = true
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
  dirty.value = true
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

function formatDate(value: string) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 19)
}

onMounted(async () => {
  await load()
  const resume = typeof route.query.resume === 'string' ? route.query.resume : ''
  if (resume) {
    resumeRunId.value = resume
    debugOpen.value = true
  }
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
