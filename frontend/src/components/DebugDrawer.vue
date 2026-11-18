<template>
  <el-drawer
    :model-value="modelValue"
    direction="btt"
    size="46%"
    :with-header="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="debug">
      <div class="debug__head">
        <div class="debug__title">调试运行</div>
        <div class="debug__actions">
          <span v-if="runStore.runId" class="debug__meta mono">run {{ runStore.runId.slice(0, 10) }}</span>
          <span v-if="runStore.elapsed" class="debug__meta">{{ runStore.elapsed }} ms</span>
          <el-button size="small" :disabled="runStore.running" type="primary" @click="run()">运行</el-button>
          <el-button
            v-if="runStore.failedRunId && !runStore.running"
            size="small"
            type="warning"
            @click="run(runStore.failedRunId)"
          >从失败点续跑</el-button>
          <el-button size="small" :disabled="!runStore.running" @click="runStore.stop()">停止</el-button>
          <el-button size="small" link @click="emit('update:modelValue', false)">收起</el-button>
        </div>
      </div>

      <div class="debug__body">
        <div class="debug__side">
          <div class="debug__label">输入 JSON</div>
          <el-input v-model="inputText" type="textarea" :rows="9" class="mono" />
          <div class="debug__label">节点状态</div>
          <div class="debug__nodes">
            <div
              v-for="node in nodes"
              :key="node.id"
              class="debug__node"
              :class="{ 'is-active': selectedNodeId === node.id }"
              @click="selectNode(node.id)"
            >
              <span class="debug__dot" :class="'is-' + (runStore.nodeStatus[node.id] || 'idle')" />
              <span class="debug__node-name">{{ node.data?.name || node.id }}</span>
              <span class="debug__node-status">{{ runStore.nodeStatus[node.id] || '待执行' }}</span>
            </div>
          </div>
        </div>

        <div class="debug__main">
          <el-tabs v-model="tab" class="debug__tabs">
            <el-tab-pane label="日志" name="logs">
              <div class="debug__logs">
                <div v-for="(entry, index) in runStore.logs" :key="index" class="debug__log" :class="'is-' + entry.level">
                  <span class="debug__time mono">{{ formatTime(entry.at) }}</span>
                  <span class="debug__msg">{{ entry.message }}</span>
                </div>
                <div v-if="!runStore.logs.length" class="debug__empty">还没有执行记录</div>
              </div>
            </el-tab-pane>

            <el-tab-pane label="输出" name="output">
              <div v-if="runStore.error" class="debug__error">{{ runStore.error }}</div>
              <OutputPreview v-if="runStore.outputText" :value="runStore.output" />
              <div v-else-if="!runStore.error" class="debug__empty">运行后在这里查看工作流输出</div>
            </el-tab-pane>

            <el-tab-pane label="节点输出" name="node">
              <div v-if="selectedNode" class="debug__node-head">
                <span class="debug__node-title">{{ selectedNode.data?.name || selectedNode.id }}</span>
                <span class="debug__meta">{{ selectedNode.data?.kind || selectedNode.type }}</span>
                <span v-if="selectedElapsed !== undefined" class="debug__meta">{{ selectedElapsed }} ms</span>
              </div>
              <OutputPreview v-if="selectedOutput !== undefined" :value="selectedOutput" />
              <div v-else class="debug__empty">{{ selectedNodeId ? '该节点没有输出' : '点击左侧节点查看该节点的输出' }}</div>
            </el-tab-pane>

            <el-tab-pane label="实时文本" name="tokens">
              <pre v-if="tokenText" class="debug__output mono">{{ tokenText }}</pre>
              <div v-else class="debug__empty">大模型节点流式输出的 token 会显示在这里</div>
            </el-tab-pane>
          </el-tabs>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRunStore } from '../stores/run'
import { executionApi } from '../api'
import OutputPreview from './OutputPreview.vue'

const props = defineProps<{
  modelValue: boolean
  workflowId: number
  nodes: any[]
  resumeRunId?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const runStore = useRunStore()
const tab = ref('logs')
const selectedNodeId = ref('')
const inputText = ref('{\n  "topic": "用三句话说明什么是 AI 工作流"\n}')

let loadedResumeId = ''
watch(
  () => props.modelValue ? props.resumeRunId : undefined,
  async (resumeRunId) => {
    if (!resumeRunId || resumeRunId === loadedResumeId) return
    loadedResumeId = resumeRunId
    try {
      const detail = await executionApi.detail(resumeRunId)
      if (detail.input && detail.input !== 'null') {
        inputText.value = detail.input
      }
      await run(resumeRunId)
    } catch {
      loadedResumeId = ''
      ElMessage.error('读取要续跑的执行记录失败')
    }
  },
  { immediate: true }
)

const tokenText = computed(() => Object.values(runStore.tokens).join('\n---\n'))
const selectedNode = computed(() => props.nodes.find((node) => node.id === selectedNodeId.value))
const selectedOutput = computed(() => (selectedNodeId.value ? runStore.nodeOutputs[selectedNodeId.value] : undefined))
const selectedElapsed = computed(() => (selectedNodeId.value ? runStore.nodeElapsed[selectedNodeId.value] : undefined))

function selectNode(nodeId: string) {
  selectedNodeId.value = nodeId
  tab.value = 'node'
}

function formatTime(value: number) {
  const date = new Date(value)
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

async function run(resumeRunId?: string) {
  let input: Record<string, any> = {}
  try {
    input = inputText.value.trim() ? JSON.parse(inputText.value) : {}
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      ElMessage.error('输入必须是 JSON 对象，例如 {"topic":"主题"}')
      return
    }
  } catch {
    ElMessage.error('输入不是合法 JSON')
    return
  }
  await runStore.start(props.workflowId, input, resumeRunId)
}
</script>

<style scoped>
.debug {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 14px 18px 18px;
}

.debug__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 10px;
  border-bottom: 1px solid #262a36;
}

.debug__title {
  font-size: 13px;
  font-weight: 600;
}

.debug__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.debug__meta {
  font-size: 11px;
  color: #6b7387;
}

.debug__body {
  flex: 1;
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  min-height: 0;
  padding-top: 12px;
}

.debug__side {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  overflow-y: auto;
}

.debug__label {
  margin-top: 4px;
  font-size: 11px;
  color: #6b7387;
}

.debug__nodes {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.debug__node {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 6px;
  border-radius: 6px;
  cursor: pointer;
}

.debug__node:hover {
  background: rgba(255, 255, 255, 0.04);
}

.debug__node.is-active {
  background: rgba(99, 102, 241, 0.16);
}

.debug__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4b5266;
}

.debug__dot.is-running { background: #f59e0b; }
.debug__dot.is-success { background: #22c55e; }
.debug__dot.is-failed { background: #ef4444; }
.debug__dot.is-canceled { background: #8b93a7; }
.debug__dot.is-interrupted { background: #f59e0b; }

.debug__node-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.debug__node-status {
  font-size: 11px;
  color: #6b7387;
}

.debug__node-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.debug__node-title {
  font-size: 12px;
  font-weight: 600;
}

.debug__main {
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.debug__logs {
  height: 100%;
  overflow-y: auto;
  font-size: 12px;
}

.debug__log {
  display: flex;
  gap: 10px;
  padding: 3px 0;
  color: #c7ccd8;
}

.debug__log.is-error { color: #f87171; }
.debug__log.is-success { color: #4ade80; }
.debug__log.is-warn { color: #fbbf24; }

.debug__time {
  color: #4b5266;
  flex: none;
}

.debug__output {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: #11141c;
  border: 1px solid #232833;
  font-size: 12px;
  line-height: 1.65;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
}

.debug__error {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(239, 68, 68, 0.12);
  color: #f87171;
  font-size: 12px;
}

.debug__empty {
  padding: 24px 0;
  text-align: center;
  font-size: 12px;
  color: #4b5266;
}

:deep(.el-tabs__item) {
  color: #8b93a7;
}

:deep(.el-tabs__item.is-active) {
  color: #e5e7eb;
}
</style>
